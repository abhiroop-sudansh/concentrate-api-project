"""Experiment runner: grid of API calls with retries, JSON repair, and fallback routing."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from src.concentrate_client import ConcentrateClient
from src.experiment_types import PromptCase, ResultRecord, prompt_case_from_dict
from src.response_parsing import extract_output_text, extract_usage

REPAIR_INVALID_MAX_CHARS = 800

# Format repair & fallback (env override, no CLI change)
def _repair_attempts() -> int:
    return int(os.environ.get("REPAIR_ATTEMPTS", "2"))


def _enable_fallback() -> bool:
    return os.environ.get("ENABLE_FALLBACK", "true").lower() in ("true", "1", "yes")


def _enable_judge() -> bool:
    return os.environ.get("ENABLE_JUDGE", "false").lower() in ("true", "1", "yes")


def _judge_model() -> str:
    return os.environ.get("JUDGE_MODEL", "openai/gpt-5.2")


def _judge_temperature() -> float:
    return float(os.environ.get("JUDGE_TEMPERATURE", "0"))


def load_prompt_suite(path: Path, limit: int | None = None) -> list[PromptCase]:
    """Load JSONL prompt suite; optional limit on number of cases."""
    cases: list[PromptCase] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                cases.append(prompt_case_from_dict(obj))
            except (json.JSONDecodeError, TypeError):
                continue
    return cases


def _validate_json(output_text: str) -> tuple[bool, str | None]:
    """Try to parse output as JSON. Return (valid, error_message)."""
    text = output_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        json.loads(text)
        return True, None
    except json.JSONDecodeError as e:
        return False, str(e)


def _schema_hint(case: PromptCase) -> str:
    """Extract schema description from prompt if possible; else generic."""
    inp = case.input or ""
    for marker in ("Schema:", "schema:", "Format:", "format:"):
        i = inp.find(marker)
        if i >= 0:
            snippet = inp[i : i + 300].strip()
            return snippet if snippet else "must be valid JSON"
    if "{" in inp:
        start = inp.find("{")
        return inp[start : start + 250] + ("..." if len(inp) > start + 250 else "")
    return "must be valid JSON"


def _build_repair_prompt(case: PromptCase, invalid_output: str) -> str:
    """Strict repair prompt; invalid_output truncated to REPAIR_INVALID_MAX_CHARS."""
    truncated = (invalid_output or "")[:REPAIR_INVALID_MAX_CHARS]
    schema = _schema_hint(case)
    return (
        "You returned invalid JSON. Output ONLY valid JSON that matches this schema: "
        + schema
        + "\nDo not include markdown or extra text.\nHere is your previous output:\n"
        + truncated
    )


def _call_with_retries(
    client: ConcentrateClient,
    model: str,
    input_text: str,
    temperature: float,
    max_output_tokens: int,
    retries: int,
) -> tuple[dict | None, int | None, float, str | None]:
    """
    Call API with retry on 424 (Provider Error), 429, and >=500. Exponential backoff 1s, 2s, 4s.
    Returns (resp_json, http_status, latency_ms, error_message).
    """
    extra = {
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    last_status: int | None = None
    last_error: str | None = None
    for attempt in range(retries + 1):
        start = time.perf_counter()
        try:
            with httpx.Client(timeout=client.timeout) as http_client:
                url = f"{client.base_url}/v1/responses"
                headers = {
                    "Authorization": f"Bearer {client.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                }
                body = {
                    "model": model,
                    "input": input_text,
                    **extra,
                }
                response = http_client.post(url, headers=headers, json=body)
                latency_ms = (time.perf_counter() - start) * 1000
                last_status = response.status_code

                if response.status_code == 424 or response.status_code == 429 or response.status_code >= 500:
                    last_error = response.text
                    if attempt < retries:
                        delay = 2**attempt
                        time.sleep(delay)
                        continue
                    return None, last_status, latency_ms, last_error

                response.raise_for_status()
                return response.json(), last_status, latency_ms, None
        except httpx.HTTPStatusError as e:
            last_status = e.response.status_code
            try:
                last_error = e.response.text or str(e)
            except Exception:
                last_error = str(e)
            latency_ms = (time.perf_counter() - start) * 1000
            if last_status == 424 or last_status == 429 or last_status >= 500:
                if attempt < retries:
                    delay = 2**attempt
                    time.sleep(delay)
                    continue
            return None, last_status, latency_ms, last_error
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            last_error = str(e)
            return None, last_status, latency_ms, last_error
    return None, last_status, 0.0, last_error


def _make_record(
    run_id: str,
    provider: str,
    model: str,
    case: PromptCase,
    temp: float,
    max_output_tokens: int,
    resp_json: dict | None,
    http_status: int | None,
    latency_ms: float,
    error_message: str | None,
    attempt_type: str = "primary",
    parent_response_id: str | None = None,
    repair_attempt: int | None = None,
    fallback_provider: str | None = None,
    final_for_case: bool = True,
) -> ResultRecord:
    """Build a ResultRecord from one API call; validate JSON when expect_format is json."""
    success = resp_json is not None
    output_preview = ""
    output_text_full: str | None = None
    usage_input: int | None = None
    usage_output: int | None = None
    usage_total: int | None = None
    response_id: str | None = None
    json_valid: bool | None = None
    json_error: str | None = None

    if resp_json is not None:
        output_text = extract_output_text(resp_json)
        output_preview = (output_text or "")[:500]
        output_text_full = output_text or None
        usage = extract_usage(resp_json)
        usage_input = usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else None
        usage_output = usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else None
        usage_total = usage.get("total_tokens") if isinstance(usage.get("total_tokens"), int) else None
        rid = resp_json.get("id")
        response_id = str(rid) if rid is not None else None
        if case.expect_format == "json":
            json_valid, json_error = _validate_json(output_text)

    return ResultRecord(
        run_id=run_id,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        provider=provider,
        model=model,
        prompt_id=case.id,
        category=case.category,
        temperature=temp,
        max_output_tokens=max_output_tokens,
        success=success,
        http_status=http_status,
        latency_ms=latency_ms,
        output_preview=output_preview,
        output_text_full=output_text_full,
        usage_input_tokens=usage_input,
        usage_output_tokens=usage_output,
        usage_total_tokens=usage_total,
        json_valid=json_valid,
        json_error=json_error,
        error_message=error_message,
        response_id=response_id,
        attempt_type=attempt_type,
        parent_response_id=parent_response_id,
        repair_attempt=repair_attempt,
        fallback_provider=fallback_provider,
        final_for_case=final_for_case,
    )


JUDGE_RUBRIC = """Score the model output (0-5 each). Return EXACT JSON and nothing else:
{
  "scores": {
    "instruction_following": 0-5,
    "format_compliance": 0-5,
    "conciseness": 0-5,
    "grounding": 0-5
  },
  "notes": "short sentence"
}
Grounding: If the prompt says answer ONLY from the document or say UNKNOWN when missing, penalize hallucinations (invented facts)."""


def _build_judge_prompt(original_prompt: str, model_output: str) -> str:
    return (
        "You are a judge evaluating a model's response to a user prompt.\n\n"
        "--- Original prompt ---\n"
        f"{original_prompt}\n\n"
        "--- Model output ---\n"
        f"{model_output}\n\n"
        "--- Instructions ---\n"
        f"{JUDGE_RUBRIC}"
    )


def _run_judge(
    client: ConcentrateClient,
    judge_model: str,
    judge_temperature: float,
    judge_prompt: str,
    retries: int,
    max_output_tokens: int = 512,
) -> tuple[dict | None, int | None, float, str | None]:
    """One judge API call. Returns (resp_json, http_status, latency_ms, error_message)."""
    return _call_with_retries(
        client=client,
        model=judge_model,
        input_text=judge_prompt,
        temperature=judge_temperature,
        max_output_tokens=max_output_tokens,
        retries=retries,
    )


def _parse_judge_response(resp_json: dict | None) -> tuple[dict | None, str | None]:
    """Extract scores dict and notes from judge response. Returns (scores, judge_notes)."""
    if resp_json is None:
        return None, None
    output_text = extract_output_text(resp_json)
    valid, _ = _validate_json(output_text)
    if not valid:
        return None, None
    try:
        data = json.loads(output_text.strip())
        scores = data.get("scores")
        notes = data.get("notes")
        if isinstance(scores, dict):
            return scores, (str(notes) if notes is not None else None)
    except (json.JSONDecodeError, TypeError):
        pass
    return None, None


def _make_judge_record(
    run_id: str,
    judge_model: str,
    prompt_id: str,
    category: str,
    evaluated_provider: str,
    evaluated_temp: float,
    parent_response_id: str | None,
    resp_json: dict | None,
    http_status: int | None,
    latency_ms: float,
    error_message: str | None,
    scores: dict | None,
    judge_notes: str | None,
) -> ResultRecord:
    """Build a ResultRecord for a judge call (attempt_type=judge, provider=judge)."""
    success = resp_json is not None and scores is not None
    output_preview = ""
    usage_input: int | None = None
    usage_output: int | None = None
    usage_total: int | None = None
    response_id: str | None = None
    if resp_json is not None:
        output_text = extract_output_text(resp_json)
        output_preview = (output_text or "")[:500]
        usage = extract_usage(resp_json)
        usage_input = usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else None
        usage_output = usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else None
        usage_total = usage.get("total_tokens") if isinstance(usage.get("total_tokens"), int) else None
        rid = resp_json.get("id")
        response_id = str(rid) if rid is not None else None
    return ResultRecord(
        run_id=run_id,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        provider="judge",
        model=judge_model,
        prompt_id=prompt_id,
        category=category,
        temperature=_judge_temperature(),
        max_output_tokens=512,
        success=success,
        http_status=http_status,
        latency_ms=latency_ms,
        output_preview=output_preview,
        output_text_full=None,
        usage_input_tokens=usage_input,
        usage_output_tokens=usage_output,
        usage_total_tokens=usage_total,
        json_valid=None,
        json_error=None,
        error_message=error_message,
        response_id=response_id,
        attempt_type="judge",
        parent_response_id=parent_response_id,
        repair_attempt=None,
        fallback_provider=None,
        final_for_case=False,
        scores=scores,
        judge_notes=judge_notes,
        evaluated_provider=evaluated_provider,
        evaluated_temp=evaluated_temp,
        evaluated_prompt_id=prompt_id,
    )


def _extract_doc_text(prompt: str) -> str:
    """Extract document text from longdoc prompt: everything after 'Document:'."""
    if "Document:" not in prompt:
        return ""
    return prompt.split("Document:", 1)[-1].strip()


def _compute_qa_grounding(case: PromptCase, final_record: ResultRecord) -> dict | None:
    """
    For _qa cases: parse final JSON, extract answers from questions[i][a],
    compare to doc text. Return qa_total, qa_supported, qa_unknown, qa_hallucinated, rates, or None on failure.
    """
    if not (case.id.endswith("_qa") or (case.category == "longdocs" and case.expect_format == "json")):
        return None
    doc_text = _extract_doc_text(case.input)
    if not doc_text:
        return None
    output_text = final_record.output_text_full or final_record.output_preview or ""
    valid, _ = _validate_json(output_text)
    if not valid:
        return None
    text = output_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        data = json.loads(text)
        questions = data.get("questions")
        if not isinstance(questions, list):
            return None
        doc_norm = doc_text.lower()
        total = 0
        supported = 0
        unknown = 0
        hallucinated = 0
        for item in questions:
            if not isinstance(item, dict):
                continue
            a = item.get("a")
            if a is None:
                continue
            ans = (a if isinstance(a, str) else str(a)).strip().lower()
            total += 1
            if ans == "unknown" or (len(ans) <= 12 and ans.startswith("unknown")):
                unknown += 1
            elif ans and ans in doc_norm:
                supported += 1
            else:
                hallucinated += 1
        if total == 0:
            return None
        return {
            "qa_total": total,
            "qa_supported": supported,
            "qa_unknown": unknown,
            "qa_hallucinated": hallucinated,
            "qa_supported_rate": supported / total,
            "qa_hallucinated_rate": hallucinated / total,
        }
    except (json.JSONDecodeError, TypeError, KeyError):
        return None


def _compute_and_attach_qa_grounding(records_for_slot: list[ResultRecord], case: PromptCase) -> None:
    """If case is _qa and final output is valid JSON, compute QA grounding and set on final record. Never raises."""
    try:
        final_record = next((r for r in records_for_slot if r.final_for_case), None)
        if final_record is None:
            return
        metrics = _compute_qa_grounding(case, final_record)
        if metrics is None:
            return
        final_record.qa_total = metrics["qa_total"]
        final_record.qa_supported = metrics["qa_supported"]
        final_record.qa_unknown = metrics["qa_unknown"]
        final_record.qa_hallucinated = metrics["qa_hallucinated"]
        final_record.qa_supported_rate = metrics["qa_supported_rate"]
        final_record.qa_hallucinated_rate = metrics["qa_hallucinated_rate"]
    except Exception:
        pass


def _append_records(results_path: Path, records: list[ResultRecord]) -> None:
    """Append all records to results.jsonl."""
    with open(results_path, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")


def _run_judge_for_slot(
    client: ConcentrateClient,
    run_id: str,
    results_path: Path,
    records_for_slot: list[ResultRecord],
    case: PromptCase,
    provider: str,
    temp: float,
    retries: int,
    all_records: list[ResultRecord],
) -> None:
    """If ENABLE_JUDGE, run judge on the final record for this slot; append judge record. Never raises."""
    if not _enable_judge():
        return
    final_record = next((r for r in records_for_slot if r.final_for_case), None)
    if final_record is None:
        return
    model_output = final_record.output_text_full or final_record.output_preview or ""
    if not model_output.strip():
        return
    try:
        judge_model = _judge_model()
        judge_temp = _judge_temperature()
        judge_prompt = _build_judge_prompt(case.input, model_output)
        resp_json, http_status, latency_ms, error_message = _run_judge(
            client=client,
            judge_model=judge_model,
            judge_temperature=judge_temp,
            judge_prompt=judge_prompt,
            retries=retries,
            max_output_tokens=512,
        )
        scores, judge_notes = _parse_judge_response(resp_json) if resp_json else (None, None)
        judge_record = _make_judge_record(
            run_id=run_id,
            judge_model=judge_model,
            prompt_id=case.id,
            category=case.category,
            evaluated_provider=final_record.provider,
            evaluated_temp=temp,
            parent_response_id=final_record.response_id,
            resp_json=resp_json,
            http_status=http_status,
            latency_ms=latency_ms,
            error_message=error_message,
            scores=scores,
            judge_notes=judge_notes,
        )
        _append_records(results_path, [judge_record])
        all_records.append(judge_record)
    except Exception:
        pass


def run_experiment(
    run_id: str,
    output_dir: Path,
    client: ConcentrateClient,
    provider_models: dict[str, str],
    cases: list[PromptCase],
    providers: list[str],
    temps: list[float],
    max_output_tokens: int,
    retries: int,
) -> list[ResultRecord]:
    """
    Run the full grid (providers × temps × cases). For JSON prompts, on invalid output
    run repair attempts then optional fallback; record all attempts. Exactly one
    record per (provider, temp, prompt_id) slot has final_for_case=True.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.jsonl"
    all_records: list[ResultRecord] = []
    repair_attempts = _repair_attempts()
    enable_fallback = _enable_fallback()

    for provider in providers:
        model = provider_models.get(provider)
        if not model:
            continue
        for temp in temps:
            for case in cases:
                records_for_slot: list[ResultRecord] = []

                # Primary call
                resp_json, http_status, latency_ms, error_message = _call_with_retries(
                    client=client,
                    model=model,
                    input_text=case.input,
                    temperature=temp,
                    max_output_tokens=max_output_tokens,
                    retries=retries,
                )
                output_text = extract_output_text(resp_json) if resp_json else ""
                primary_record = _make_record(
                    run_id=run_id,
                    provider=provider,
                    model=model,
                    case=case,
                    temp=temp,
                    max_output_tokens=max_output_tokens,
                    resp_json=resp_json,
                    http_status=http_status,
                    latency_ms=latency_ms,
                    error_message=error_message,
                    attempt_type="primary",
                    final_for_case=True,
                )
                records_for_slot.append(primary_record)

                # Provider failover: if primary failed (424/429/5xx after retries), try other provider once
                if not primary_record.success and enable_fallback:
                    other_provider = "anthropic" if provider == "openai" else "openai"
                    other_model = provider_models.get(other_provider)
                    if other_model:
                        resp_f, status_f, latency_f, err_f = _call_with_retries(
                            client=client,
                            model=other_model,
                            input_text=case.input,
                            temperature=temp,
                            max_output_tokens=max_output_tokens,
                            retries=retries,
                        )
                        fallback_record = _make_record(
                            run_id=run_id,
                            provider=other_provider,
                            model=other_model,
                            case=case,
                            temp=temp,
                            max_output_tokens=max_output_tokens,
                            resp_json=resp_f,
                            http_status=status_f,
                            latency_ms=latency_f,
                            error_message=err_f,
                            attempt_type="fallback",
                            parent_response_id=None,
                            fallback_provider=other_provider,
                            final_for_case=False,
                        )
                        records_for_slot.append(fallback_record)
                        if fallback_record.success:
                            primary_record.final_for_case = False
                            fallback_record.final_for_case = True
                    _compute_and_attach_qa_grounding(records_for_slot, case)
                    _append_records(results_path, records_for_slot)
                    all_records.extend(records_for_slot)
                    _run_judge_for_slot(client, run_id, results_path, records_for_slot, case, provider, temp, retries, all_records)
                    continue

                if case.expect_format != "json":
                    _compute_and_attach_qa_grounding(records_for_slot, case)
                    _append_records(results_path, records_for_slot)
                    all_records.extend(records_for_slot)
                    _run_judge_for_slot(client, run_id, results_path, records_for_slot, case, provider, temp, retries, all_records)
                    continue

                valid, _ = _validate_json(output_text)
                if valid:
                    _compute_and_attach_qa_grounding(records_for_slot, case)
                    _append_records(results_path, records_for_slot)
                    all_records.extend(records_for_slot)
                    _run_judge_for_slot(client, run_id, results_path, records_for_slot, case, provider, temp, retries, all_records)
                    continue

                # Repair attempts (same provider/model/temp)
                last_invalid_output = output_text
                parent_id = primary_record.response_id
                repair_succeeded = False
                for repair_num in range(1, repair_attempts + 1):
                    repair_prompt = _build_repair_prompt(case, last_invalid_output)
                    resp_r, status_r, latency_r, err_r = _call_with_retries(
                        client=client,
                        model=model,
                        input_text=repair_prompt,
                        temperature=temp,
                        max_output_tokens=max_output_tokens,
                        retries=retries,
                    )
                    output_text_r = extract_output_text(resp_r) if resp_r else ""
                    valid_r, _ = _validate_json(output_text_r)
                    repair_record = _make_record(
                        run_id=run_id,
                        provider=provider,
                        model=model,
                        case=case,
                        temp=temp,
                        max_output_tokens=max_output_tokens,
                        resp_json=resp_r,
                        http_status=status_r,
                        latency_ms=latency_r,
                        error_message=err_r,
                        attempt_type="repair",
                        parent_response_id=parent_id,
                        repair_attempt=repair_num,
                        final_for_case=False,
                    )
                    records_for_slot.append(repair_record)
                    last_invalid_output = output_text_r
                    parent_id = repair_record.response_id
                    if valid_r:
                        primary_record.final_for_case = False
                        repair_record.final_for_case = True
                        repair_succeeded = True
                        break

                if repair_succeeded:
                    _compute_and_attach_qa_grounding(records_for_slot, case)
                    _append_records(results_path, records_for_slot)
                    all_records.extend(records_for_slot)
                    _run_judge_for_slot(client, run_id, results_path, records_for_slot, case, provider, temp, retries, all_records)
                    continue

                # Fallback: one call with other provider, temp=0, original input
                if enable_fallback:
                    other_provider = "anthropic" if provider == "openai" else "openai"
                    other_model = provider_models.get(other_provider)
                    if other_model:
                        resp_f, status_f, latency_f, err_f = _call_with_retries(
                            client=client,
                            model=other_model,
                            input_text=case.input,
                            temperature=0.0,
                            max_output_tokens=max_output_tokens,
                            retries=retries,
                        )
                        output_text_f = extract_output_text(resp_f) if resp_f else ""
                        valid_f, _ = _validate_json(output_text_f)
                        fallback_record = _make_record(
                            run_id=run_id,
                            provider=other_provider,
                            model=other_model,
                            case=case,
                            temp=0.0,
                            max_output_tokens=max_output_tokens,
                            resp_json=resp_f,
                            http_status=status_f,
                            latency_ms=latency_f,
                            error_message=err_f,
                            attempt_type="fallback",
                            parent_response_id=parent_id,
                            fallback_provider=other_provider,
                            final_for_case=False,
                        )
                        records_for_slot.append(fallback_record)
                        if valid_f:
                            for r in records_for_slot:
                                r.final_for_case = False
                            fallback_record.final_for_case = True
                        else:
                            repair_records = [r for r in records_for_slot if r.attempt_type == "repair"]
                            for r in records_for_slot:
                                r.final_for_case = False
                            if repair_records:
                                repair_records[-1].final_for_case = True
                            else:
                                primary_record.final_for_case = True
                    else:
                        repair_records = [r for r in records_for_slot if r.attempt_type == "repair"]
                        for r in records_for_slot:
                            r.final_for_case = False
                        if repair_records:
                            repair_records[-1].final_for_case = True
                        else:
                            primary_record.final_for_case = True
                else:
                    repair_records = [r for r in records_for_slot if r.attempt_type == "repair"]
                    for r in records_for_slot:
                        r.final_for_case = False
                    if repair_records:
                        repair_records[-1].final_for_case = True
                    else:
                        primary_record.final_for_case = True

                _compute_and_attach_qa_grounding(records_for_slot, case)
                _append_records(results_path, records_for_slot)
                all_records.extend(records_for_slot)
                _run_judge_for_slot(client, run_id, results_path, records_for_slot, case, provider, temp, retries, all_records)

    return all_records
