
# -*- coding: utf-8 -*-
from store import dao
from core import templates

def test_write_candidates_to_db():
    cands = [{
        "pattern": r"Auto gen vx graph\(.+\) failed",
        "sample_log": "Auto gen vx graph(DAADBevDetTemporal6v) failed",
        "semantic_info": "VX 图生成失败",
        "advise": "检查参数与资源"
    }]
    ids = templates.write_candidates(cands)
    assert isinstance(ids, list) and len(ids) == 1
    rows = dao.fetch_all_templates(active_only=False)
    assert any(r["template_id"] == ids[0] for r in rows)
