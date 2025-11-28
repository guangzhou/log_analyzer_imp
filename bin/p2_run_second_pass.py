#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, argparse, hashlib
from store import dao
from core import reader, parser as parser_mod, matcher, indexer as indexer_mod, aggregator as aggregator_mod

def calc_file_id(path: str) -> str:
    st = os.stat(path)
    key = f"{path}|{int(st.st_mtime)}|{st.st_size}".encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:32]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True, help="normal 文件路径")
    ap.add_argument("--file-id", default="auto")
    ap.add_argument("--chunk-lines", type=int, default=10000)
    ap.add_argument("--micro-batch", type=int, default=20)
    ap.add_argument("--match-workers", type=int, default=4)
    args = ap.parse_args()

    path = args.path
    file_id = calc_file_id(path) if args.file_id == "auto" else args.file_id
    dao.register_file(file_id, path)

    run_id = dao.create_run_session(file_id, "第二遍", dict(chunk_lines=args.chunk_lines, micro_batch=args.micro_batch))

    idx = indexer_mod.Indexer()
    idx.load_initial()

    aggr = aggregator_mod.Aggregator(run_id=run_id, file_id=file_id, bucket_granularity="minute", flush_lines=2000)

    total_lines = 0
    unmatched = 0

    for chunk in reader.read_in_chunks(path, chunk_lines=args.chunk_lines):
        parsed = [p for line in chunk if (p := parser_mod.parse_fields(line))]
        micro_batches = reader.split_micro_batches(parsed, size=args.micro_batch)
        for batch in micro_batches:
            results = matcher.match_batch(idx.get_active(), batch, workers=args.match_workers)
            for r in results:
                total_lines += 1
                if r.is_hit and r.template_id is not None:
                    p = r.parsed
                    aggr.add_match(template_id=r.template_id, mod=p.mod, smod=p.smod, classification="", level=p.level, thread_id=p.thread_id, ts=p.ts)
                else:
                    unmatched += 1
                    dao.write_unmatched(run_id, file_id, r.key_text, r.parsed.raw if r.parsed else "")

        aggr.flush()

    dao.complete_run_session(run_id, total_lines=total_lines, preprocessed_lines=total_lines, unmatched_lines=unmatched, status="成功")
    print(f"[OK] 第二遍完成 file_id={file_id}, normal={path}, total={total_lines}, unmatched={unmatched}")

if __name__ == "__main__":
    main()
