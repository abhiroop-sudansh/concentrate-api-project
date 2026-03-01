"""Types for the experiment runner and reporting."""

from dataclasses import dataclass
from typing import Any


@dataclass
class PromptCase:
    """A single prompt from a suite JSONL."""
    id: str
    category: str  # "basic" | "json" | "robust"
    input: str
    expect_format: str  # "text" | "json"


def prompt_case_from_dict(d: dict) -> PromptCase:
    """Build PromptCase from JSON object; expect is {format: 'text'|'json'}."""
    expect = d.get("expect") or {}
    fmt = expect.get("format", "text")
    if fmt not in ("text", "json"):
        fmt = "text"
    return PromptCase(
        id=str(d.get("id", "")),
        category=str(d.get("category", "")),
        input=str(d.get("input", "")),
        expect_format=fmt,
    )


@dataclass
class ResultRecord:
    """One API call result, written as one JSONL line."""
    run_id: str
    timestamp_utc: str
    provider: str
    model: str
    prompt_id: str
    category: str
    temperature: float
    max_output_tokens: int
    success: bool
    http_status: int | None
    latency_ms: float
    output_preview: str
    usage_input_tokens: int | None
    usage_output_tokens: int | None
    usage_total_tokens: int | None
    json_valid: bool | None  # only for expect.format == "json"
    json_error: str | None
    error_message: str | None
    response_id: str | None
    # Format repair & fallback (Milestone 3)
    attempt_type: str = "primary"  # "primary" | "repair" | "fallback"
    parent_response_id: str | None = None
    repair_attempt: int | None = None
    fallback_provider: str | None = None
    final_for_case: bool = True
    # Full output for final record (used by judge); judge scoring
    output_text_full: str | None = None
    scores: dict[str, Any] | None = None
    judge_notes: str | None = None
    evaluated_provider: str | None = None
    evaluated_temp: float | None = None
    evaluated_prompt_id: str | None = None
    # Long-doc QA grounding (heuristic): only on final_for_case when prompt_id ends with _qa
    qa_total: int | None = None
    qa_supported: int | None = None
    qa_unknown: int | None = None
    qa_hallucinated: int | None = None
    qa_supported_rate: float | None = None
    qa_hallucinated_rate: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp_utc": self.timestamp_utc,
            "provider": self.provider,
            "model": self.model,
            "prompt_id": self.prompt_id,
            "category": self.category,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "success": self.success,
            "http_status": self.http_status,
            "latency_ms": self.latency_ms,
            "output_preview": self.output_preview,
            "usage_input_tokens": self.usage_input_tokens,
            "usage_output_tokens": self.usage_output_tokens,
            "usage_total_tokens": self.usage_total_tokens,
            "json_valid": self.json_valid,
            "json_error": self.json_error,
            "error_message": self.error_message,
            "response_id": self.response_id,
            "attempt_type": self.attempt_type,
            "parent_response_id": self.parent_response_id,
            "repair_attempt": self.repair_attempt,
            "fallback_provider": self.fallback_provider,
            "final_for_case": self.final_for_case,
            "output_text_full": self.output_text_full,
            "scores": self.scores,
            "judge_notes": self.judge_notes,
            "evaluated_provider": self.evaluated_provider,
            "evaluated_temp": self.evaluated_temp,
            "evaluated_prompt_id": self.evaluated_prompt_id,
            "qa_total": self.qa_total,
            "qa_supported": self.qa_supported,
            "qa_unknown": self.qa_unknown,
            "qa_hallucinated": self.qa_hallucinated,
            "qa_supported_rate": self.qa_supported_rate,
            "qa_hallucinated_rate": self.qa_hallucinated_rate,
        }
