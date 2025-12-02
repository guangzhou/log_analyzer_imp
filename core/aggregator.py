# -*- coding: utf-8 -*-
from typing import Dict, Any, List, Tuple
from datetime import datetime
from collections import defaultdict
from store import dao

def _minute_bucket(ts: str) -> str:
    try:
        dt = datetime.strptime(ts, "%Y%m%d %H%M%S")
        return dt.replace(second=0).isoformat()
    except Exception:
        return ts

class Aggregator:
    def __init__(self, run_id: int, file_id: str, bucket_granularity: str = "minute", flush_lines: int = 2000):
        self.run_id = run_id
        self.file_id = file_id
        self.bucket_granularity = bucket_granularity
        self.flush_lines = flush_lines
        self.summary: Dict[Tuple, Dict[str, Any]] = {}
        self.time_bucket: Dict[Tuple, int] = defaultdict(int)
        self._line_acc = 0

    def add_match(self, template_id: int, mod: str, smod: str, classification: str,
                  level: str, thread_id: str, ts: str):
        key = (template_id, mod, smod, classification, level, thread_id)
        rec = self.summary.get(key)
        if not rec:
            rec = dict(run_id=self.run_id, file_id=self.file_id,
                       template_id=template_id, mod=mod, smod=smod,
                       classification=classification, level=level, thread_id=thread_id,
                       first_ts=ts, last_ts=ts, line_count=0)
            self.summary[key] = rec
        rec["last_ts"] = ts
        rec["line_count"] += 1
        self._line_acc += 1

        if self.bucket_granularity == "minute":
            b = _minute_bucket(ts)
            bkey = (template_id, mod, smod, classification, level, thread_id, b)
            self.time_bucket[bkey] += 1

        if self._line_acc >= self.flush_lines:
            self.flush()

    def flush(self):
        if not self.summary and not self.time_bucket:
            return
        if self.summary:
            dao.batch_upsert_log_match_summary(list(self.summary.values()))
        # if self.time_bucket:
        #     trows = []
        #     for (template_id, mod, smod, classification, level, thread_id, b), cnt in self.time_bucket.items():
        #         trows.append(dict(run_id=self.run_id, file_id=self.file_id,
        #                           template_id=template_id, mod=mod, smod=smod, classification=classification,
        #                           level=level, thread_id=thread_id, bucket_granularity=self.bucket_granularity,
        #                           bucket_start=b, count_in_bucket=cnt))
        #     dao.batch_upsert_key_time_bucket(trows)
        self.summary.clear()
        self.time_bucket.clear()
        self._line_acc = 0
