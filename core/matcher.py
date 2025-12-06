# -*- coding: utf-8 -*-
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, NamedTuple, Optional, Any
import logging
from core.utils.logger import get_logger 
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
                    # 记录编译失败的 pattern，但继续处理其他项
                    logger.error(f"Warning: Failed to compile pattern '{it[pattern_key]}' for template_id {it.get('template_id')}: {e}")
                    continue

    def match_one(self, text: str) -> Optional[int]:
        for tid, pat, creg in self.items:
            if creg.search(text):
                return tid
        return None

def match_batch(index_handle: CompiledIndex, parsed_batch: List[Any], workers: int = 4, nomal=True) -> List[MatchResult]:
        outs: List[MatchResult] = [None] * len(parsed_batch)  # type: ignore
        def _task(i):
            p = parsed_batch[i]
            tid = index_handle.match_one(p.key_text)
            if tid is None:
                return i, MatchResult(False, None, None,None, p, p.key_text)
            else:
                return i, MatchResult(True, tid, None, None, p, p.key_text)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_task, i) for i in range(len(parsed_batch))]
            for fu in as_completed(futs):
                i, res = fu.result()
                outs[i] = res
        return outs
