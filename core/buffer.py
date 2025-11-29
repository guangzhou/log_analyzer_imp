# -*- coding: utf-8 -*-
from typing import List, Set
import hashlib, re

def _norm(s: str) -> str:
    s = re.sub(r'\s+', ' ', s).strip()
    s = re.sub(r'\d+', '{NUM}', s)
    return s

def _hash(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

class DiversityBuffer:
    def __init__(self, size_threshold: int = 100, max_per_micro_batch: int = 15):
        self.size_threshold = size_threshold
        self.max_per_micro_batch = max_per_micro_batch
        self.samples: List[str] = []
        self.hset: Set[str] = set()
        self._locked = False

    def pick_for_buffer(self, misses: List[str]) -> List[str]:
        out = []
        for m in misses:
            if len(out) >= self.max_per_micro_batch:
                break
            # nm = _norm(m)
            h = _hash(m)
            if h in self.hset:
                continue
            out.append(m)
        return out

    def add(self, picked: List[str]):
        for nm in picked:
            h = _hash(nm)
            if h not in self.hset:
                self.hset.add(h)
                self.samples.append(nm)

    def reached_threshold(self) -> bool:
        return (not self._locked) and len(self.samples) >= self.size_threshold

    def snapshot_and_lock(self) -> List[str]:
        self._locked = True
        return list(self.samples)

    def clear_locked_batch(self):
        self.samples.clear()
        self.hset.clear()
        self._locked = False
