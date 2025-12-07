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
            # 返回当前缓存的一份拷贝，然后清空
            yield list(buf)
            buf.clear()

    # 优先使用系统 zcat 流式解压 .gz
    if path.endswith(".gz") and shutil_which("zcat"):
        # 关键修改：显式指定 encoding 和 errors="ignore"
        proc = subprocess.Popen(
            ["zcat", path],
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
        )
        try:
            for line in proc.stdout:
                buf.append(line.rstrip("\n"))
                if len(buf) >= chunk_lines:
                    for b in emit():
                        yield b
            for b in emit():
                yield b
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
            proc.wait()
    else:
        # 非 zcat 分支：普通文件或无 zcat 时用 Python 自己解压/读取
        opener = gzip.open if path.endswith(".gz") else open
        mode = "rt" if path.endswith(".gz") else "r"
        # 这里你已经加了 errors="ignore"
        with opener(path, mode, encoding="utf-8", errors="ignore") as f:
            for line in f:
                buf.append(line.rstrip("\n"))
                if len(buf) >= chunk_lines:
                    for b in emit():
                        yield b
            for b in emit():
                yield b


def split_micro_batches(lines: list, size: int = 20) -> List[list]:
    return [lines[i : i + size] for i in range(0, len(lines), size)]
