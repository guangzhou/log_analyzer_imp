#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第三遍 P3: 自动补齐 MODULE 与 SUBMODULE 的 description 字段

设计目标
- 读取数据库中 description 为空的模块与子模块
- 调用大模型, 基于名称自动生成简短中文描述
- 支持 dry-run, 方便先预览再落库
- 尽量复用现有的 secrets.yaml 配置, 与一二遍保持一致的模型接入方式

使用示例
python -m bin.p3_fill_descriptions \\
    --secrets configs/secrets.yaml \\
    --limit-mods 50 \\
    --limit-smods 100

"""

import argparse
import os
from typing import List, Tuple

from openai import OpenAI

from core.utils.config import load_yaml
from store import dao_desc


def _load_llm_from_secrets(secrets_path: str = "configs/secrets.yaml") -> tuple[OpenAI, str]:
    """从 secrets.yaml 与环境变量中加载 LLM 配置.

    优先级
    1) secrets.qwen.api_key / base_url / model_name / timeout_s
    2) 环境变量 LLM_API_KEY / LLM_API_BASE / LLM_MODEL / LLM_TIMEOUT_S
    """
    cfg = load_yaml(secrets_path) or {}
    secrets = cfg.get("secrets", {}) if isinstance(cfg, dict) else {}
    qwen = secrets.get("qwen", {})
    api_key = qwen.get("api_key") or os.environ.get("LLM_API_KEY")
    base_url = qwen.get("base_url") or os.environ.get("LLM_API_BASE") or None
    model_name = qwen.get("model_name") or os.environ.get("LLM_MODEL") or "qwen-max-latest"
    timeout_s = qwen.get("timeout_s") or int(os.environ.get("LLM_TIMEOUT_S", "600"))

    if not api_key:
        raise RuntimeError(
            "未找到 LLM API Key, 请在 configs/secrets.yaml 的 qwen.api_key 或环境变量 LLM_API_KEY 中配置"
        )

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_s)
    return client, model_name


def _describe_module(client: OpenAI, model: str, mod: str, examples: List[str] | None = None) -> str:
    """让大模型为单个模块生成描述."""
    system_prompt = (
        "你是一个自动驾驶系统日志模块命名解析助手, "
        "负责根据模块名生成简短清晰的中文说明。"
    )
    user_content = (
        f"请用简短中文说明这个模块的含义, 控制在 20 个汉字以内, "
        f"不要带引号或多余前后缀。模块名: {mod}"
    )
    if examples:
        user_content += "\n可参考的示例日志关键内容如下(如无可忽略):\n"
        user_content += "\n".join(examples[:5])

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        max_tokens=64,
    )
    text = resp.choices[0].message.content or ""
    return text.strip().replace("\n", " ")


def _describe_submodule(client: OpenAI, model: str, smod: str, mod: str, examples: List[str] | None = None) -> str:
    """让大模型为单个子模块生成描述."""
    system_prompt = (
        "你是一个自动驾驶系统日志模块命名解析助手, "
        "负责根据模块名与子模块名生成简短清晰的中文说明。"
    )
    user_content = (
        "请用简短中文说明这个子模块的含义, 控制在 20 个汉字以内, "
        "不要带引号或多余前后缀。"
        f"模块名: {mod} 子模块名: {smod}"
    )
    if examples:
        user_content += "\n可参考的示例日志关键内容如下(如无可忽略):\n"
        user_content += "\n".join(examples[:5])

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        max_tokens=64,
    )
    text = resp.choices[0].message.content or ""
    return text.strip().replace("\n", " ")


def main():
    ap = argparse.ArgumentParser(description="第三遍: 自动补齐 module / submodule 的 description 字段")
    ap.add_argument(
        "--secrets",
        default="configs/secrets.yaml",
        help="LLM 密钥配置文件路径, 默认为 configs/secrets.yaml",
    )
    ap.add_argument(
        "--limit-mods",
        type=int,
        default=50,
        help="本次最多处理的模块数量, 默认 50",
    )
    ap.add_argument(
        "--limit-smods",
        type=int,
        default=100,
        help="本次最多处理的子模块数量, 默认 100",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印建议描述, 不写入数据库",
    )
    args = ap.parse_args()

    client, model_name = _load_llm_from_secrets(args.secrets)

    # 1. 处理模块
    mods = dao_desc.list_modules_without_desc(limit=args.limit_mods)
    if mods:
        print(f"[P3] 发现 {len(mods)} 个 description 为空的模块")
        for m in mods:
            try:
                desc = _describe_module(client, model_name, m)
            except Exception as e:  # noqa: BLE001
                print(f"[P3][模块] 生成描述失败 mod={m} err={e}")
                continue
            print(f"[P3][模块] {m} -> {desc}")
            if not args.dry_run and desc:
                dao_desc.update_module_description(m, desc)
    else:
        print("[P3] 未发现需要补全描述的模块")

    # 2. 处理子模块
    smods: List[Tuple[str, str]] = dao_desc.list_submodules_without_desc(limit=args.limit_smods)
    if smods:
        print(f"[P3] 发现 {len(smods)} 个 description 为空的子模块")
        for s, m in smods:
            try:
                desc = _describe_submodule(client, model_name, s, m)
            except Exception as e:  # noqa: BLE001
                print(f"[P3][子模块] 生成描述失败 smod={s} mod={m} err={e}")
                continue
            print(f"[P3][子模块] {s} ({m}) -> {desc}")
            if not args.dry_run and desc:
                dao_desc.update_submodule_description(s, desc)
    else:
        print("[P3] 未发现需要补全描述的子模块")

    print("[P3] 处理完成")


if __name__ == "__main__":
    main()
