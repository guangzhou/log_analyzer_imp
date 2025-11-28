# -*- coding: utf-8 -*-
from typing import List, Dict, Any, Optional
import os
from core.utils.config import load_yaml
from store import dao

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

def _lc_cluster(llm, samples: List[str]) -> List[List[str]]:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是日志聚类助手。将输入的关键日志样本按语义分成若干簇，每簇保留若干代表样本。仅返回 JSON 数组，每个元素是该簇的代表样本数组。"),
        ("user", "{samples}")
    ])
    chain = prompt | llm | JsonOutputParser()
    clusters = chain.invoke({"samples": "\n".join(samples)})
    return [ _ensure_list_str(c) for c in clusters if isinstance(c, list) ]

def _lc_draft(llm, cluster_samples: List[str]) -> Dict[str, Any]:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import JsonOutputParser
    # 提示词转为内部模板字段: pattern, sample_log, semantic_info, advise
    prompt = ChatPromptTemplate.from_messages([
        ("system", "你是自动驾驶日志正则草拟助手。基于下方样本生成一个尽量简洁且泛化的正则。务必以 JSON 返回，键为 pattern, sample_log, semantic_info, advise。"),
        ("user", "{samples}")
    ])
    chain = prompt | llm | JsonOutputParser()
    out = chain.invoke({"samples": "\n".join(cluster_samples)})
    return dict(
        pattern=out.get("pattern",""),
        sample_log=out.get("sample_log", cluster_samples[0] if cluster_samples else ""),
        semantic_info=out.get("semantic_info",""),
        advise=out.get("advise","")
    )

def _lc_adversary(llm, pattern: str, historical_negatives: List[str]) -> bool:
    import re
    cre = re.compile(pattern) if pattern else None
    if not cre:
        return False
    hits = sum(1 for s in historical_negatives if cre.search(s))
    return hits == 0

def _lc_regression(llm, pattern: str, history_matched: List[str]) -> bool:
    import re
    cre = re.compile(pattern) if pattern else None
    if not cre:
        return False
    if not history_matched:
        return True
    ok = sum(1 for s in history_matched if cre.search(s))
    return ok >= max(1, int(len(history_matched) * 0.6))

def _lc_arbitrate(llm, drafts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # MVP: 直接放行，通过后续索引与第二遍再优化
    return drafts

def _run_langchain(samples: List[str], cfg: Dict[str, Any], secrets: Dict[str, Any]) -> List[Dict[str, Any]]:
    samples = _ensure_list_str(samples)
    if not samples:
        return []
    agents = cfg.get("agents", {})
    orch = cfg.get("orchestration", {})
    max_templates = orch.get("max_templates", 10)

    llm_clusterer = _build_langchain_llm(agents.get("clusterer", {}).get("model", {}), secrets)
    llm_drafter = _build_langchain_llm(agents.get("drafter", {}).get("model", {}), secrets)
    llm_adversary = _build_langchain_llm(agents.get("adversary", {}).get("model", {}), secrets)
    llm_regressor = _build_langchain_llm(agents.get("regressor", {}).get("model", {}), secrets)
    llm_arbiter = _build_langchain_llm(agents.get("arbiter", {}).get("model", {}), secrets)

    clusters = _lc_cluster(llm_clusterer, samples)
    drafts = []
    for c in clusters[:max_templates]:
        d = _lc_draft(llm_drafter, c)
        drafts.append(d)

    negatives = dao.get_recent_unmatched(limit=orch.get("adversary_unmatched_limit", 100))
    matched_hist = dao.get_template_samples(limit=100)

    passed = []
    for d in drafts:
        if not d.get("pattern"):
            continue
        ok_adv = _lc_adversary(llm_adversary, d["pattern"], negatives)
        if not ok_adv:
            continue
        ok_reg = _lc_regression(llm_regressor, d["pattern"], matched_hist)
        if not ok_reg:
            continue
        passed.append(d)

    final = _lc_arbitrate(llm_arbiter, passed)
    return [ _mk_candidate(x["pattern"], x.get("sample_log",""), x.get("semantic_info",""), x.get("advise",""), "langchain") for x in final ]

def _run_langgraph(samples: List[str], cfg: Dict[str, Any], secrets: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        from langgraph.graph import StateGraph, END
    except Exception:
        return _run_langchain(samples, cfg, secrets)

    samples = _ensure_list_str(samples)
    if not samples:
        return []

    agents = cfg.get("agents", {})
    orch = cfg.get("orchestration", {})
    max_templates = orch.get("max_templates", 10)

    try:
        lc_llm_clusterer = _build_langchain_llm(agents.get("clusterer", {}).get("model", {}), secrets)
        lc_llm_drafter = _build_langchain_llm(agents.get("drafter", {}).get("model", {}), secrets)
        lc_llm_adversary = _build_langchain_llm(agents.get("adversary", {}).get("model", {}), secrets)
        lc_llm_regressor = _build_langchain_llm(agents.get("regressor", {}).get("model", {}), secrets)
        lc_llm_arbiter = _build_langchain_llm(agents.get("arbiter", {}).get("model", {}), secrets)
    except Exception:
        return _run_langchain(samples, cfg, secrets)

    from typing import TypedDict, List as TList, Dict as TDict, Any as TAny
    class St(TypedDict):
        samples: TList[str]
        clusters: TList[TList[str]]
        drafts: TList[TDict[str, TAny]]
        negatives: TList[str]
        matched_hist: TList[str]
        passed: TList[TDict[str, TAny]]

    def n_cluster(state: St):
        cs = _lc_cluster(lc_llm_clusterer, state["samples"])
        state["clusters"] = cs[:max_templates]
        return state

    def n_draft(state: St):
        drafts = []
        for c in state["clusters"]:
            drafts.append(_lc_draft(lc_llm_drafter, c))
        state["drafts"] = drafts
        return state

    def n_hist(state: St):
        state["negatives"] = dao.get_recent_unmatched(limit=orch.get("adversary_unmatched_limit", 100))
        state["matched_hist"] = dao.get_template_samples(limit=100)
        return state

    def n_validate(state: St):
        passed = []
        for d in state["drafts"]:
            pat = d.get("pattern","")
            if not pat:
                continue
            ok_adv = _lc_adversary(lc_llm_adversary, pat, state["negatives"])
            if not ok_adv:
                continue
            ok_reg = _lc_regression(lc_llm_regressor, pat, state["matched_hist"])
            if not ok_reg:
                continue
            passed.append(d)
        state["passed"] = passed
        return state

    def n_arb(state: St):
        finals = _lc_arbitrate(lc_llm_arbiter, state["passed"])
        state["passed"] = finals
        return state

    g = StateGraph(St)
    g.add_node("cluster", n_cluster)
    g.add_node("draft", n_draft)
    g.add_node("hist", n_hist)
    g.add_node("validate", n_validate)
    g.add_node("arb", n_arb)
    g.set_entry_point("cluster")
    g.add_edge("cluster", "draft")
    g.add_edge("draft", "hist")
    g.add_edge("hist", "validate")
    g.add_edge("validate", "arb")
    g.add_edge("arb", END)

    app = g.compile()
    init = {"samples": samples, "clusters": [], "drafts": [], "negatives": [], "matched_hist": [], "passed": []}
    out = app.invoke(init)
    finals = out["passed"]
    return [ _mk_candidate(x["pattern"], x.get("sample_log",""), x.get("semantic_info",""), x.get("advise",""), "langgraph") for x in finals ]

def _run_stub(samples: List[str], cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 离线调试占位
    outs = []
    for s in samples[: min(3, len(samples)) ]:
        outs.append(_mk_candidate(pattern=".*"+s.split(" ")[0]+".*", sample_log=s, semantic_info="", advise="", source="stub"))
    return outs

def run(samples: List[str], model: str = "stub", phase: str = "v1点0", config_path: str = None) -> List[Dict[str, Any]]:
    app_cfg = _read_application_yaml()
    secrets = _load_secrets(app_cfg)
    cfg_path = config_path or os.environ.get("LOG_ANALYZER_AGENTS_PATH") or (((app_cfg.get("first_pass") or {}).get("committee") or {}).get("config_path")) or "configs/agents.yaml"
    all_cfg = load_yaml(cfg_path) or {}
    cfg = all_cfg.get("committee", all_cfg)  # 兼容直接放根上的写法
    backend = (cfg.get("backend") or model or "stub").lower()
    if backend == "langgraph":
        return _run_langgraph(samples, cfg, secrets)
    elif backend == "langchain":
        return _run_langchain(samples, cfg, secrets)
    else:
        return _run_stub(samples, cfg)
