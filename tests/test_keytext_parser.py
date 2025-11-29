
# -*- coding: utf-8 -*-
from core.keytext import extract_key_text

def test_extract_key_text_basic():
    raw = "[20250929_183904][3499.966][I][40433][MOD:vgnss][SMOD:log][ INFO ] [RTK] sensor:3500813, age=1.00, ns_r=32, ns_b=39"
    kt = extract_key_text(raw)
    assert "sensor:3500813, age=1.00, ns_r=32, ns_b=39" in kt
