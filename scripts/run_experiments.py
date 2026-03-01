#!/usr/bin/env python3
"""
Run experiment grid: providers × temps × max_output_tokens × prompt cases.
Logs every call to results.jsonl, writes summary.json and summary.md.
"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.concentrate_client import ConcentrateClient
from src.experiment_runner import load_prompt_suite, run_experiment
from src.reporting import generate_reports


def _parse_temps(s: str) -> list[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


def _parse_providers(s: str) -> list[str]:
    return [x.strip().lower() for x in s.split(",") if x.strip()]


def main() -> int:
    load_dotenv(_REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Run Concentrate API experiment grid")
    parser.add_argument("--suite", required=True, type=Path, help="Path to prompt suite JSONL")
    parser.add_argument(
        "--providers",
        default="openai,anthropic",
        type=str,
        help="Comma-separated providers (default: openai,anthropic)",
    )
    parser.add_argument(
        "--temps",
        default="0,0.3,0.7",
        type=str,
        help="Comma-separated temperatures (default: 0,0.3,0.7)",
    )
    parser.add_argument(
        "--max-output",
        default=256,
        type=int,
        help="max_output_tokens (default: 256)",
    )
    parser.add_argument(
        "--retries",
        default=2,
        type=int,
        help="Retries on 429/5xx (default: 2)",
    )
    parser.add_argument(
        "--out",
        default=None,
        type=Path,
        help="Output directory (default: runs/run_<UTC timestamp>)",
    )
    parser.add_argument(
        "--limit",
        default=None,
        type=int,
        help="Limit number of prompt cases",
    )
    args = parser.parse_args()

    api_key = os.environ.get("CONCENTRATE_API_KEY")
    if not api_key:
        print("ERROR: CONCENTRATE_API_KEY not set in .env", file=sys.stderr)
        return 1

    base_url = os.environ.get("CONCENTRATE_BASE_URL", "https://api.concentrate.ai")
    timeout = float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "60"))
    openai_model = os.environ.get("OPENAI_MODEL", "openai/gpt-5.2")
    anthropic_model = os.environ.get("ANTHROPIC_MODEL", "anthropic/claude-opus-4-6")

    provider_models = {
        "openai": openai_model,
        "anthropic": anthropic_model,
    }
    providers = _parse_providers(args.providers)
    temps = _parse_temps(args.temps)

    suite_path = args.suite if args.suite.is_absolute() else _REPO_ROOT / args.suite
    if not suite_path.exists():
        print(f"ERROR: Suite not found: {suite_path}", file=sys.stderr)
        return 1

    cases = load_prompt_suite(suite_path, limit=args.limit)
    if not cases:
        print("ERROR: No prompt cases loaded from suite", file=sys.stderr)
        return 1

    if args.out is not None:
        output_dir = args.out if args.out.is_absolute() else _REPO_ROOT / args.out
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = _REPO_ROOT / "runs" / f"run_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = output_dir.name

    client = ConcentrateClient(api_key=api_key, base_url=base_url, timeout=timeout)

    print(f"Run ID: {run_id}")
    print(f"Suite: {suite_path} ({len(cases)} cases)")
    print(f"Providers: {providers}, temps: {temps}, max_output: {args.max_output}, retries: {args.retries}")
    print(f"Output: {output_dir}")
    print("Running grid...")

    try:
        run_experiment(
            run_id=run_id,
            output_dir=output_dir,
            client=client,
            provider_models=provider_models,
            cases=cases,
            providers=providers,
            temps=temps,
            max_output_tokens=args.max_output,
            retries=args.retries,
        )
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    summary = generate_reports(output_dir, run_id)
    print(f"Total calls: {summary['total_calls']}, success rate: {summary['success_rate']:.1%}")
    print(f"Results: {output_dir / 'results.jsonl'}")
    print(f"Summary: {output_dir / 'summary.json'}, {output_dir / 'summary.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
