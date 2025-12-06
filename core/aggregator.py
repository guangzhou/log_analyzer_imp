# -*- coding: utf-8 -*-
from typing import Dict, Any, List, Tuple
from datetime import datetime

from store import dao


def _minute_bucket(ts: str) -> str:
    """
    将 "YYYYMMDD HHMMSS" 形式的时间戳归一到分钟粒度。
    解析失败时直接返回原字符串，避免抛异常导致统计中断。
    """
    try:
        dt = datetime.strptime(ts, "%Y%m%d %H%M%S")
        return dt.replace(second=0).isoformat()
    except Exception:
        return ts


class Aggregator:
    """
    第二遍统计用的聚合器：
    - 按 (template_id, mod, smod, classification, level, thread_id) 维度聚合
    - 记录 first_ts / last_ts / line_count
    - 支持按分钟粒度做时间桶统计（暂未写库，可按需打开）
    """

    def __init__(self, run_id: int, file_id: str,
                 bucket_granularity: str = "minute",
                 flush_lines: int = 2000) -> None:
        self.run_id = run_id
        self.file_id = file_id
        self.bucket_granularity = bucket_granularity or "minute"
        self.flush_lines = int(flush_lines) if flush_lines else 2000

        # key: (template_id, mod, smod, classification, level, thread_id)
        # val: row dict 写入 log_match_summary
        self.summary: Dict[Tuple[int, str, str, str, str, str], Dict[str, Any]] = {}

        # key: (template_id, mod, smod, classification, level, thread_id, bucket_str)
        # val: count
        self.time_bucket: Dict[Tuple[int, str, str, str, str, str, str], int] = {}

        self._line_acc: int = 0

    def add_match(self,
                  template_id: int,
                  mod: str,
                  smod: str,
                  classification: str,
                  level: str,
                  thread_id: str,
                  ts: str) -> None:
        """
        template_id: 命中的模板 ID
        mod/smod: 模块/子模块
        classification: 分类标签（功能/性能等），没有就传 "" 即可
        level: 日志级别
        thread_id: 线程 ID
        ts: 原始时间戳字符串（尽量保持统一格式，如 "YYYYMMDD HHMMSS"）
        """
        try:
            tid = int(template_id)
        except Exception:
            return

        mod = (mod or "").strip()
        smod = (smod or "").strip()
        classification = (classification or "").strip()
        level = (level or "").strip()
        thread_id = (thread_id or "").strip()
        ts = (ts or "").strip()

        key = (tid, mod, smod, classification, level, thread_id)
        now = datetime.utcnow().isoformat()

        row = self.summary.get(key)
        if row is None:
            row = {
                "run_id": self.run_id,
                "file_id": self.file_id,
                "template_id": tid,
                "mod": mod,
                "smod": smod,
                "classification": classification,
                "level": level,
                "thread_id": thread_id,
                "first_ts": ts,
                "last_ts": ts,
                "line_count": 1,
                "updated_at": now,
            }
            self.summary[key] = row
        else:
            # 行数累加
            row["line_count"] = int(row.get("line_count") or 0) + 1
            # first_ts / last_ts 更新
            if ts:
                first_ts = row.get("first_ts") or ""
                last_ts = row.get("last_ts") or ""
                if not first_ts or ts < first_ts:
                    row["first_ts"] = ts
                if not last_ts or ts > last_ts:
                    row["last_ts"] = ts
            row["updated_at"] = now

        # 时间桶统计（按需打开）
        if ts and self.bucket_granularity == "minute":
            bucket = _minute_bucket(ts)
            bkey = (tid, mod, smod, classification, level, thread_id, bucket)
            self.time_bucket[bkey] = self.time_bucket.get(bkey, 0) + 1

        self._line_acc += 1
        if self._line_acc >= self.flush_lines:
            self.flush()

    def flush(self) -> None:
        """
        将当前累积的 summary / time_bucket 写入数据库。
        """
        if not self.summary and not self.time_bucket:
            return

        if self.summary:
            dao.batch_upsert_log_match_summary(list(self.summary.values()))

        # 如需启用时间桶统计，取消下面注释，并确保 key_time_bucket 表结构与 dao 中函数一致
        # if self.time_bucket:
        #     trows: List[Dict[str, Any]] = []
        #     for (template_id, mod, smod, classification, level, thread_id, b), cnt in self.time_bucket.items():
        #         trows.append(
        #             dict(
        #                 run_id=self.run_id,
        #                 file_id=self.file_id,
        #                 template_id=template_id,
        #                 mod=mod,
        #                 smod=smod,
        #                 classification=classification,
        #                 level=level,
        #                 thread_id=thread_id,
        #                 bucket_granularity=self.bucket_granularity,
        #                 bucket_start=b,
        #                 count_in_bucket=cnt,
        #             )
        #         )
        #     dao.batch_upsert_key_time_bucket(trows)

        self.summary.clear()
        self.time_bucket.clear()
        self._line_acc = 0
