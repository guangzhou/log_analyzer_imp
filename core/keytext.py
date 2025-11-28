# -*- coding: utf-8 -*-
"""
核心工具: 关键文本抽取与去重计数
- 仅剥离行首连续中括号段, 保留正文中的中括号
- 提供统一的关键文本提取逻辑, 避免各处实现不一致
"""
import re
from typing import Iterable, Iterator, Tuple, List, Dict

# 行首连续的 [ ... ] 区段, 包含紧随的空白
_LEADING_BRACKETS = re.compile(r'^(?:\[[^\]\n]*\]\s*)+')

def extract_key_text(line: str) -> str:
    """
    输入: 已经过预处理标准化的一行日志文本
    输出: 去除了行首连续中括号段后的关键文本
    """
    if not line:
        return ""
    # 去除行首连续中括号段
    s = _LEADING_BRACKETS.sub('', line)
    # 收尾空白
    s = s.strip()
    return s

def iter_key_texts(lines: Iterable[str]) -> Iterator[str]:
    """对一批规整行抽取关键文本, 过滤空串"""
    for ln in lines:
        if not ln:
            continue
        kt = extract_key_text(ln)
        if kt:
            yield kt

def dedup_and_count(key_iter: Iterable[str]) -> Tuple[List[str], Dict[str, int]]:
    """
    对关键文本进行排序去重, 并统计出现次数
    返回:
      uniq_list: 去重后的关键文本列表(按字典序排序)
      count_map: {关键文本: 次数}
    """
    cnt: Dict[str, int] = {}
    for k in key_iter:
        cnt[k] = cnt.get(k, 0) + 1
    uniq_list = sorted(cnt.keys())
    return uniq_list, cnt
