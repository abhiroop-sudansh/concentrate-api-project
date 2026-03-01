"""Generate summary.json and summary.md from results.jsonl."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _avg_key(scores_list: list[dict], key: str) -> float:
    vals = [s.get(key) for s in scores_list if s.get(key) is not None]
    if not vals:
        return 0.0
    try:
        return sum(float(v) for v in vals) / len(vals)
    except (TypeError, ValueError):
        return 0.0


def load_results(path: Path) -> list[dict[str, Any]]:
    """Load results.jsonl into list of dicts."""
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def compute_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate stats: total calls, success rate, avg latency/tokens by provider, JSON compliance, top 3 slowest, top 3 highest token."""
    total = len(records)
    success_count = sum(1 for r in records if r.get("success"))
    success_rate = success_count / total if total else 0.0

    by_provider: dict[str, list[dict]] = {}
    for r in records:
        p = r.get("provider") or "unknown"
        by_provider.setdefault(p, []).append(r)

    avg_latency_by_provider: dict[str, float] = {}
    avg_tokens_by_provider: dict[str, float] = {}
    for provider, rs in by_provider.items():
        ok = [r for r in rs if r.get("success")]
        if ok:
            avg_latency_by_provider[provider] = sum(r.get("latency_ms") or 0 for r in ok) / len(ok)
            tokens = [r.get("usage_total_tokens") for r in ok if r.get("usage_total_tokens") is not None]
            avg_tokens_by_provider[provider] = sum(tokens) / len(tokens) if tokens else 0.0
        else:
            avg_latency_by_provider[provider] = 0.0
            avg_tokens_by_provider[provider] = 0.0

    json_candidates = [r for r in records if r.get("json_valid") is not None]
    json_total = len(json_candidates)
    json_valid_count = sum(1 for r in json_candidates if r.get("json_valid"))
    json_compliance_rate = json_valid_count / json_total if json_total else 0.0

    # Format repair & fallback (Milestone 3)
    def slot_key(r: dict) -> tuple:
        return (r.get("provider"), r.get("prompt_id"), r.get("temperature"))

    by_slot: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        by_slot[slot_key(r)].append(r)
    invalid_primary = 0
    repaired_valid = 0
    for slot_records in by_slot.values():
        primary_records = [r for r in slot_records if r.get("attempt_type", "primary") == "primary"]
        repair_records = [r for r in slot_records if r.get("attempt_type") == "repair"]
        if not primary_records:
            continue
        prim = primary_records[0]
        if prim.get("json_valid") is False:
            invalid_primary += 1
            if any(r.get("json_valid") for r in repair_records):
                repaired_valid += 1
    json_repair_success_rate = repaired_valid / invalid_primary if invalid_primary else 0.0

    fallback_records = [r for r in records if r.get("attempt_type") == "fallback"]
    fallback_used_count = len(fallback_records)
    fallback_success_count = sum(1 for r in fallback_records if r.get("success"))

    final_records_with_json = [r for r in records if r.get("final_for_case", True) and r.get("json_valid") is not None]
    final_json_total = len(final_records_with_json)
    final_json_valid_count = sum(1 for r in final_records_with_json if r.get("json_valid"))
    final_json_compliance_rate = final_json_valid_count / final_json_total if final_json_total else 0.0

    # Top 3 slowest (by latency_ms)
    with_latency = [(r, r.get("latency_ms") or 0) for r in records]
    with_latency.sort(key=lambda x: x[1], reverse=True)
    top3_slowest = [
        {"prompt_id": r.get("prompt_id"), "provider": r.get("provider"), "temperature": r.get("temperature"), "latency_ms": r.get("latency_ms")}
        for r, _ in with_latency[:3]
    ]

    # Top 3 highest token
    with_tokens = [(r, r.get("usage_total_tokens") or 0) for r in records]
    with_tokens.sort(key=lambda x: x[1], reverse=True)
    top3_tokens = [
        {"prompt_id": r.get("prompt_id"), "provider": r.get("provider"), "usage_total_tokens": r.get("usage_total_tokens")}
        for r, _ in with_tokens[:3]
    ]

    # Judge scores (attempt_type=judge with scores)
    judge_with_scores = [r for r in records if r.get("attempt_type") == "judge" and isinstance(r.get("scores"), dict)]
    avg_instruction_following_by_provider: dict[str, float] = {}
    avg_format_compliance_by_provider: dict[str, float] = {}
    avg_conciseness_by_provider: dict[str, float] = {}
    avg_grounding_by_provider: dict[str, float] = {}
    avg_instruction_following_by_temp: dict[float, float] = {}
    avg_format_compliance_by_temp: dict[float, float] = {}
    avg_conciseness_by_temp: dict[float, float] = {}
    avg_grounding_by_temp: dict[float, float] = {}

    for provider in set(r.get("evaluated_provider") for r in judge_with_scores if r.get("evaluated_provider")):
        subset = [r for r in judge_with_scores if r.get("evaluated_provider") == provider]
        if subset:
            scores_list = [r["scores"] for r in subset]
            avg_instruction_following_by_provider[provider] = _avg_key(scores_list, "instruction_following")
            avg_format_compliance_by_provider[provider] = _avg_key(scores_list, "format_compliance")
            avg_conciseness_by_provider[provider] = _avg_key(scores_list, "conciseness")
            avg_grounding_by_provider[provider] = _avg_key(scores_list, "grounding")
    for temp in set(r.get("evaluated_temp") for r in judge_with_scores if r.get("evaluated_temp") is not None):
        subset = [r for r in judge_with_scores if r.get("evaluated_temp") == temp]
        if subset:
            scores_list = [r["scores"] for r in subset]
            avg_instruction_following_by_temp[temp] = _avg_key(scores_list, "instruction_following")
            avg_format_compliance_by_temp[temp] = _avg_key(scores_list, "format_compliance")
            avg_conciseness_by_temp[temp] = _avg_key(scores_list, "conciseness")
            avg_grounding_by_temp[temp] = _avg_key(scores_list, "grounding")

    # Long-doc QA grounding: final_for_case records with qa_total set
    qa_grounding_records = [r for r in records if r.get("final_for_case", True) and r.get("qa_total") is not None]
    qa_supported_rate_by_provider: dict[str, float] = {}
    qa_hallucinated_rate_by_provider: dict[str, float] = {}
    qa_supported_rate_by_temp: dict[float, float] = {}
    qa_hallucinated_rate_by_temp: dict[float, float] = {}
    for provider in set(r.get("provider") for r in qa_grounding_records if r.get("provider")):
        subset = [r for r in qa_grounding_records if r.get("provider") == provider]
        if subset:
            qa_supported_rate_by_provider[provider] = sum(r.get("qa_supported_rate") or 0 for r in subset) / len(subset)
            qa_hallucinated_rate_by_provider[provider] = sum(r.get("qa_hallucinated_rate") or 0 for r in subset) / len(subset)
    for temp in set(r.get("temperature") for r in qa_grounding_records if r.get("temperature") is not None):
        subset = [r for r in qa_grounding_records if r.get("temperature") == temp]
        if subset:
            qa_supported_rate_by_temp[temp] = sum(r.get("qa_supported_rate") or 0 for r in subset) / len(subset)
            qa_hallucinated_rate_by_temp[temp] = sum(r.get("qa_hallucinated_rate") or 0 for r in subset) / len(subset)

    return {
        "total_calls": total,
        "success_count": success_count,
        "success_rate": success_rate,
        "avg_latency_ms_by_provider": avg_latency_by_provider,
        "avg_tokens_by_provider": avg_tokens_by_provider,
        "json_total": json_total,
        "json_valid_count": json_valid_count,
        "json_compliance_rate": json_compliance_rate,
        "json_repair_success_rate": json_repair_success_rate,
        "invalid_primary_count": invalid_primary,
        "repaired_valid_count": repaired_valid,
        "fallback_used_count": fallback_used_count,
        "fallback_success_count": fallback_success_count,
        "final_json_total": final_json_total,
        "final_json_valid_count": final_json_valid_count,
        "final_json_compliance_rate": final_json_compliance_rate,
        "top3_slowest": top3_slowest,
        "top3_highest_tokens": top3_tokens,
        "avg_instruction_following_by_provider": avg_instruction_following_by_provider,
        "avg_format_compliance_by_provider": avg_format_compliance_by_provider,
        "avg_conciseness_by_provider": avg_conciseness_by_provider,
        "avg_grounding_by_provider": avg_grounding_by_provider,
        "avg_instruction_following_by_temp": avg_instruction_following_by_temp,
        "avg_format_compliance_by_temp": avg_format_compliance_by_temp,
        "avg_conciseness_by_temp": avg_conciseness_by_temp,
        "avg_grounding_by_temp": avg_grounding_by_temp,
        "qa_supported_rate_by_provider": qa_supported_rate_by_provider,
        "qa_hallucinated_rate_by_provider": qa_hallucinated_rate_by_provider,
        "qa_supported_rate_by_temp": qa_supported_rate_by_temp,
        "qa_hallucinated_rate_by_temp": qa_hallucinated_rate_by_temp,
    }


def write_summary_json(summary: dict[str, Any], path: Path) -> None:
    """Write summary.json."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


def write_summary_md(summary: dict[str, Any], path: Path, run_id: str) -> None:
    """Write human-readable summary.md."""
    lines = [
        f"# Experiment summary — {run_id}",
        "",
        "## Overview",
        f"- **Total calls:** {summary.get('total_calls', 0)}",
        f"- **Success count:** {summary.get('success_count', 0)}",
        f"- **Success rate:** {summary.get('success_rate', 0):.1%}",
        "",
        "## Avg latency (ms) by provider",
    ]
    for provider, avg in summary.get("avg_latency_ms_by_provider", {}).items():
        lines.append(f"- **{provider}:** {avg:.1f}")
    lines.extend([
        "",
        "## Avg tokens by provider",
    ])
    for provider, avg in summary.get("avg_tokens_by_provider", {}).items():
        lines.append(f"- **{provider}:** {avg:.1f}")
    lines.extend([
        "",
        "## JSON compliance (json category)",
        f"- **JSON-related calls:** {summary.get('json_total', 0)}",
        f"- **Valid JSON count:** {summary.get('json_valid_count', 0)}",
        f"- **Compliance rate:** {summary.get('json_compliance_rate', 0):.1%}",
        "",
        "## Format Repair & Fallback",
        "When a prompt expects JSON and the model returns invalid JSON, the runner first re-asks the same provider (repair); if still invalid, it can call the other provider once (fallback). Fallback is also used for provider/HTTP failures (e.g. 424 Provider Error, 429, 5xx): after retries are exhausted, one attempt is made with the other provider for the same prompt.",
        f"- **Invalid primary (JSON) count:** {summary.get('invalid_primary_count', 0)}",
        f"- **Repaired to valid count:** {summary.get('repaired_valid_count', 0)}",
        f"- **JSON repair success rate:** {summary.get('json_repair_success_rate', 0):.1%}",
        f"- **Fallback used count:** {summary.get('fallback_used_count', 0)}",
        f"- **Fallback success count:** {summary.get('fallback_success_count', 0)}",
        f"- **Final JSON compliance rate** (per-slot final output): {summary.get('final_json_compliance_rate', 0):.1%}",
        "",
        "## Top 3 slowest calls",
    ])
    for s in summary.get("top3_slowest", []):
        lines.append(f"- {s.get('prompt_id')} / {s.get('provider')} / temp={s.get('temperature')} — {s.get('latency_ms')} ms")
    lines.extend([
        "",
        "## Top 3 highest token calls",
    ])
    for s in summary.get("top3_highest_tokens", []):
        lines.append(f"- {s.get('prompt_id')} / {s.get('provider')} — {s.get('usage_total_tokens')} tokens")
    lines.extend([
        "",
        "## Judge scores (when ENABLE_JUDGE=true)",
    ])
    for provider, avg in summary.get("avg_instruction_following_by_provider", {}).items():
        lines.append(f"- **{provider}** — instruction_following: {summary.get('avg_instruction_following_by_provider', {}).get(provider, 0):.2f}, format_compliance: {summary.get('avg_format_compliance_by_provider', {}).get(provider, 0):.2f}, conciseness: {summary.get('avg_conciseness_by_provider', {}).get(provider, 0):.2f}, grounding: {summary.get('avg_grounding_by_provider', {}).get(provider, 0):.2f}")
    for temp, avg in summary.get("avg_instruction_following_by_temp", {}).items():
        lines.append(f"- **temp={temp}** — instruction_following: {avg:.2f}, format_compliance: {summary.get('avg_format_compliance_by_temp', {}).get(temp, 0):.2f}, conciseness: {summary.get('avg_conciseness_by_temp', {}).get(temp, 0):.2f}, grounding: {summary.get('avg_grounding_by_temp', {}).get(temp, 0):.2f}")
    lines.extend([
        "",
        "## Long-doc QA grounding (heuristic)",
        "For prompt_id ending with _qa (long-doc QA cases): answers are classified as SUPPORTED (substring in document), UNKNOWN, or HALLUCINATED. Averages below are over final_for_case records with qa_total set.",
        "",
        "### By provider",
    ])
    for provider in summary.get("qa_supported_rate_by_provider", {}):
        sup = summary.get("qa_supported_rate_by_provider", {}).get(provider, 0)
        hall = summary.get("qa_hallucinated_rate_by_provider", {}).get(provider, 0)
        lines.append(f"- **{provider}** — supported_rate: {sup:.2%}, hallucinated_rate: {hall:.2%}")
    lines.extend([
        "",
        "### By temperature",
    ])
    for temp in summary.get("qa_supported_rate_by_temp", {}):
        sup = summary.get("qa_supported_rate_by_temp", {}).get(temp, 0)
        hall = summary.get("qa_hallucinated_rate_by_temp", {}).get(temp, 0)
        lines.append(f"- **temp={temp}** — supported_rate: {sup:.2%}, hallucinated_rate: {hall:.2%}")
    lines.append("")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def generate_reports(output_dir: Path, run_id: str) -> dict[str, Any]:
    """Load results.jsonl, compute summary, write summary.json and summary.md. Return summary dict."""
    results_path = output_dir / "results.jsonl"
    records = load_results(results_path)
    summary = compute_summary(records)
    write_summary_json(summary, output_dir / "summary.json")
    write_summary_md(summary, output_dir / "summary.md", run_id)
    return summary
