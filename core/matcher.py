# -*- coding: utf-8 -*-
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, NamedTuple, Optional, Any

class MatchResult(NamedTuple):
    is_hit: bool
    template_id: Optional[int]
    pattern: Optional[str]
    parsed: Any  # ParsedLine
    key_text: str

class CompiledIndex:
    def __init__(self, items: List[dict]):
        self.items = [(it["template_id"], it["pattern"], re.compile(it["pattern"])) for it in items if it.get("pattern")]

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
