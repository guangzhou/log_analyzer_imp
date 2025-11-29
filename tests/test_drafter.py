
# -*- coding: utf-8 -*-
import json, re
import pytest
from tests.fakes import FakeLLM

# 从项目中引入 committee 内部草拟函数
from core import committee

def test_drafter_multi_rules_contract(monkeypatch, cluster_samples_vx):
    """验证：草拟员根据多条样本返回 JSON 数组，且字段齐全且可编译。"""
    fake_out = json.dumps([
        {"semantic_info":"VX 图生成失败",
         "pattern":"Auto gen vx graph\(.+\) failed",
         "sample_log":"Auto gen vx graph(DAADBevDetTemporal6v) failed",
         "advise":"检查参数配置与系统资源"},
        {"semantic_info":"VX 图生成失败",
         "pattern":"Auto gen vx graph\(.*Temporal[0-9]v\) failed",
         "sample_log":"Auto gen vx graph(DAADBevDetTemporal5v) failed"}
    ])
    fake = FakeLLM({"default": fake_out})
    # 将内部创建 LLM 的工厂替换成假模型
    monkeypatch.setattr(committee, "_mk_lc_chat_model", lambda *a, **k: fake)

    # 调用新版草拟函数：应返回 list[dict]
    out = committee._lc_draft(fake, cluster_samples_vx, trace=None)
    assert isinstance(out, list) and len(out) >= 1
    for r in out:
        assert set(["pattern","sample_log","semantic_info"]).issubset(r)
        re.compile(r["pattern"])
