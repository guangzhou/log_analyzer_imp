# -*- coding: utf-8 -*-
import threading
from store import dao
from .matcher import CompiledIndex

class Indexer:
    def __init__(self):
        self._lock = threading.RLock()
        self._active = None  # type: ignore

    def load_initial(self):
        items = [{"template_id": r["template_id"], "pattern": r["pattern"]} for r in dao.fetch_all_templates(True)]
        with self._lock:
            self._active = CompiledIndex(items)

    def get_active(self) -> CompiledIndex:
        with self._lock:
            return self._active

    def build_new_index_async(self):
        def _worker():
            items = [{"template_id": r["template_id"], "pattern": r["pattern"]} for r in dao.fetch_all_templates(True)]
            new_idx = CompiledIndex(items)
            self.atomic_switch(new_idx)
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def atomic_switch(self, new_handle: CompiledIndex):
        with self._lock:
            self._active = new_handle
