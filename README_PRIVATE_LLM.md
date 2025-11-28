# 私有云 LLM 配置说明

你可以通过环境变量统一配置：

```bash
export LLM_API_BASE="https://dashscope.aliyuncs.com/compatible-mode/v1"
export LLM_MODEL="qwen-max-latest"
export LLM_API_KEY="sk-xxxxx"
export LLM_AUTH_SCHEME="Bearer"
export LLM_TIMEOUT_S="600"
```

也可以在 `configs/agents.yaml` 为**每个智能体**单独指定：`api_key_env`、`base_url`、`model_name`、`timeout_s`、`auth_scheme`。

系统优先取 `agents.yaml` 里为该智能体设置的值；当某项未配置时回退到对应环境变量；再不行回退默认值。

> 若你的网关是 OpenAI 兼容协议，这套配置可直接生效；如果是自定义网关，可进一步在 `core/committee.py` 的构造函数里扩展 provider 分支。
