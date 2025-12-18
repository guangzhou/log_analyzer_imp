# -*- coding: utf-8 -*-
import atexit
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import List, NamedTuple, Optional, Any, Dict, Tuple
import logging
from core.utils.logger import get_logger 
from store.dao import deactivate_template

logger = get_logger("myapp", level=logging.DEBUG, rotate="day")   


class MatchResult(NamedTuple):

    """
    用于存储匹配结果的命名元组类，继承自NamedTuple。
    包含匹配是否成功、模板ID、匹配模式、解析结果和关键文本等信息。
    """
    is_hit: bool  # 是否匹配成功的布尔值
    template_id: Optional[int]  # 可选的模板ID，整数类型或None
    pattern_nomal: Optional[str]  # 可选的标准模式，字符串类型或None（已注释）
    pattern: Optional[str]  # 可选的模式，字符串类型或None
    parsed: Any  # ParsedLine
    key_text: str


class CompiledIndex:
    def __init__(self, items: List[dict], nomal: bool = True, cache_size: int = 20000):
        self.items: List[Tuple[int, str, re.Pattern]] = []
        self.literal_bins: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        self.fallback_indices: List[int] = []
        pattern_key = "pattern_nomal" if nomal else "pattern"
        for it in items:
            raw = it.get(pattern_key)
            if not raw:
                continue
            try:
                compiled_pattern = re.compile(raw)
            except re.error as e:
                template_id = it.get("template_id")
                logger.error(
                    "Warning: Failed to compile pattern '%s' for template_id %s: %s",
                    raw,
                    template_id,
                    e,
                )
                if template_id is not None:
                    try:
                        success = deactivate_template(template_id)
                        if success:
                            logger.info(
                                "Successfully deactivated template_id %s due to pattern compilation failure",
                                template_id,
                            )
                        else:
                            logger.warning(
                                "Failed to deactivate template_id %s - template may not exist or already inactive",
                                template_id,
                            )
                    except Exception as db_error:
                        logger.error(
                            "Database error when deactivating template_id %s: %s",
                            template_id,
                            db_error,
                        )
                continue

            idx = len(self.items)
            self.items.append((it["template_id"], pattern_key, compiled_pattern))
            literal_hint = self._extract_literal_hint(raw)
            if literal_hint:
                self.literal_bins[literal_hint[0]].append((literal_hint, idx))
            else:
                self.fallback_indices.append(idx)

        self._match_one_cached = lru_cache(maxsize=cache_size)(self._match_one_uncached)

    @staticmethod
    def _extract_literal_hint(pattern: str) -> Optional[str]:
        """
        粗略提取模式中长度>=4的连续字面量片段，用于快速过滤候选模板。
        """
        literals: List[str] = []
        buf = []
        escape = False
        for ch in pattern:
            if escape:
                if ch.isalnum() or ch in "-_:/.":
                    buf.append(ch)
                else:
                    if len(buf) >= 4:
                        literals.append("".join(buf))
                    buf = []
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch.isalnum() or ch in "-_:/.":
                buf.append(ch)
            else:
                if len(buf) >= 4:
                    literals.append("".join(buf))
                buf = []
        if len(buf) >= 4:
            literals.append("".join(buf))
        if not literals:
            return None
        literals.sort(key=len, reverse=True)
        return literals[0]

    def _iter_candidates(self, text: str):
        yielded = set()
        text_chars = set(text)
        for ch in text_chars:
            for literal, idx in self.literal_bins.get(ch, []):
                if idx in yielded:
                    continue
                if literal in text:
                    yielded.add(idx)
                    yield self.items[idx]
        for idx in self.fallback_indices:
            if idx in yielded:
                continue
            yielded.add(idx)
            yield self.items[idx]

    def _match_one_uncached(self, text: str) -> Optional[int]:
        for tid, _, creg in self._iter_candidates(text):
            if creg.search(text):
                return tid
        return None

    def match_one(self, text: str) -> Optional[int]:
        return self._match_one_cached(text or "")

    def clear_cache(self) -> None:
        self._match_one_cached.cache_clear()


_executor_cache: Dict[int, ThreadPoolExecutor] = {}
_executor_lock = threading.Lock()


def _get_executor(workers: int) -> ThreadPoolExecutor:
    with _executor_lock:
        ex = _executor_cache.get(workers)
        if ex is None or getattr(ex, "_shutdown", False):
            ex = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="matcher")
            _executor_cache[workers] = ex
        return ex


def _shutdown_executors() -> None:
    with _executor_lock:
        for ex in _executor_cache.values():
            ex.shutdown(wait=True)
        _executor_cache.clear()


atexit.register(_shutdown_executors)


def match_batch(index_handle: CompiledIndex, parsed_batch: List[Any], workers: int = 4, nomal=True) -> List[MatchResult]:
    if not parsed_batch:
        return []

    workers = max(1, int(workers or 1))
    key_to_idx: Dict[str, int] = {}
    unique_key_texts: List[str] = []
    for parsed in parsed_batch:
        key = parsed.key_text or ""
        if key not in key_to_idx:
            key_to_idx[key] = len(unique_key_texts)
            unique_key_texts.append(key)

    def _match_keys(keys: List[str]) -> List[Optional[int]]:
        if workers == 1 or len(keys) <= workers * 4:
            return [index_handle.match_one(k) for k in keys]
        executor = _get_executor(workers)
        return list(executor.map(index_handle.match_one, keys))

    key_results = _match_keys(unique_key_texts)
    key_to_tid = {
        key: key_results[idx] for key, idx in key_to_idx.items()
    }

    outs: List[MatchResult] = []
    for parsed in parsed_batch:
        key = parsed.key_text or ""
        tid = key_to_tid.get(key)
        if tid is None:
            outs.append(MatchResult(False, None, None, None, parsed, key))
        else:
            outs.append(MatchResult(True, tid, None, None, parsed, key))
    return outs

# def match_batch_copy(index_handle: CompiledIndex, parsed_batch: List[Any], workers: int = 4, nomal=True) -> List[MatchResult]:
#         """
#         单线程版本的 match_batch，用于调试性能问题
#         """
#         outs: List[MatchResult] = [None] * len(parsed_batch)  # type: ignore
        
#         for i, p in enumerate(parsed_batch):
#             tid = index_handle.match_one(p.key_text)
#             if tid is None:
#                 outs[i] = MatchResult(False, None, None, None, p, p.key_text)
#             else:
#                 outs[i] = MatchResult(True, tid, None, None, p, p.key_text)
                
#         return outs
