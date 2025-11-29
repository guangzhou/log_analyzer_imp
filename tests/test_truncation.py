
# -*- coding: utf-8 -*-
from core.committee import _truncate_samples_for_llm

def test_truncate_samples_len_and_items():
    samples = ["x"*1000]*100 + ["short"]*10
    out = _truncate_samples_for_llm(samples, max_chars=5000, max_items=20)
    assert len(out) <= 20
    assert sum(len(s)+1 for s in out) <= 5000
    # 应优先保留短文本
    assert out[0] == "short"
