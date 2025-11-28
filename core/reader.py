# -*- coding: utf-8 -*-
import os, subprocess, gzip
from typing import Iterable, List

def shutil_which(cmd: str):
    import shutil
    return shutil.which(cmd)

def read_in_chunks(path: str, chunk_lines: int = 10000) -> Iterable[list]:
    buf = []
    def emit():
        nonlocal buf
        if buf:
            yield list(buf)
            buf.clear()

    if path.endswith(".gz") and shutil_which("zcat"):
        proc = subprocess.Popen(["zcat", path], stdout=subprocess.PIPE, text=True, bufsize=1)
        try:
            for line in proc.stdout:
                buf.append(line.rstrip("\n"))
                if len(buf) >= chunk_lines:
                    for b in emit(): yield b
            for b in emit(): yield b
        finally:
            proc.stdout.close()
            proc.wait()
    else:
        opener = gzip.open if path.endswith(".gz") else open
        mode = "rt" if path.endswith(".gz") else "r"
        with opener(path, mode, encoding="utf-8", errors="ignore") as f:
            for line in f:
                buf.append(line.rstrip("\n"))
                if len(buf) >= chunk_lines:
                    for b in emit(): yield b
            for b in emit(): yield b

def split_micro_batches(lines: list, size: int = 20) -> List[list]:
    return [lines[i:i+size] for i in range(0, len(lines), size)]
