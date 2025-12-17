# -*- coding: utf-8 -*-
import atexit
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, NamedTuple, Optional, Any, Dict
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
    def __init__(self, items: List[dict],nomal=True):
        self.items = []
        pattern_key = "pattern_nomal" if nomal else "pattern"
        for it in items:
            if it.get("pattern_nomal"):
                try: 
                    compiled_pattern = re.compile(it[pattern_key]) 
                    self.items.append((it["template_id"],pattern_key , compiled_pattern)) 
                except re.error as e:
                    # 记录编译失败的 pattern，并从数据库删除对应的模板记录
                    template_id = it.get('template_id')
                    logger.error(f"Warning: Failed to compile pattern '{it[pattern_key]}' for template_id {template_id}: {e}")
                    
                    # 尝试从数据库删除对应的模板记录
                    if template_id is not None:
                        try:
                            success = deactivate_template(template_id)
                            if success:
                                logger.info(f"Successfully deactivated template_id {template_id} due to pattern compilation failure")
                            else:
                                logger.warning(f"Failed to deactivate template_id {template_id} - template may not exist or already inactive")
                        except Exception as db_error:
                            logger.error(f"Database error when deactivating template_id {template_id}: {db_error}")
                    
                    continue

    def match_one(self, text: str) -> Optional[int]:
        for tid, pat, creg in self.items:
            if creg.search(text):
                return tid
        return None


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


def _build_match_result(index_handle: CompiledIndex, parsed_line: Any) -> MatchResult:
    tid = index_handle.match_one(parsed_line.key_text)
    if tid is None:
        return MatchResult(False, None, None, None, parsed_line, parsed_line.key_text)
    return MatchResult(True, tid, None, None, parsed_line, parsed_line.key_text)


def match_batch(index_handle: CompiledIndex, parsed_batch: List[Any], workers: int = 4, nomal=True) -> List[MatchResult]:
    if not parsed_batch:
        return []

    workers = max(1, int(workers or 1))

    # 小批次直接串行处理，避免线程调度开销
    if workers == 1 or len(parsed_batch) <= workers * 4:
        return [_build_match_result(index_handle, p) for p in parsed_batch]

    executor = _get_executor(workers)
    # executor.map 会保持输入顺序，省去额外排序
    return list(executor.map(lambda p: _build_match_result(index_handle, p), parsed_batch))

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
