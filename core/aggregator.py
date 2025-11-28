
from collections import defaultdict
from datetime import datetime
from store import dao
class Aggregator:
    def __init__(self, run_id: int, granularity: str = "分钟"):
        self.run_id=run_id; self.granularity=granularity
        self.summary=defaultdict(lambda: {"first_ts":None,"last_ts":None,"count":0})
        self.bucket=defaultdict(int)
    def _bucket_start(self, ts: str):
        if not ts: return "1970-01-01 00:00:00"
        dt=datetime.strptime(ts, "%Y%m%d_%H%M%S"); dt=dt.replace(second=0)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    def update(self, file_id: str, template_id: int, mod: str, smod: str, classification: str, level: str | None, thread_id: str | None, ts: str):
        key=(file_id, template_id, mod, smod, level or "", thread_id or "")
        e=self.summary[key]
        if e["first_ts"] is None or ts < e["first_ts"]: e["first_ts"]=ts
        if e["last_ts"] is None or ts > e["last_ts"]: e["last_ts"]=ts
        e["count"]+=1
        bkey=(file_id, template_id, mod, smod, level or "", thread_id or "", self._bucket_start(ts), self.granularity)
        self.bucket[bkey]+=1
    def flush(self):
        for key, v in self.summary.items():
            file_id, template_id, mod, smod, level, thread_id = key
            dao.upsert_summary(self.run_id, file_id, template_id, mod, smod, "", level, thread_id, v["first_ts"].replace("_","-"), v["last_ts"].replace("_","-"), v["count"])
        for key, cnt in self.bucket.items():
            file_id, template_id, mod, smod, level, thread_id, bstart, gran = key
            dao.upsert_bucket(self.run_id, file_id, template_id, mod, smod, "", level, thread_id, gran, bstart, cnt)
