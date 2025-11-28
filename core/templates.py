# -*- coding: utf-8 -*-
from typing import List, Dict, Any
from store import dao

def write_candidates(cands: List[Dict[str, Any]]) -> List[int]:
    if not cands:
        return []
    return dao.write_templates(cands)
