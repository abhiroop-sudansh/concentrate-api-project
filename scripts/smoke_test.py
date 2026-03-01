#!/usr/bin/env python3
"""
Smoke test: call Concentrate AI /v1/responses for OpenAI and Anthropic models.
Run from repo root: python scripts/smoke_test.py
"""

import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

# Allow importing from src when run as script
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.concentrate_client import ConcentrateClient
from src.response_parsing import extract_output_text, extract_usage


def _load_env() -> None:
    env_path = _REPO_ROOT / ".env"
    load_dotenv(env_path)


def _run_one(
    client: ConcentrateClient,
    model: str,
    prompt: str,
    label: str,
) -> None:
    print(f"\n--- {label} (model: {model}) ---")
    start = time.perf_counter()
    try:
        resp_json = client.create_response(model=model, input_text=prompt)
        latency_sec = time.perf_counter() - start
    except httpx.HTTPStatusError as e:
        latency_sec = time.perf_counter() - start
        body = e.response.text
        try:
            body = e.response.json()
        except Exception:
            pass
        print(f"FAILED status_code={e.response.status_code} error_body={body}")
        return
    except Exception as e:
        latency_sec = time.perf_counter() - start
        print(f"FAILED exception={type(e).__name__}: {e}")
        return

    output_text = extract_output_text(resp_json)
    usage = extract_usage(resp_json)
    total_tokens = usage.get("total_tokens", "N/A")

    if not output_text:
        print("WARN: output_text empty; check parsing.")

    print(f"model:          {model}")
    print(f"output_text:    {output_text[:500]}{'...' if len(output_text) > 500 else ''}")
    print(f"usage.total_tokens: {total_tokens}")
    print(f"latency:        {latency_sec:.2f}s")


def main() -> None:
    _load_env()

    api_key = os.environ.get("CONCENTRATE_API_KEY")
    if not api_key:
        print("ERROR: CONCENTRATE_API_KEY not set in .env")
        sys.exit(1)

    base_url = os.environ.get(
        "CONCENTRATE_BASE_URL",
        "https://api.concentrate.ai",
    )
    timeout = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "60"))
    openai_model = os.environ.get("OPENAI_MODEL", "openai/gpt-5.2")
    anthropic_model = os.environ.get("ANTHROPIC_MODEL", "anthropic/claude-opus-4-6")

    client = ConcentrateClient(api_key=api_key, base_url=base_url, timeout=timeout)
    prompt = "Say OK and give 2 bullets about why API experiments matter."

    print("Concentrate AI smoke test")
    _run_one(client, openai_model, prompt, "OpenAI")
    _run_one(client, anthropic_model, prompt, "Anthropic")
    print("\nDone.")


if __name__ == "__main__":
    main()
