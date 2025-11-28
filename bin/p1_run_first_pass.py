# -*- coding: utf-8 -*-
"""
第一遍 P1: 规则演进与总规则更新
最小侵入式调整:
1) 写完 xx.normal.txt 后, 额外产出:
   - xx_uniq.txt: 关键文本排序去重
   - xx_uniq_with_count.tsv: 关键文本 + 在 normal 中出现的次数
2) 匹配与缓冲改为基于 xx_uniq.txt 的关键文本进行, 减少重复匹配
其余 LLM 阈值触发、模板写入、索引双缓冲与原子切换逻辑不变
"""
import os, argparse, threading, sys
from typing import List

# --- 现有依赖 ---
from store import dao
from core import reader, preprocessor, parser as parser_mod, matcher, buffer as buffer_mod, indexer as indexer_mod, committee, templates
from core.utils.config import load_yaml

# 新增: 关键文本抽取与去重计数
from core import keytext

# 新增: ANSI与控制字符清洗, 在生成 normal 之前做统一清洗
try:
    from preprocess.sanitizers import sanitize_line
except Exception:
    # 兼容相对执行路径
    ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from preprocess.sanitizers import sanitize_line

def calc_file_id(path: str) -> str:
    st = os.stat(path)
    key = f"{path}|{int(st.st_mtime)}|{st.st_size}".encode("utf-8")
    import hashlib as _hl
    return _hl.sha256(key).hexdigest()[:32]

def _derive_normal_path(path: str, override: str = None) -> str:
    if override:
        return override
    # 去掉 .gz 或最后一个扩展名, 生成 .normal.txt
    if path.endswith(".gz"):
        base = path[:-3]
    else:
        base, _ = os.path.splitext(path)
    if not base:
        base = path
    return base + ".normal.txt"

def _derive_uniq_paths(normal_path: str) -> tuple:
    base, _ = os.path.splitext(normal_path)
    uniq_txt = base + "_uniq.txt"
    uniq_tsv = base + "_uniq_with_count.tsv"
    return uniq_txt, uniq_tsv

def write_normal_file(path: str, out_path: str, chunk_lines: int = 10000) -> int:
    """
    在原有 normalize_lines 之前, 先对原始行做 ANSI/控制字符清洗。
    保持“一行一日志”与轻量标准化的一致性。
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    total = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for chunk in reader.read_in_chunks(path, chunk_lines=chunk_lines):
            # 逐行清洗 ANSI 控制符等
            cleaned = [sanitize_line(x) for x in chunk if x]
            # 继续走既有规整逻辑
            normed = preprocessor.normalize_lines(cleaned)
            for line in normed:
                out.write(line + "\n")
                total += 1
    return total

def build_uniq_files(normal_path: str, chunk_lines: int = 10000) -> tuple:
    """
    从 xx.normal.txt 抽取关键文本, 排序去重并计数:
    产出:
      - xx_uniq.txt
      - xx_uniq_with_count.tsv
    返回: (uniq_txt_path, uniq_tsv_path, uniq_count, uniq_distinct)
    """
    uniq_txt, uniq_tsv = _derive_uniq_paths(normal_path)

    # 统计计数
    counter = {}
    for chunk in reader.read_in_chunks(normal_path, chunk_lines=chunk_lines):
        for kt in keytext.iter_key_texts(chunk):
            counter[kt] = counter.get(kt, 0) + 1

    uniq_list = sorted(counter.keys())
    os.makedirs(os.path.dirname(uniq_txt) or ".", exist_ok=True)

    # 写 xx_uniq.txt
    with open(uniq_txt, "w", encoding="utf-8") as f1:
        for k in uniq_list:
            f1.write(k + "\n")

    # 写 xx_uniq_with_count.tsv (count \t key_text)
    with open(uniq_tsv, "w", encoding="utf-8") as f2:
        for k in uniq_list:
            f2.write(f"{counter[k]}\t{k}\n")

    uniq_count = sum(counter.values())
    uniq_distinct = len(uniq_list)
    return uniq_txt, uniq_tsv, uniq_count, uniq_distinct

class _KeyTextObj:
    """轻量包装, 仅提供 key_text 属性, 以复用 matcher.match_batch"""
    __slots__ = ("key_text",)
    def __init__(self, key_text: str):
        self.key_text = key_text

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="gz 日志文件路径")
    ap.add_argument("--normal-out", default=None, help="指定 normal 输出路径, 默认为同名 .normal.txt")
    ap.add_argument("--size-threshold", type=int, default=None, help="缓冲触发阈值 n")
    ap.add_argument("--max-per-micro-batch", type=int, default=None, help="每个微批最多入缓冲的未命中条数")
    ap.add_argument("--chunk-lines", type=int, default=None, help="大块读取行数")
    ap.add_argument("--micro-batch", type=int, default=None, help="微批大小")
    ap.add_argument("--match-workers", type=int, default=None, help="每批匹配并发 worker 数")
    ap.add_argument("--config", type=str, default="configs/application.yaml", help="应用配置")
    ap.add_argument("--await-llm", action="store_true", help="在进程退出前等待异步 LLM 处理完成")
    ap.add_argument("--force-flush", action="store_true", help="结束时强制冲洗缓冲区以触发一次 LLM")
    args = ap.parse_args()

    appcfg = load_yaml(args.config) or {}
    fp = appcfg.get("first_pass", {})
    bufcfg = fp.get("buffer", {})
    idxcfg = fp.get("indexer", {})
    cmcfg = fp.get("committee", {})

    chunk_lines = args.chunk_lines or fp.get("read_chunk_lines", 10000)
    micro_batch = args.micro_batch or fp.get("micro_batch_size", 20)
    match_workers = args.match_workers or fp.get("match_workers_per_batch", 4)
    size_threshold = args.size_threshold or bufcfg.get("size_threshold", 100)
    max_per_mb = args.max_per_micro_batch or bufcfg.get("max_per_micro_batch", 15)
    committee_backend = cmcfg.get("model", "stub")
    agents_cfg_path = cmcfg.get("config_path", "configs/agents.yaml")
    phase = cmcfg.get("phase", "v1点0")

    path = args.path
    normal_path = _derive_normal_path(path, args.normal_out)
    uniq_txt, uniq_tsv = _derive_uniq_paths(normal_path)

    # 注册文件与会话
    file_id = calc_file_id(path)
    dao.register_file(file_id, path)
    run_id = dao.create_run_session(file_id, "第一遍", dict(chunk_lines=chunk_lines, micro_batch=micro_batch))

    # 1) 写 normal
    pre_lines = write_normal_file(path, normal_path, chunk_lines=chunk_lines)

    # 2) 一次性抽取 MODULE/SUBMODULE 并 upsert
    mods, mod_smods, parsed_all = set(), set(), []
    for chunk in reader.read_in_chunks(normal_path, chunk_lines=chunk_lines):
        for line in chunk:
            p = parser_mod.parse_fields(line)
            if p:
                parsed_all.append(p)
                if p.mod:
                    mods.add(p.mod)
                if p.mod and p.smod:
                    mod_smods.add((p.mod, p.smod))
    dao.upsert_modules(mods)
    dao.upsert_submodules(mod_smods)

    # 3) 生成 uniq 文件
    uniq_txt, uniq_tsv, uniq_total, uniq_distinct = build_uniq_files(normal_path, chunk_lines=chunk_lines)
    print(f"[P1] 产物: uniq={uniq_txt} uniq_with_count={uniq_tsv} "
          f"normal_lines={pre_lines} uniq_total={uniq_total} uniq_distinct={uniq_distinct}")

    # 4) 装载活动索引与缓冲器
    idx = indexer_mod.Indexer()
    idx.load_initial()
    dbuf = buffer_mod.DiversityBuffer(size_threshold=size_threshold, max_per_micro_batch=max_per_mb)

    # 5) 用 uniq.txt 作为匹配输入, 切分微批
    with open(uniq_txt, "r", encoding="utf-8") as f:
        key_lines = [ln.rstrip("\n") for ln in f if ln.strip()]

    def _split_batches(items: List[str], size: int) -> List[List[str]]:
        return [items[i:i+size] for i in range(0, len(items), size)]

    micro_batches = _split_batches(key_lines, micro_batch)
    llm_threads: List[threading.Thread] = []

    for i, batch in enumerate(micro_batches, 1):
        objs = [_KeyTextObj(k) for k in batch]

        results = matcher.match_batch(idx.get_active(), objs, workers=match_workers)
        misses = [r.key_text for r in results if not getattr(r, "is_hit", False)]

        if misses:
            picked = dbuf.pick_for_buffer(misses)
            dbuf.add(picked)

        # 阈值触发异步 LLM
        if dbuf.reached_threshold():
            samples = dbuf.snapshot_and_lock()

            def _async_proc():
                try:
                    cands = committee.run(samples, model=committee_backend, phase=phase, config_path=agents_cfg_path)
                    if cands:
                        templates.write_candidates(cands)
                        idx.build_new_index_async()
                finally:
                    dbuf.clear_locked_batch()

            th = threading.Thread(target=_async_proc, daemon=True)
            th.start()
            llm_threads.append(th)

    # 结束时可选强制冲洗一次缓冲
    if args.force_flush:
        samples = dbuf.snapshot_and_lock()
        if samples:
            def _async_proc2():
                try:
                    cands = committee.run(samples, model=committee_backend, phase=phase, config_path=agents_cfg_path)
                    if cands:
                        templates.write_candidates(cands)
                        idx.build_new_index_async()
                finally:
                    dbuf.clear_locked_batch()
            th2 = threading.Thread(target=_async_proc2, daemon=True)
            th2.start()
            llm_threads.append(th2)

    if args.await_llm:
        for th in llm_threads:
            th.join()

    dao.complete_run_session(run_id, total_lines=len(parsed_all), preprocessed_lines=pre_lines, unmatched_lines=0, status="成功")
    print(f"[OK] 第一遍完成 file_id={file_id}, normal={normal_path}")

if __name__ == "__main__":
    main()
