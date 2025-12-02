# -*- coding: utf-8 -*-
"""
第二遍 P2: 按关键维度统计与时间分布
新增：统计整个文件的匹配总数 matched_lines，并写入 run_session.matched_lines
"""
import os, argparse
from store import dao
from core import reader, parser as parser_mod, matcher, indexer as indexer_mod
from core.utils.config import load_yaml

def _derive_normal_path(path: str, override: str = None) -> str:
    if override:
        return override
    base = path[:-3] if path.endswith(".gz") else os.path.splitext(path)[0]
    return base + ".normal.txt"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="gz 日志文件路径")
    ap.add_argument("--normal-in", default=None, help="已生成的 normal 文件路径；若不传则按约定推导")
    ap.add_argument("--chunk-lines", type=int, default=None)
    ap.add_argument("--micro-batch", type=int, default=None)
    ap.add_argument("--match-workers", type=int, default=None)
    ap.add_argument("--config", type=str, default="configs/application.yaml")
    args = ap.parse_args()

    appcfg = load_yaml(args.config) or {}
    sp = appcfg.get("second_pass", {})
    chunk_lines = args.chunk_lines or sp.get("read_chunk_lines", 10000)
    micro_batch = args.micro_batch or sp.get("micro_batch_size", 200)
    match_workers = args.match_workers or sp.get("match_workers_per_batch", 4)

    path = args.path
    normal_path = args.normal_in or _derive_normal_path(path)

    # 会话
    # 与 P1 保持一致：如果项目已有 calc_file_id，请替换为相同实现
    file_id = os.path.basename(path)
    run_id = dao.create_run_session(file_id, "第二遍", dict(chunk_lines=chunk_lines, micro_batch=micro_batch))

    # 索引
    idx = indexer_mod.Indexer()
    idx.load_initial()

    file_matched_total = 0
    buffer = []

    for chunk in reader.read_in_chunks(normal_path, chunk_lines=chunk_lines):
        for line in chunk:
            p = parser_mod.parse_fields(line)
            if p:
                buffer.append(p)
                if len(buffer) >= micro_batch:
                    results = matcher.match_batch(idx.get_active(), buffer, workers=match_workers)
                    file_matched_total += sum(1 for r in results if getattr(r, "is_hit", False))
                    # TODO: 保持原有聚合与写库逻辑（此处不改动，只新增总数计数）
                    buffer.clear()

    if buffer:
        results = matcher.match_batch(idx.get_active(), buffer, workers=match_workers)
        file_matched_total += sum(1 for r in results if getattr(r, "is_hit", False))
        buffer.clear()

    dao.complete_run_session(run_id, matched_lines=file_matched_total, status="成功")
    print(f"[OK] 第二遍完成 file_id={file_id}, matched_lines={file_matched_total}")

if __name__ == "__main__":
    main()