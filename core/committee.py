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
        # ========= 新增：透传自定义 body 参数（比如 GLM-4.6 的 thinking） =========
        # 通用入口：agents.yaml 里可以写 model.model_kwargs / model.thinking / model.disable_thinking
        model_kwargs: Dict[str, Any] = dict(model_cfg.get("model_kwargs") or {})

        # 允许直接在 agents.yaml 里写：
        # thinking:
        #   type: disabled
        if "thinking" in model_cfg and "thinking" not in model_kwargs:
            model_kwargs["thinking"] = model_cfg["thinking"]

         
            

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
    # msg 可能是 AIMessage，也可能是 str，简单兼容一下
    from langchain_core.messages import AIMessage
    if isinstance(msg, AIMessage):
        text = msg.content
    else:
        text = msg

    # content 可能是 str 或 list[dict/...]
    if isinstance(text, list):
        parts = []
        for p in text:
            if isinstance(p, dict) and "text" in p:
                parts.append(p["text"])
            else:
                parts.append(str(p))
        text = "".join(parts)
    else:
        text = str(text)

    # 去掉前缀的 <think> ... </think>
    clean = re.sub(r"^<think>[\s\S]*?</think>\s*", "", text).strip()
    return json.loads(clean)

def _parse_json_after_think(msg: Any):
    """
    兼容 GLM 带 <think> 标签 或 其他前缀噪音的 JSON 解析器：
    - msg 可能是 str，也可能是 LangChain 的 AIMessage / content-chunks list
    - 会自动剥离 <think>...</think> 和前缀噪音，从第一个 '[' 或 '{' 开始做 json.loads
    """
    try:
        # 1. 先把各种类型都归一成纯字符串
        try:
            from langchain_core.messages import BaseMessage
        except Exception:
            BaseMessage = object  # 如果没有这玩意，就当普通 object

        if isinstance(msg, BaseMessage):
            content = msg.content
        else:
            content = msg

        # content 可能是 str 或 list[dict/...]
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict):
                    # 兼容 OpenAI / 新 SDK 的几种格式
                    if "text" in p:
                        v = p["text"]
                        if isinstance(v, dict) and "value" in v:
                            parts.append(str(v["value"]))
                        else:
                            parts.append(str(v))
                    elif "content" in p:
                        parts.append(str(p["content"]))
                    else:
                        parts.append(str(p))
                else:
                    parts.append(str(p))
            text = "".join(parts)
        else:
            text = str(content)

        # 2. 去掉 BOM 和前导空白
        text = text.lstrip("\ufeff \t\r\n")

        # 3. 如果有 <think>...</think>，把它以及之前的内容全部干掉
        if "<think>" in text and "</think>" in text:
            end = text.find("</think>")
            if end != -1:
                text = text[end + len("</think>") :]

        # 4. 再去掉前导空白
        text = text.lstrip()

        # 5. 从第一个 '[' 或 '{' 开始截断
        first = len(text)
        for ch in "[{":
            idx = text.find(ch)
            if idx != -1 and idx < first:
                first = idx

        if first == len(text):
            # 找不到 JSON 起始符，直接报清楚一点的错
            raise ValueError(f"No JSON array/object start found in: {text[:80]!r}")

        text = text[first:]

        # debug 的时候可以顺手 print 一下看看
        # print("CLEAN TEXT:", repr(text))

        # 6. 正常 json 解析
        return json.loads(text)

    except Exception as e:
        # 解析失败时返回空值，而不是抛出异常
        print(f"Warning: Failed to parse JSON after think: {e}")
        return []
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
        print(111)
        # 记录格式化后的消息
        # msgs = prompt.format_messages(samples="\n".join(samples))
        # trace("cluster.prompt", {"messages": [dict(type=m.type, content=m.content) for m in msgs]})
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
    from langchain_core.runnables import RunnableLambda

    system_text = (
        "你是一个自动驾驶系统问题分析专家，对报错/日志进行语义归类和正则抽取。\n"
        "你会收到一个 JSON 数组，数组中的每个元素是一条完整的日志字符串（可能很长）。\n"
        "你的任务是：根据这些日志，生成若干条【泛化良好】的正则表达式，并用 JSON 数组返回结果。\n"
        "\n"
        "输出格式（严格 JSON 数组）：\n"
        "- 返回一个 JSON 数组，每个元素是一个对象，必须包含字段：pattern, sample_log, semantic_info；可选字段：advise\n"
        "  - pattern：针对一类日志的正则表达式，尽量简洁、可泛化，不要过拟合单条样本。\n"
        "  - sample_log：从输入样本中挑选一条最能代表该 pattern 的日志原文。\n"
        "  - semantic_info：用一句话概括这一类日志的含义（中文）。\n"
        "  - advise：仅对明显“错误/异常类”日志给出简短处理建议；其他情况可以是空字符串。\n"
        "\n"
        "重要约束：\n"
        "1. 请先在心里按“语义相近”对日志样本进行分组，然后为每一组生成 1~N 条 pattern。\n"
        "2. 确保【所有输入样本】都至少能被你返回的某一条 pattern 匹配到，不能遗漏任何一条日志。\n"
        "3. pattern 的数量应当不大于样本行数，避免一行样本生成多个几乎一样的模式。\n"
        "4. 文本中出现的 'NUMNUM' 是【占位符保留标记】，在 pattern 中必须原样保留：\n"
        "   - 不要把 'NUMNUM' 改写成 '\\d+' 或其他形式；\n"
        "   - 不要对 'NUMNUM' 做额外转义或改动；\n"
        "   - 只对真正的数字或时间戳等做适度正则化（例如用 '\\d+'）。\n"
        "5. 复杂且高度重复、有明显规律的日志，请提取关键字段进行归纳，不要机械地为每一条都生成一条几乎相同的正则。\n"
        "6. 只允许输出 JSON 数组本体 不要格式化，只要压缩的json字符串：\n"
        "   - 不能输出 ```json 这样的代码块标记；\n"
        "   - 不能在 JSON 前后添加说明文字、注释或其他自然语言。\n"
        "   - 不要输出和返回思考过程\n"

    )
    # 使用双花括号展示示例（避免被当作模板变量）
    example_text = (
    '示例（仅供参考，不要死记示例里的正则）：\n'
    '示例输入 JSON 数组：\n'
    '["Auto gen vx graph(DAADBevDetTemporal6v) failed",\n'
    ' "Auto gen vx graph(DAADBevDetTemporal5v) failed",\n'
    ' "seletct_mot_id: NUMNUM NUMNUM",\n'
    ' "seletct_mot_id: NUMNUM",\n'
    ' "seletct_mot_id: NUMNUM NUMNUM NUMNUM",\n'
    ' "front side mots: [(NUMNUM, NUMNUM), ], [], [(NUMNUM, NUMNUM), (NUMNUM, NUMNUM),]",\n'
    ' "front side mots: [], [], [(NUMNUM, NUMNUM), ]",\n'
    ' "front side mots: [], [], [(NUMNUM, NUMNUM), ],[],[]"]\n'
    '\n'
    '示例输出 JSON 数组（压缩形式，注意这里是 JSON 数组本身，不是被引号包裹的字符串）：\n'
    '[{{"pattern":"^Auto gen vx graph\\\\(.*\\\\) failed$","sample_log":"Auto gen vx graph(DAADBevDetTemporal6v) failed","semantic_info":"VX 图生成失败","advise":"检查图生成流程中的参数配置与系统资源"}},'
    '{{"pattern":"^seletct_mot_id: (?:NUMNUM)(?: NUMNUM)*$","sample_log":"seletct_mot_id: NUMNUM NUMNUM","semantic_info":"模块选出的 MOT 目标 ID 列表","advise":""}},'
    '{{"pattern":"^front side mots: .*$","sample_log":"front side mots: [(NUMNUM, NUMNUM), ], [(NUMNUM, NUMNUM), ], [(NUMNUM, NUMNUM), ]","semantic_info":"车前方区域的 MOT 跟踪目标列表","advise":""}}]\n'
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_text + "\n" + example_text),
        ("user", "{samples}")
    ])

    if trace:
        msgs = prompt.format_messages(samples="\n".join(cluster_samples))
        trace("draft.prompt", {"messages": [dict(type=m.type, content=m.content) for m in msgs]})

    # chain = prompt | llm | JsonOutputParser()
    
    chain = prompt | llm | RunnableLambda(_parse_json_after_think)
      
    jsonstr=json.dumps(cluster_samples)
    out = chain.invoke({"samples":  jsonstr})

    # 检查解析结果是否为空，如果为空则跳过处理
    if not out or (isinstance(out, list) and len(out) == 0):
        if trace:
            trace("draft.empty_result", {"warning": "JSON parsing returned empty, skipping draft processing"})
        return []

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
    # clusters = _lc_cluster(llms["clusterer"], samples, trace=trace_write if trace_enabled else None)

    # # 2) 草拟（可能返回多个候选/每簇）
    # drafts: List[Dict[str, Any]] = []
    # for c in clusters[:max_templates]:
    #     d_list = _lc_draft(llms["drafter"], c, trace=trace_write if trace_enabled else None)
    #     # 兼容老逻辑：若返回单 dict 则包装为 list
    #     if isinstance(d_list, dict):
    #         d_list = [d_list]
    #     for d in d_list:
    #         if isinstance(d, dict) and d.get("pattern"):
    #             drafts.append(d)
    drafts: List[Dict[str, Any]] = []
    d_list = _lc_draft(llms["drafter"], samples, trace=trace_write if trace_enabled else None)
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
        # pat = d.get("pattern")
        # if not pat:
        #     continue
        # ok_adv = _lc_adversary(pat, negatives, trace=trace_write if trace_enabled else None)
        # if not ok_adv:
        #     continue
        # ok_reg = _lc_regression(pat, matched_hist, trace=trace_write if trace_enabled else None)
        # if not ok_reg:
        #     continue
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
