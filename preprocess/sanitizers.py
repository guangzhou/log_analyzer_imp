# -*- coding: utf-8 -*-
"""
preprocess.sanitizers
提供基础清洗能力：
- 去除 ANSI 转义序列，如 \x1b[0m
- 去除控制字符，保留换行
- 供第一遍在折行前清洗
"""
import re

ANSI_ESCAPE_RE = re.compile(
    r"""
    (?:\x1B\[ [0-?]* [ -/]* [@-~])   # CSI
    | (?:\x1B\] .*? \x07)           # OSC 到 BEL
    | (?:\x1B[PXY^_].*?\x1B\\)      # DCS/PM/APC 到 ST
    | (?:\x1B[@-Z\\-_])             # 单字符 ESC
    """, re.VERBOSE
)

CTRL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

def sanitize_line(raw: str) -> str:
    if not raw:
        return raw
    s = ANSI_ESCAPE_RE.sub("", raw)
    s = s.replace("\r", "")
    s = CTRL_CHARS_RE.sub("", s)
    return s.rstrip("\n")
