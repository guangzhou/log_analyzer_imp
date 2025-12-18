# -*- coding: utf-8 -*-
"""
第二遍 P2: 在完整日志上做规则匹配，并将命中结果聚合写入 log_match_summary。

设计要点：
- 读取第一遍生成的 normal 文本（每行一条原始日志，已清洗 ANSI 控制字符）。
- 使用 core.parser.parse_fields 提取 ts / level / thread_id / mod / smod 等字段。
- 使用 Indexer + matcher.match_batch 做批量匹配（使用 regex_template.pattern，nomal=False）。
- 在进程内按 (template_id, mod, smod, classification, level, thread_id) 聚合
  first_ts / last_ts / line_count，最后一次性写入 log_match_summary。
"""
import os
import argparse
from typing import Dict, Any, List, Tuple, Optional, NamedTuple

from store import dao
from core import reader, parser as parser_mod, matcher, indexer as indexer_mod
from core.utils.config import load_yaml
import logging
from core.utils.logger import get_logger  
logger = get_logger("myapp", level=logging.DEBUG, rotate="day")   

def _derive_normal_path(path: str, override: str = None) -> str:
    """
    推导 normal 文本路径：
    - xxx.log.gz -> xxx.log.normal.txt
    - xxx.log    -> xxx.log.normal.txt
    """
    if override:
        return override
    base = path[:-3] if path.endswith(".gz") else os.path.splitext(path)[0]
    return base + ".normal.txt"


def _derive_uniq_tsv_path(normal_path: str, override: str = None) -> str:
    if override:
        return override
    base, _ = os.path.splitext(normal_path)
    return base + "_uniq_with_count.tsv"


def _calc_file_id(path: str) -> str:
    """
    与第一遍保持一致的 file_id 计算方式：
    路径 + mtime + size 做 SHA256，取前 32 位。
    """
    st = os.stat(path)
    key = f"{path}|{int(st.st_mtime)}|{st.st_size}".encode("utf-8")
    import hashlib

    return hashlib.sha256(key).hexdigest()[:32]


def _load_second_pass_cfg(app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    兼容不同命名的二遍配置字段，尽量不破坏你现有的 application.yaml。
    """
    sp = app_cfg.get("second_pass") or {}
    cfg: Dict[str, Any] = {}
    cfg["chunk_lines"] = (
        sp.get("chunk_lines")
        or sp.get("read_chunk_lines")
        or 10000
    )
    cfg["micro_batch"] = (
        sp.get("micro_batch")
        or sp.get("batch_size")
        or sp.get("micro_batch_size")
        or 500
    )
    cfg["match_workers"] = (
        sp.get("match_workers")
        or sp.get("match_workers_per_batch")
        or 4
    )
    cfg["bucket_granularity"] = sp.get("bucket_granularity") or "minute"
    cfg["agg_flush_lines"] = sp.get("agg_flush_lines") or 2000
    return cfg


class _KeyTextWrapper:
    __slots__ = ("key_text",)

    def __init__(self, key_text: str):
        self.key_text = key_text or ""


class _UniqAggRecord(NamedTuple):
    count: int
    key_text_norm: str
    key_text_raw: str
    mod: str
    smod: str
    level: str
    min_ts: str
    max_ts: str


def _load_uniq_records(path: str) -> List[_UniqAggRecord]:
    records: List[_UniqAggRecord] = []
    if not path or not os.path.exists(path):
        return records
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 6:
                # 旧格式，不包含扩展信息，返回空列表以触发回退
                return []
            try:
                count = int(parts[0])
            except ValueError:
                continue
            key_norm = parts[1].strip()
            mod = parts[2].strip() if len(parts) > 2 else ""
            smod = parts[3].strip() if len(parts) > 3 else ""
            min_ts = parts[4].strip() if len(parts) > 4 else ""
            max_ts = parts[5].strip() if len(parts) > 5 else ""
            level = parts[6].strip() if len(parts) > 6 else ""
            sample_norm = parts[7].strip() if len(parts) > 7 else key_norm
            sample_raw = parts[8].strip() if len(parts) > 8 else sample_norm
            records.append(
                _UniqAggRecord(
                    count=count,
                    key_text_norm=key_norm,
                    key_text_raw=sample_raw or sample_norm or key_norm,
                    mod=mod,
                    smod=smod,
                    level=level,
                    min_ts=min_ts,
                    max_ts=max_ts,
                )
            )
    return records


def _iter_batches(items: List[Any], size: int):
    size = max(1, int(size or 1))
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _update_summary_from_agg(
    summary: Dict[Tuple[int, str, str, str, str, str], Dict[str, Any]],
    file_id: str,
    run_id: int,
    template_id: int,
    record: _UniqAggRecord,
) -> None:
    mod = (record.mod or "").strip()
    smod = (record.smod or "").strip()
    level = (record.level or "").strip()
    classification = ""
    key = (template_id, mod, smod, classification, level, 0)
    first_ts = record.min_ts or record.max_ts or ""
    last_ts = record.max_ts or record.min_ts or ""
    row = summary.get(key)
    if row is None:
        summary[key] = dict(
            run_id=run_id,
            file_id=file_id,
            template_id=template_id,
            mod=mod,
            smod=smod,
            classification=classification,
            level=level,
            thread_id=0,
            first_ts=first_ts,
            last_ts=last_ts,
            line_count=record.count,
        )
    else:
        row["line_count"] = int(row.get("line_count", 0) or 0) + record.count
        if first_ts:
            prev_first = row.get("first_ts") or ""
            if not prev_first or first_ts < prev_first:
                row["first_ts"] = first_ts
        if last_ts:
            prev_last = row.get("last_ts") or ""
            if not prev_last or last_ts > prev_last:
                row["last_ts"] = last_ts


def _process_normal_mode(
    normal_path: str,
    chunk_lines: int,
    micro_batch: int,
    match_workers: int,
    idx: indexer_mod.Indexer,
    summary: Dict[Tuple[int, str, str, str, str, str], Dict[str, Any]],
    file_id: str,
    run_id: int,
) -> Tuple[int, int]:
    total_lines = 0
    matched_total = 0
    buffer: List[parser_mod.ParsedLine] = []

    def _consume_buffer() -> None:
        nonlocal matched_total
        if not buffer:
            return
        results = matcher.match_batch(
            idx.get_active(),
            buffer,
            workers=match_workers,
            nomal=False,
        )
        for parsed_line, res in zip(buffer, results):
            if not getattr(res, "is_hit", False):
                continue
            template_id = getattr(res, "template_id", None)
            if template_id is None:
                continue
            try:
                tid = int(template_id)
            except Exception:
                continue
            matched_total += 1
            _update_summary_from_line(summary, file_id, run_id, tid, parsed_line)
        buffer.clear()

    for chunk in reader.read_in_chunks(normal_path, chunk_lines=chunk_lines):
        for line in chunk:
            total_lines += 1
            line = line.strip()
            if not line:
                continue
            parsed = parser_mod.parse_fields(line)
            if parsed is None:
                continue
            buffer.append(parsed)
            if len(buffer) >= micro_batch:
                _consume_buffer()
        logger.info(
            "processed_lines: %d, matched_lines: %d (normal mode)",
            total_lines,
            matched_total,
        )

    _consume_buffer()
    return total_lines, matched_total


def _process_uniq_mode(
    records: List[_UniqAggRecord],
    micro_batch: int,
    match_workers: int,
    idx: indexer_mod.Indexer,
    summary: Dict[Tuple[int, str, str, str, str, str], Dict[str, Any]],
    file_id: str,
    run_id: int,
) -> Tuple[int, int]:
    total_lines = sum(r.count for r in records)
    matched_total = 0
    processed_rows = 0
    total_rows = len(records)
    for batch in _iter_batches(records, micro_batch):
        wrappers = [_KeyTextWrapper(r.key_text_raw or r.key_text_norm) for r in batch]
        results = matcher.match_batch(
            idx.get_active(),
            wrappers,
            workers=match_workers,
            nomal=False,
        )
        for record, res in zip(batch, results):
            if not getattr(res, "is_hit", False):
                continue
            template_id = getattr(res, "template_id", None)
            if template_id is None:
                continue
            try:
                tid = int(template_id)
            except Exception:
                continue
            matched_total += record.count
            _update_summary_from_agg(summary, file_id, run_id, tid, record)
        processed_rows += len(batch)
        logger.info(
            "[uniq-mode] processed uniq_rows: %d/%d, matched_lines: %d",
            processed_rows,
            total_rows,
            matched_total,
        )
    return total_lines, matched_total


def _update_summary_from_line(
    summary: Dict[Tuple[int, str, str, str, str, str], Dict[str, Any]],
    file_id: str,
    run_id: int,
    template_id: int,
    parsed: parser_mod.ParsedLine,
) -> None:
    """
    使用 parse_fields 提取到的字段更新一条汇总记录。
    维度：template_id, mod, smod, classification(暂空), level, thread_id
    """
    # ParsedLine 定义：ts, level, thread_id, mod, smod, key_text, raw
    mod = (parsed.mod or "").strip()
    smod = (parsed.smod or "").strip()
    level = (parsed.level or "").strip()
    thread_id = (parsed.thread_id or "").strip()
    ts = (parsed.ts or "").strip()
    classification = ""  # 目前不从模板库回填分类，保持为空串

    # key = (template_id, mod, smod, classification, level, thread_id)
    key = (template_id, mod, smod, classification, level, 0)
    row = summary.get(key)
    if row is None:
        summary[key] = dict(
            run_id=run_id,
            file_id=file_id,
            template_id=template_id,
            mod=mod,
            smod=smod,
            classification=classification,
            level=level,
            # thread_id=thread_id,
            thread_id=0,
            first_ts=ts,
            last_ts=ts,
            line_count=1,
        )
    else:
        # 行数累加
        row["line_count"] = int(row.get("line_count", 0) or 0) + 1
        # first_ts / last_ts 更新（ts 形如 "YYYYMMDD HHMMSS"，字符串比较即可）
        if ts:
            first_ts = row.get("first_ts") or ""
            last_ts = row.get("last_ts") or ""
            if not first_ts or ts < first_ts:
                row["first_ts"] = ts
            if not last_ts or ts > last_ts:
                row["last_ts"] = ts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="原始 gz 日志文件路径（或已解压的原始日志路径）")
    ap.add_argument(
        "--normal-in",
        default=None,
        help="第一遍生成的 normal 文本路径；若不指定，则按约定自动推导 *.normal.txt",
    )
    ap.add_argument(
        "--uniq-tsv",
        default=None,
        help="第一遍生成的 *_uniq_with_count.tsv 路径；若不指定，则与 normal 文件同名推导",
    )
    ap.add_argument("--chunk-lines", type=int, default=None, help="read_in_chunks 每块行数")
    ap.add_argument("--micro-batch", type=int, default=None, help="每批送给 matcher 的条数")
    ap.add_argument("--match-workers", type=int, default=None, help="匹配并发 worker 数")
    ap.add_argument("--config", type=str, default="configs/application.yaml", help="应用配置文件路径")
    args = ap.parse_args()

    app_cfg = load_yaml(args.config) or {}
    sp_cfg = _load_second_pass_cfg(app_cfg)

    chunk_lines = int(args.chunk_lines or sp_cfg["chunk_lines"])
    user_defined_micro = args.micro_batch is not None
    micro_batch = int(args.micro_batch or sp_cfg["micro_batch"])
    match_workers = int(args.match_workers or sp_cfg["match_workers"])
    bucket_granularity = sp_cfg["bucket_granularity"]
    # agg_flush_lines = int(sp_cfg["agg_flush_lines"])  # 当前版本不使用时间桶，可按需开启
    # 针对未显式指定 micro_batch 的情况，按 worker 数动态调整，减少调度开销
    min_recommended_batch = max(match_workers * 200, 1000)
    if micro_batch < min_recommended_batch:
        if user_defined_micro:
            logger.info(
                "micro_batch=%d 低于推荐阈值 %d，可能导致线程开销偏大",
                micro_batch,
                min_recommended_batch,
            )
        else:
            logger.info(
                "自动放大 micro_batch: %d -> %d，以降低线程调度开销",
                micro_batch,
                min_recommended_batch,
            )
            micro_batch = min_recommended_batch

    path = args.path
    normal_path = args.normal_in or _derive_normal_path(path)

    if not os.path.exists(normal_path):
        raise FileNotFoundError(f"normal 文件不存在: {normal_path}")

    # 与第一遍保持一致的 file_id
    file_id = _calc_file_id(path)
    dao.register_file(file_id, path)
    # rerun 前先清理旧的统计，避免重复写入
    dao.delete_log_match_summary_by_file(file_id)

    # 记录第二遍 run_session
    run_id = dao.create_run_session(
        file_id,
        "第二遍",
        dict(
            chunk_lines=chunk_lines,
            micro_batch=micro_batch,
            match_workers=match_workers,
            bucket_granularity=bucket_granularity,
        ),
    )

    # 加载“未归一化的正则”，用于原始日志匹配
    idx = indexer_mod.Indexer()
    idx.load_initial(nomal=False)

    uniq_tsv_path = _derive_uniq_tsv_path(normal_path, args.uniq_tsv)
    uniq_records = _load_uniq_records(uniq_tsv_path)

    summary: Dict[Tuple[int, str, str, str, str, str], Dict[str, Any]] = {}

    if uniq_records:
        expanded_total = sum(r.count for r in uniq_records)
        logger.info(
            "使用 uniq TSV 进行匹配: %s, uniq_rows=%d, expanded_lines=%d",
            uniq_tsv_path,
            len(uniq_records),
            expanded_total,
        )
        total_lines, matched_total = _process_uniq_mode(
            uniq_records,
            micro_batch,
            match_workers,
            idx,
            summary,
            file_id,
            run_id,
        )
    else:
        if args.uniq_tsv or os.path.exists(uniq_tsv_path):
            logger.info(
                "uniq TSV 不可用或格式不匹配，回退 normal 模式: %s",
                uniq_tsv_path,
            )
        total_lines, matched_total = _process_normal_mode(
            normal_path,
            chunk_lines,
            micro_batch,
            match_workers,
            idx,
            summary,
            file_id,
            run_id,
        )

    # 将聚合结果写入 log_match_summary
    if summary:
        dao.batch_upsert_log_match_summary(list(summary.values()))

    # 更新 run_session
    dao.complete_run_session(
        run_id,
        total_lines=total_lines,
        matched_lines=matched_total,
        status="成功",
    )
    print(
        f"[OK] 第二遍完成 file_id={file_id}, total_lines={total_lines}, matched_lines={matched_total}"
    )


if __name__ == "__main__":
    main()
