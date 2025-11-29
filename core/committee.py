# -*- coding: utf-8 -*-
from typing import List, Dict, Any, Optional
import os, json, time, re

from core.utils.config import load_yaml
from store import dao

# ------------------------------ 通用小工具 ------------------------------

def _truncate_samples_for_llm(samples, max_chars: int = 32000, max_items: int = 120):
    """将样本做去重与长度裁剪，保证传给 LLM 的输入在安全范围。
    策略：优先保留较短、多样的样本；按长度从短到长取，直到达到上限。
    """
    if not samples:
        return []
    seen = set()
    uniq = []
    for s in samples:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    uniq_sorted = sorted(uniq, key=len)
    out, total = [], 0
    for s in uniq_sorted[:max_items]:
        if total + len(s) + 1 > max_chars:
            break
        out.append(s); total += len(s) + 1
    return out


def _ensure_list_str(xs) -> List[str]:
    return [x for x in xs if isinstance(x, str) and x.strip()]


def _default_agents_cfg_path() -> str:
    return os.environ.get("LOG_ANALYZER_AGENTS_PATH", "configs/agents.yaml")


def _default_secrets_path() -> str:
    # 可在 application.yaml 的 first_pass.committee.secrets_path 覆盖
    return os.environ.get("LOG_ANALYZER_SECRETS_PATH", "configs/secrets.yaml")


def _mk_candidate(pattern: str, sample_log: str, semantic_info: str = "", advise: str = "", source: str = "委员会") -> Dict[str, Any]:
    return dict(pattern=pattern, sample_log=sample_log, semantic_info=semantic_info, advise=advise, source=source)


def _read_application_yaml() -> Dict[str, Any]:
    app = load_yaml("configs/application.yaml") or {}
    return app


def _load_secrets(app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    # 优先 application.yaml 指定路径
    sp = (((app_cfg or {}).get("first_pass") or {}).get("committee") or {}).get("secrets_path")
    sp = sp or _default_secrets_path()
    try:
        data = load_yaml(sp) or {}
        return data
    except Exception:
        return {}


def _dot_get(d: Dict[str, Any], path: str, default: Optional[Any] = None):
    cur = d or {}
    if not path:
        return default
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def _resolve_model_field(model_cfg: Dict[str, Any], field: str, secrets: Dict[str, Any], env_keys: List[str], default=None):
    """
    解析字段优先级：
    1) agents.yaml 的直接值，如 model.base_url 或 model.api_key
    2) agents.yaml 的 *_ref，通过 secrets.yaml 的点路径解析
    3) 环境变量回退，供本地临时调试
    4) 默认值
    """
    # 1) 直接写在 agents.yaml 里
    if field in model_cfg and model_cfg[field]:
        return model_cfg[field]
    # 2) *_ref -> 从 secrets.yaml 解析
    ref_name = f"{field}_ref"
    if ref_name in model_cfg and model_cfg[ref_name]:
        ref_value = _dot_get(secrets, model_cfg[ref_name])
        if ref_value:
            return ref_value
    # 3) 环境变量回退
    for k in env_keys:
        v = os.environ.get(k)
        if v:
            return v
    # 4) 默认
    return default


def _build_langchain_llm(model_cfg: Dict[str, Any], secrets: Dict[str, Any]):
    # 支持私有云 OpenAI 兼容网关；读取顺序：agents.yaml -> secrets.yaml -> env -> 默认
    prov = (model_cfg or {}).get("provider", "").lower()
    if prov == "openai":
        from langchain_openai import ChatOpenAI

        # 读取 api_key/base_url/model_name/timeout/auth_scheme
        api_key = _resolve_model_field(
            model_cfg, "api_key", secrets,
            env_keys=["OPENAI_API_KEY","LLM_API_KEY"], default=None
        )
        base_url = _resolve_model_field(
            model_cfg, "base_url", secrets,
            env_keys=["OPENAI_BASE_URL","OPENAI_API_BASE","LLM_API_BASE"], default=None
        )
        model_name = _resolve_model_field(
            model_cfg, "model_name", secrets,
            env_keys=["LLM_MODEL"], default="gpt-4o-mini"
        )
        timeout_s = _resolve_model_field(
            model_cfg, "timeout_s", secrets,
            env_keys=["LLM_TIMEOUT_S"], default=600
        )
        try:
            timeout_s = int(timeout_s)
        except Exception:
            timeout_s = 600

        auth_scheme = _resolve_model_field(
            model_cfg, "auth_scheme", secrets,
            env_keys=["LLM_AUTH_SCHEME"], default="Bearer"
        )

        temperature = model_cfg.get("temperature", 0.0)

        default_headers = None
        if auth_scheme and auth_scheme.lower() != "bearer":
            # 非 Bearer 场景强制设置 Authorization 头
            if api_key:
                default_headers = {"Authorization": f"{auth_scheme} {api_key}"}
        # 若是标准 Bearer，可以走 ChatOpenAI 内置 api_key 处理；否则交给 default_headers
        kwargs = dict(model=model_name, temperature=temperature, base_url=base_url, timeout=timeout_s)
        if auth_scheme and auth_scheme.lower() == "bearer":
            kwargs["api_key"] = api_key
        else:
            kwargs["default_headers"] = default_headers

        return ChatOpenAI(**kwargs)

    raise RuntimeError(f"不支持的 provider: {prov}")


# ------------------------------ 带“会话内容”记录的 LLM 代理 ------------------------------

def _trace_prep(orchestration_cfg: Dict[str, Any], run_context: Optional[Dict[str, Any]]):
    """根据配置决定是否开启对话记录，返回 (enabled, writer)。"""
    orch = orchestration_cfg or {}
    enabled = bool(orch.get("trace_conversations", False))
    trace_dir = orch.get("trace_dir", "data/agent_traces")
    if not enabled:
        return False, (lambda *a, **k: None), None
    ts = time.strftime("%Y%m%d_%H%M%S")
    file_id = (run_context or {}).get("file_id", "nofile")
    run_id = (run_context or {}).get("run_id", "norun")
    base = os.path.join(trace_dir, f"{ts}_{file_id}_{run_id}")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, "trace.jsonl")

    def _write(event: str, payload: Dict[str, Any]):
        rec = {
            "ts": time.time(),
            "event": event,
            "run_context": {"file_id": file_id, "run_id": run_id},
            **payload
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    return True, _write, path


def _lc_cluster(llm, samples: List[str], trace=None) -> List[List[str]]:
    """聚类节点，可选记录 prompt 与输出"""
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是日志聚类助手。将输入的关键日志样本按语义分成若干簇，每簇保留若干代表样本。仅返回 JSON 数组，每个元素是该簇的代表样本数组。"),
        ("user", "{samples}")
    ])
    if trace:
        # 记录格式化后的消息
        msgs = prompt.format_messages(samples="\n".join(samples))
        trace("cluster.prompt", {"messages": [dict(type=m.type, content=m.content) for m in msgs]})
    chain = prompt | llm | JsonOutputParser()
    clusters = chain.invoke({"samples": "\n".join(samples)})
    clusters = [ [x for x in c if isinstance(x, str) and x.strip()] for c in clusters if isinstance(c, list) ]
    if trace:
        trace("cluster.output", {"clusters": clusters})
    return clusters


def _lc_draft(llm, cluster_samples: List[str], trace=None) -> List[Dict[str, Any]]:
    """草拟正则：
    - 输入一簇样本，期望输出“多个”候选规则
    - 返回值是 JSON 数组，每个元素包含至少: pattern, sample_log, semantic_info；可选 advise、category
    - 为避免 LangChain 变量占位符冲突，提示中的花括号作为字面量出现时使用双花括号转义
    """
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser

    system_text = (
        "你是一个自动驾驶系统问题分析专家，对报错日志进行分类与规则抽取。"
        "请分析多条样本日志，并输出 JSON 数组。数组中每个元素必须包含字段："
        "pattern, sample_log, semantic_info；可选字段：advise, category。"
        "要求：pattern 为尽量简洁且泛化的正则；sample_log 选用代表性样本；"
        "semantic_info 用一句话概括问题；advise 仅对错误类可给出处理建议。"
        "注意：只输出 JSON 数组本体，不要多余文字。"
    )
    # 使用双花括号展示示例（避免被当作模板变量）
    example_text = (
        "示例输入：\n"
        "Auto gen vx graph(DAADBevDetTemporal6v) failed\n"
        "Auto gen vx graph(DAADBevDetTemporal5v) failed\n"
        "示例输出：\n"
        '[{{"semantic_info":"VX 图生成失败","advise":"检查图生成流程中的参数配置与系统资源","pattern":"Auto gen vx graph(.*) failed.","sample_log":"Auto gen vx graph(DAADBevDetTemporal6v) failed."}}]'
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_text + "\n" + example_text),
        ("user", "{samples}")
    ])

    if trace:
        msgs = prompt.format_messages(samples="\n".join(cluster_samples))
        trace("draft.prompt", {"messages": [dict(type=m.type, content=m.content) for m in msgs]})

    chain = prompt | llm | JsonOutputParser()
    out = chain.invoke({"samples": "\n".join(cluster_samples)})

    # 兼容：如果模型误返回 dict，转为 list
    if isinstance(out, dict):
        out = [out]
    results = []
    for item in out:
        if not isinstance(item, dict):
            continue
        result = dict(
            pattern=item.get("pattern",""),
            sample_log=item.get("sample_log", cluster_samples[0] if cluster_samples else ""),
            semantic_info=item.get("semantic_info",""),
            advise=item.get("advise",""),
        )
        # category 可忽略入库，但将其原样保留在回显轨迹里
        if "category" in item:
            result["category"] = item.get("category")
        results.append(result)

    if trace:
        trace("draft.output", {"results": results})
    return results


def _lc_adversary(pattern: str, historical_negatives: List[str], trace=None) -> bool:
    cre = re.compile(pattern) if pattern else None
    if not cre:
        if trace: trace("adversary.compile_error", {"pattern": pattern})
        return False
    hits = sum(1 for s in historical_negatives if cre.search(s))
    ok = (hits == 0)
    if trace:
        trace("adversary.result", {"pattern": pattern, "neg_checked": len(historical_negatives), "hits": hits, "ok": ok})
    return ok


def _lc_regression(pattern: str, history_matched: List[str], trace=None) -> bool:
    cre = re.compile(pattern) if pattern else None
    if not cre:
        if trace: trace("regression.compile_error", {"pattern": pattern})
        return False
    if not history_matched:
        if trace: trace("regression.result", {"pattern": pattern, "checked": 0, "ok": True})
        return True
    ok = sum(1 for s in history_matched if cre.search(s))
    passed = ok >= max(1, int(len(history_matched) * 0.6))
    if trace:
        trace("regression.result", {"pattern": pattern, "checked": len(history_matched), "ok_count": ok, "passed": passed})
    return passed


def _lc_arbitrate(drafts: List[Dict[str, Any]], trace=None) -> List[Dict[str, Any]]:
    if trace:
        trace("arbiter.result", {"kept": drafts})
    return drafts


def _build_llms_for_agents(agents_cfg: Dict[str, Any], secrets: Dict[str, Any]):
    # 每个智能体允许不同模型
    return {
        "clusterer": _build_langchain_llm(agents_cfg.get("clusterer", {}).get("model", {}), secrets),
        "drafter": _build_langchain_llm(agents_cfg.get("drafter", {}).get("model", {}), secrets),
        "adversary": _build_langchain_llm(agents_cfg.get("adversary", {}).get("model", {}), secrets),
        "regressor": _build_langchain_llm(agents_cfg.get("regressor", {}).get("model", {}), secrets),
        "arbiter": _build_langchain_llm(agents_cfg.get("arbiter", {}).get("model", {}), secrets),
    }


def _run_langchain(samples: List[str], cfg: Dict[str, Any], secrets: Dict[str, Any], run_context: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    samples = _ensure_list_str(samples)
    if not samples:
        return []
    orch = cfg.get("orchestration", {})
    max_templates = orch.get("max_templates", 20)
    max_chars = orch.get("max_chars_per_call", 32000)
    max_items = orch.get("max_items_per_call", 120)
    samples = _truncate_samples_for_llm(samples, max_chars=max_chars, max_items=max_items)

    trace_enabled, trace_write, trace_path = _trace_prep(orch, run_context)
    if trace_enabled:
        trace_write("init", {"samples_cnt": len(samples), "max_templates": max_templates})

    agents = cfg.get("agents", {})
    llms = _build_llms_for_agents(agents, secrets)

    # 1) 聚类
    clusters = _lc_cluster(llms["clusterer"], samples, trace=trace_write if trace_enabled else None)

    # 2) 草拟（可能返回多个候选/每簇）
    drafts: List[Dict[str, Any]] = []
    for c in clusters[:max_templates]:
        d_list = _lc_draft(llms["drafter"], c, trace=trace_write if trace_enabled else None)
        # 兼容老逻辑：若返回单 dict 则包装为 list
        if isinstance(d_list, dict):
            d_list = [d_list]
        for d in d_list:
            if isinstance(d, dict) and d.get("pattern"):
                drafts.append(d)

    # 3) 历史负样本与已有样本集
    negatives = dao.get_recent_unmatched(limit=orch.get("adversary_unmatched_limit", 100))
    matched_hist = dao.get_template_samples(limit=100)
    if trace_enabled:
        trace_write("hist.loaded", {"negatives": len(negatives), "matched_hist": len(matched_hist)})

    # 4) 对抗与回归
    passed = []
    for d in drafts:
        pat = d.get("pattern")
        if not pat:
            continue
        ok_adv = _lc_adversary(pat, negatives, trace=trace_write if trace_enabled else None)
        if not ok_adv:
            continue
        ok_reg = _lc_regression(pat, matched_hist, trace=trace_write if trace_enabled else None)
        if not ok_reg:
            continue
        passed.append(d)

    # 5) 仲裁输出最终候选
    finals = _lc_arbitrate(passed, trace=trace_write if trace_enabled else None)
    if trace_enabled:
        trace_write("final", {"kept": finals})
    # 入库时仅关心必要字段，多余字段不影响
    return [ _mk_candidate(x.get("pattern",""), x.get("sample_log",""), x.get("semantic_info",""), x.get("advise",""), "langchain") for x in finals ]


def _run_langgraph(samples: List[str], cfg: Dict[str, Any], secrets: Dict[str, Any], run_context: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """为保持简单与一致性，这里直接复用上面的逻辑（不是用图编辑器），从而也能完整记录“会话内容”。"""
    return _run_langchain(samples, cfg, secrets, run_context)


def _run_stub(samples: List[str], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 退化模式：基于样本做启发式规则
    outs = []
    for s in samples[:10]:
        text = s
        pattern = re.sub(r"\b\d+\b", r"\\d+", re.escape(text))
        pattern = pattern.replace(r"\/", r"\/")
        pattern = pattern.replace(r"\<NUM\>", r".+").replace(r"\<PATH\>", r".+").replace(r"\<PATH_CPP\>", r".+")
        pattern = pattern.replace(r"\.\.\.", r".*")
        outs.append(_mk_candidate(pattern, text, "自动生成 分类未知 建议人工复核", "" , "stub"))
    return outs


def run(samples: List[str], model: str = "stub", phase: str = "v1点0", config_path: str = None, run_context: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """
    增强点：
    - 读取 agents.yaml 中的 committee.orchestration.trace_conversations 开关；若开启，记录对话到 data/agent_traces 下
    - 每个智能体可用不同模型
    - 安全裁剪样本长度，避免 400 错误
    - 草拟阶段改为“一簇多候选”输出，兼容老逻辑
    """
    app_cfg = _read_application_yaml()
    secrets = _load_secrets(app_cfg)
    cfg_path = config_path or os.environ.get("LOG_ANALYZER_AGENTS_PATH") or (((app_cfg.get("first_pass") or {}).get("committee") or {}).get("config_path")) or "configs/agents.yaml"
    all_cfg = load_yaml(cfg_path) or {}
    cfg = all_cfg.get("committee", all_cfg)  # 兼容直接放根上的写法
    backend = (cfg.get("backend") or model or "stub").lower()
    if backend == "langgraph":
        return _run_langgraph(samples, cfg, secrets, run_context)
    elif backend == "langchain":
        return _run_langchain(samples, cfg, secrets, run_context)
    else:
        return _run_stub(samples, cfg)
