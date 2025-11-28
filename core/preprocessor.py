# -*- coding: utf-8 -*-
import re
from typing import List

TS_PATTERN = re.compile(r'^\[\d{8}_\d{6}\]\[\d+\.\d+\]')

def normalize_lines(raw_lines: List[str]) -> List[str]:
    out = []
    cur = ""
    for line in raw_lines:
        if TS_PATTERN.match(line):
            if cur:
                out.append(cur)
            cur = line
        else:
            if not cur:
                cur = line
            else:
                cur = cur + " " + line.strip()
    if cur:
        out.append(cur)
    return out
