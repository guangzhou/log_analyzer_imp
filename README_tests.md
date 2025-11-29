
# 多智能体单元测试套件

## 运行方式
```bash
# 在项目根目录执行
pytest -q
```

## 内容一览
- `tests/fakes.py`：假模型 FakeLLM，无需真实 API，确保测试可重复。
- `tests/conftest.py`：临时 sqlite 数据库初始化与样本夹具。
- `tests/test_drafter.py`：验证草拟员返回“多规则 JSON 数组”契约与正则可编译。
- `tests/test_truncation.py`：输入裁剪函数的边界与优先级策略。
- `tests/test_graph_closed_loop.py`：微闭环：草拟 → 对抗 → 回归 → 仲裁，校验写库被触发。
- `tests/test_keytext_parser.py`：关键文本抽取与规范化的正确性。
- `tests/test_templates_db.py`：候选模板写库与读取的完整性。

## 说明
- 测试默认使用 `FakeLLM`，不会访问外部网络。
- 数据库采用临时 sqlite 文件，测试结束后自动清理。
- 如需跑真实模型回归测试，可将 `committee._mk_lc_chat_model` 的 monkeypatch 注释掉，
  并在环境中配置好 `agents.yaml` 与 secrets。
