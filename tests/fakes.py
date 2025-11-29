
# -*- coding: utf-8 -*-
"""测试用假模型与辅助工具。"""
from langchain_core.messages import AIMessage

class FakeLLM:
    """极简假模型：根据 test_key 返回预设 JSON 文本，模拟 LLM 输出。"""
    def __init__(self, scripted_outputs: dict):
        self.scripted_outputs = scripted_outputs or {}

    def invoke(self, messages, **kwargs):
        key = kwargs.get("test_key") or "default"
        content = self.scripted_outputs.get(key, "[]")
        return AIMessage(content=content)
