# -*- coding: utf-8 -*-
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, NamedTuple, Optional, Any
import logging
from core.utils.logger import get_logger 
logger = get_logger("myapp", level=logging.DEBUG, rotate="day")   
class MatchResult(NamedTuple):
    is_hit: bool
    template_id: Optional[int]
    pattern: Optional[str]
    parsed: Any  # ParsedLine
    key_text: str

class CompiledIndex:
    def __init__(self, items: List[dict]):
        self.items = []
        for it in items:
            if it.get("pattern"):
                try:
                    compiled_pattern = re.compile(it["pattern"])
                    self.items.append((it["template_id"], it["pattern"], compiled_pattern))
                except re.error as e:
                    # 记录编译失败的 pattern，但继续处理其他项
                    logger.error(f"Warning: Failed to compile pattern '{it['pattern']}' for template_id {it.get('template_id')}: {e}")
                    continue

    def match_one(self, text: str) -> Optional[int]:
        for tid, pat, creg in self.items:
            if creg.search(text):
                return tid
        return None

def match_batch(index_handle: CompiledIndex, parsed_batch: List[Any], workers: int = 4) -> List[MatchResult]:
        outs: List[MatchResult] = [None] * len(parsed_batch)  # type: ignore
        def _task(i):
            p = parsed_batch[i]
            tid = index_handle.match_one(p.key_text)
            if tid is None:
                return i, MatchResult(False, None, None, p, p.key_text)
            else:
                return i, MatchResult(True, tid, None, p, p.key_text)

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_task, i) for i in range(len(parsed_batch))]
            for fu in as_completed(futs):
                i, res = fu.result()
                outs[i] = res
        return outs
