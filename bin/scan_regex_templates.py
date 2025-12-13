# bin/scan_regex_templates.py
# -*- coding: utf-8 -*-
"""
离线扫描 regex_template 表中的所有 pattern / pattern_nomal，做正则安全检测。

功能：
  1) 检测每条模板是否存在灾难性回溯风险或编译问题；
  2) 对 pattern 与 pattern_nomal 各测一次，取“更危险”的等级；
  3) 输出 summary 到控制台；
  4) 可将详细结果写入 JSON 报告；
  5) 可选：对 level = 'danger' 的模板自动软删除（调用 deactivate_template）；
  6) 可选：把所有 warning 也当 danger 禁用（推荐，彻底一点）。

用法示例：

  LOG_ANALYZER_DB=./data/log_analyzer.sqlite3 \
    python -m bin.scan_regex_templates \
      --active-only \
      --report-json ./regex_safety_report.json \
      --auto-deactivate-danger \
      --ban-warning-too
"""

import argparse
import json
from typing import List, Dict, Any

from store.dao import fetch_all_templates, deactivate_template
from core.regex_safety import analyze_regex_safety, RegexSafetyResult


_LEVEL_RANK = {"ok": 0, "warning": 1, "danger": 2}


def _pick_worse(a: RegexSafetyResult, b: RegexSafetyResult | None) -> RegexSafetyResult:
    if b is None:
        return a
    if _LEVEL_RANK[b.level] > _LEVEL_RANK[a.level]:
        return b
    return a


def scan_templates(
    active_only: bool = True,
    timeout_sec: float = 0.5,
    auto_deactivate_danger: bool = False,
    ban_warning_too: bool = False,
) -> Dict[str, Any]:
    rows = fetch_all_templates(active_only=active_only)

    results: List[Dict[str, Any]] = []
    total = len(rows)
    ok_cnt = warning_cnt = danger_cnt = 0

    for row in rows:
        template_id = row["template_id"]
        pattern = row["pattern"]
        pattern_nomal = row["pattern_nomal"]
        sample_log = row["sample_log"] or ""

        # 分别对 pattern 和 pattern_nomal 做检测，取“更危险”的那个结果
        res_pattern: RegexSafetyResult = analyze_regex_safety(
            pattern=pattern,
            sample_texts=[sample_log] if sample_log else [],
            timeout_sec=timeout_sec,
        )

        res_nomal: RegexSafetyResult | None = None
        if pattern_nomal:
            res_nomal = analyze_regex_safety(
                pattern=pattern_nomal,
                sample_texts=[sample_log] if sample_log else [],
                timeout_sec=timeout_sec,
            )

        best = _pick_worse(res_pattern, res_nomal)

        if best.level == "ok":
            ok_cnt += 1
        elif best.level == "warning":
            warning_cnt += 1
        else:
            danger_cnt += 1

        item = best.to_dict()
        item["template_id"] = template_id
        item["pattern_nomal"] = pattern_nomal
        item["sample_log_preview"] = sample_log[:200]
        results.append(item)

        # 是否禁用：danger 必禁；ban_warning_too 时，warning 也禁
        need_ban = best.level == "danger" or (ban_warning_too and best.level == "warning")
        if auto_deactivate_danger and need_ban:
            success = deactivate_template(template_id)
            item["auto_deactivated"] = bool(success)

    summary = {
        "total": total,
        "ok": ok_cnt,
        "warning": warning_cnt,
        "danger": danger_cnt,
    }
    return {"summary": summary, "details": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="regex_template 正则安全离线扫描工具")
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="仅扫描 is_active=1 的模板（默认行为）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="扫描所有模板（包括已 inactive）",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=0.5,
        help="单次动态检测 timeout 秒数，默认 0.5s（离线运行，一次性稍微慢点没关系）",
    )
    parser.add_argument(
        "--report-json",
        type=str,
        default="",
        help="将详细检测结果输出为 JSON 文件路径（可选）",
    )
    parser.add_argument(
        "--auto-deactivate-danger",
        action="store_true",
        help="对危险模板自动调用 deactivate_template 做软删除",
    )
    parser.add_argument(
        "--ban-warning-too",
        action="store_true",
        help="把所有 warning 也当成 danger，一并禁用（推荐，宁可误杀，先确保不再卡死）",
    )
    args = parser.parse_args()

    if args.all:
        active_only = False
    else:
        active_only = True  # 默认只扫 active 模板

    result = scan_templates(
        active_only=active_only,
        timeout_sec=args.timeout_sec,
        auto_deactivate_danger=args.auto_deactivate_danger,
        ban_warning_too=args.ban_warning_too,
    )

    summary = result["summary"]
    print("========================================")
    print(" 正则安全扫描结果汇总")
    print("========================================")
    print(f"总模板数              : {summary['total']}")
    print(f"✅ 安全 (ok)          : {summary['ok']}")
    print(f"⚠️  警告 (warning)    : {summary['warning']}")
    print(f"❌ 危险 (danger)      : {summary['danger']}")
    print("========================================")

    if args.report_json:
        with open(args.report_json, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[OK] 报告已写入: {args.report_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
