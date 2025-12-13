# core/regex_safety.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from typing import List, Sequence, Optional, Dict, Any

import re as stdre  # 只用于静态分析

try:
    import regex  # 用于动态压测 + timeout
except ImportError as e:
    raise RuntimeError(
        "模块 'regex' 未安装，本模块需要用它做离线 timeout 检测。\n"
        "请先执行: pip install regex"
    ) from e


@dataclass
class RegexSafetyResult:
    pattern: str
    level: str              # "ok" | "warning" | "danger"
    compile_ok: bool
    static_flags: List[str]
    dynamic_timeout: bool
    runtime_error: Optional[str]
    timeout_text_preview: Optional[str]
    timeout_cost: Optional[float]
    samples_tested: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------- 更激进的静态红旗规则 ----------

def _static_red_flags(pattern: str) -> List[str]:
    """
    返回静态可疑特征列表。

    这里宁可多报一点“嫌疑人”，也不要漏掉真正危险的。
    """
    flags: List[str] = []

    # 1) 嵌套量词，如: (.+)+、(\w+)*、(?:[A-Z]+)+ 等
    #   粗暴一点：括号里有量词，括号外又跟量词
    if stdre.search(r"\((?:[^()]*?[+*?][^()]*)\)[+*?]", pattern):
        flags.append("nested_quantifier_group")

    # 2) 多个 dot-star / plus 组合，容易产生大量回溯
    if ".*.*" in pattern or ".*.+" in pattern or ".+.*" in pattern:
        flags.append("multiple_dot_star_like")

    # 3) 大分支 + 量词，例如 (foo|bar|baz|...)+
    if stdre.search(r"\((?:[^()]*\|){3,}[^()]*\)[+*?]", pattern):
        flags.append("large_alternation_with_quantifier")

    # 4) 看起来比较长、而且没有锚点的正则，也标个 flag 提醒
    if len(pattern) > 120 and not stdre.search(r"^\^|\$$", pattern):
        flags.append("long_unanchored_pattern")
    if stdre.search(
        r"(?:\(\?:[^)]*?\w[+*][^)]*\)[+*])\s*(?:\\w[+*]|\(\?:[^)]*?\\w[^)]*\)[+*])",
        pattern,
    ):
        flags.append("adjacent_quantified_words")
    return flags


# ---------- 动态压测：构造更“狠”的测试文本 ----------

def _make_test_strings(pattern: str, sample_texts: Sequence[str]) -> List[str]:
    tests: List[str] = []

    # 先把样例日志塞进去
    for t in sample_texts:
        if t and t not in tests:
            tests.append(t)

    # 通用基础样本（短）
    generic_short = [
        "a",
        "0",
        " ",
        "NUMNUM",
        "test",
    ]

    # 中等长度样本
    generic_mid = [
        "a" * 64,
        "0" * 64,
        " " * 64,
        "x" * 64 + "y",
    ]

    # 长样本（更容易踩到灾难路径）
    generic_long = [
        "a" * 512,
        "0" * 512,
        "x" * 512 + "y",
        " " * 512,
    ]

    for t in generic_short + generic_mid + generic_long:
        if t not in tests:
            tests.append(t)

    # 针对 NUMNUM 的模式，构造大量 NUMNUM 串
    if "NUMNUM" in pattern:
        nn1 = (" NUMNUM" * 64).strip()
        nn2 = ("NUMNUM " * 64).strip()
        nn3 = (" NUMNUM" * 128).strip()
        for t in (nn1, nn2, nn3):
            if t not in tests:
                tests.append(t)

    # 把样例日志放大几倍，模拟真实长日志
    for t in list(sample_texts):
        if not t:
            continue
        long_t = (t + " ") * 5
        if len(long_t) > 4000:
            long_t = long_t[:4000]
        if long_t not in tests:
            tests.append(long_t)

    # 去重
    seen = set()
    out: List[str] = []
    for t in tests:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


# ---------- 核心检测函数 ----------

def analyze_regex_safety(
    pattern: str,
    sample_texts: Optional[Sequence[str]] = None,
    timeout_sec: float = 0.5,
) -> RegexSafetyResult:
    """
    对单个正则做“离线安全检测”：

      - 静态：检查典型的灾难回溯结构；
      - 动态：对多组文本做 regex.search(text, timeout=timeout_sec) 压测。

    注意：这里是“激进模式”：
      * 只要有静态红旗，就至少是 warning；
      * 线上推荐：直接把 warning 也当 danger 禁用。
    """
    static_flags = _static_red_flags(pattern)
    samples = list(sample_texts or [])

    # 1. 编译检测
    try:
        creg = regex.compile(pattern)
        compile_ok = True
    except regex.error as e:
        return RegexSafetyResult(
            pattern=pattern,
            level="danger",
            compile_ok=False,
            static_flags=static_flags,
            dynamic_timeout=False,
            runtime_error=str(e),
            timeout_text_preview=None,
            timeout_cost=None,
            samples_tested=0,
        )

    # 2. 动态压测
    tests = _make_test_strings(pattern, samples)
    dynamic_timeout = False
    runtime_error: Optional[str] = None
    timeout_text_preview: Optional[str] = None
    timeout_cost: Optional[float] = None
    tested = 0

    for text in tests:
        if not text:
            continue

        t0 = time.perf_counter()
        try:
            creg.search(text, timeout=timeout_sec)
        except TimeoutError:
            dynamic_timeout = True
            timeout_text_preview = text[:200]
            timeout_cost = time.perf_counter() - t0
            break
        except regex.error as e:
            runtime_error = str(e)
            break
        else:
            cost = time.perf_counter() - t0
            # 虽然没抛 TimeoutError，但耗时超过阈值，也视作 timeout 风险
            if cost > timeout_sec:
                dynamic_timeout = True
                timeout_text_preview = text[:200]
                timeout_cost = cost
                break

        tested += 1

    # 3. 结果等级：
    #   - danger: 编译失败 / 动态超时 / 运行时异常
    #   - warning: 动态 OK，但有静态红旗
    #   - ok: 都没问题
    if not compile_ok or dynamic_timeout or runtime_error:
        level = "danger"
    elif "nested_quantifier_group" in static_flags:
        level = "danger"
    elif static_flags:
        level = "warning"
    else:
        level = "ok"

    return RegexSafetyResult(
        pattern=pattern,
        level=level,
        compile_ok=compile_ok,
        static_flags=static_flags,
        dynamic_timeout=dynamic_timeout,
        runtime_error=runtime_error,
        timeout_text_preview=timeout_text_preview,
        timeout_cost=timeout_cost,
        samples_tested=tested,
    )


def check_regex_safety(pattern: str) -> bool:
    """
    简化版接口：返回这个 pattern 是否“足够安全”。

    默认策略：只要被判定为 danger，就认为不安全。
    （你可以在调用端：把 warning 也当 danger 一起禁用）
    """
    r = analyze_regex_safety(pattern)
    return r.level != "danger"
