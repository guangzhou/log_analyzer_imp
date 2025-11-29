
# -*- coding: utf-8 -*-
import json
from tests.fakes import FakeLLM
from core import committee, templates

def test_graph_end_to_end_with_fake(monkeypatch, cluster_samples_vx, adversary_negatives):
    """微闭环：聚类省略，草拟返回两个候选，对抗与回归通过，仲裁保留泛化版本，并触发写库。"""

    fake_out = json.dumps([
        {"semantic_info":"VX 图生成失败",
         "pattern":"Auto gen vx graph\(.+\) failed",
         "sample_log":"Auto gen vx graph(DAADBevDetTemporal6v) failed"},
        {"semantic_info":"过拟合版本",
         "pattern":"Auto gen vx graph\(DAADBevDetTemporal6v\) failed",
         "sample_log":"Auto gen vx graph(DAADBevDetTemporal6v) failed"}
    ])
    fake = FakeLLM({"default": fake_out})
    monkeypatch.setattr(committee, "_mk_lc_chat_model", lambda *a, **k: fake)

    written = {}
    def fake_write(cands):
        written["cands"] = cands
        return [1]
    monkeypatch.setattr(templates, "write_candidates", fake_write)

    cfg = {
        "committee": {
            "backend": "langgraph",
            "phase": "v1点5",
            "orchestration": {"min_support": 1}
        }
    }
    secrets = {"qwen": {"api_key":"x", "base_url":"http://dummy"}}

    # 直接调用内部 langgraph 流程。如果外部 run 封装相同，也可改为 run(...)
    out = committee._run_langgraph(cluster_samples_vx, cfg, secrets)

    assert "cands" in written and len(written["cands"]) >= 1
    # 断言保留的至少有一条是“泛化版”
    assert any("\(.+\)" in c["pattern"] for c in written["cands"])
