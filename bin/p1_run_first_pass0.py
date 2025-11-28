#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, argparse, hashlib, threading
from store import dao
from core import reader, preprocessor, parser as parser_mod, matcher, buffer as buffer_mod, indexer as indexer_mod, committee, templates

def calc_file_id(path: str) -> str:
    st = os.stat(path)
    key = f"{path}|{int(st.st_mtime)}|{st.st_size}".encode("utf-8")
    return hashlib.sha256(key).hexdigest()[:32]

def write_normal_file(path: str, out_path: str, chunk_lines: int = 10000):
    total = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for chunk in reader.read_in_chunks(path, chunk_lines=chunk_lines):
            normed = preprocessor.normalize_lines(chunk)
            for line in normed:
                out.write(line + "\n")
                total += 1
    return total

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", required=True)
    ap.add_argument("--normal-out", default=None)
    ap.add_argument("--size-threshold", type=int, default=100)
    ap.add_argument("--max-per-micro-batch", type=int, default=15)
    ap.add_argument("--chunk-lines", type=int, default=10000)
    ap.add_argument("--micro-batch", type=int, default=20)
    ap.add_argument("--match-workers", type=int, default=4)
    args = ap.parse_args()

    path = args.path
    normal_path = args.normal_out or (path.rstrip(".gz") + ".normal.txt")

    file_id = calc_file_id(path)
    dao.register_file(file_id, path)

    run_id = dao.create_run_session(file_id, "第一遍", dict(chunk_lines=args.chunk_lines, micro_batch=args.micro_batch))

    pre_lines = write_normal_file(path, normal_path, chunk_lines=args.chunk_lines)

    mods, mod_smods, parsed_all = set(), set(), []
    for chunk in reader.read_in_chunks(normal_path, chunk_lines=args.chunk_lines):
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

    idx = indexer_mod.Indexer()
    idx.load_initial()
    dbuf = buffer_mod.DiversityBuffer(size_threshold=args.size_threshold, max_per_micro_batch=args.max_per_micro_batch)

    micro_batches = reader.split_micro_batches(parsed_all, size=args.micro_batch)
    for batch in micro_batches:
        results = matcher.match_batch(idx.get_active(), batch, workers=args.match_workers)
        misses = [r.key_text for r in results if not r.is_hit]
        picked = dbuf.pick_for_buffer(misses)
        dbuf.add(picked)

        if dbuf.reached_threshold():
            samples = dbuf.snapshot_and_lock()
            def _async_proc():
                cands = committee.run(samples, model="stub", phase="v1点0")
                if cands:
                    templates.write_candidates(cands)
                    idx.build_new_index_async()
                dbuf.clear_locked_batch()
            threading.Thread(target=_async_proc, daemon=True).start()

    dao.complete_run_session(run_id, total_lines=len(parsed_all), preprocessed_lines=pre_lines, unmatched_lines=0, status="成功")
    print(f"[OK] 第一遍完成 file_id={file_id}, normal={normal_path}")

if __name__ == "__main__":
    main()
