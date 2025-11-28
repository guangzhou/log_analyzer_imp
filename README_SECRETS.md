# 私有云 LLM 密钥配置改造说明

本补丁将所有 LLM 的密钥与网关地址改为**从配置文件读取**，避免使用环境变量传递密钥。

## 目录变更

- `core/committee.py`：支持 `secrets.yaml`，新增字段解析逻辑：`api_key_ref`、`base_url_ref`
- `configs/agents.yaml`：示例里全部改为 `api_key_ref`、`base_url_ref`
- `configs/secrets.example.yaml`：密钥模板文件，请复制为 `configs/secrets.yaml` 并填写真实值
- `configs/application.yaml`：新增 `first_pass.committee.secrets_path` 指向密钥文件路径

## 使用方法

1. 复制密钥模板为实际文件：

```bash
cp configs/secrets.example.yaml configs/secrets.yaml
# 按需填写 qwen 或 openai 的 api_key 与 base_url
```

2. 确保 `configs/application.yaml` 指向该文件：

```yaml
first_pass:
  committee:
    secrets_path: "configs/secrets.yaml"
```

3. 在 `configs/agents.yaml` 中为每个智能体指定：

```yaml
api_key_ref: "secrets.qwen.api_key"
base_url_ref: "secrets.qwen.base_url"
```

> 优先级：agents.yaml 直接值 > agents.yaml 的 *_ref 从 secrets.yaml 解析 > 环境变量回退 > 默认值

## 安全建议

- `configs/secrets.yaml` 不要进版本库，请添加到 `.gitignore`
- 本补丁不会在日志中打印密钥内容
