# Concentrate API Exercise — Multi-provider Experiment Runner

## What I did first

I validated the API from the dashboard (Playground, Logs, Billing), then ran the repo smoke test to confirm both providers and `usage` from `/v1/responses`. Next I built the experiment runner: grid over suites × providers × temperatures, logging every call to `results.jsonl`, with retries, JSON repair, and provider failover. I added the long-doc suite (generated synthetic docs, 3 cases per doc), then wired in optional judge scoring and a heuristic QA grounding metric for `_qa` cases. All of that is driven from the CLI; artifacts live under `runs/run_<timestamp>/`.

## How to run it

- `python scripts/smoke_test.py`
- `python scripts/run_experiments.py --suite prompts/suite_basic.jsonl --providers openai,anthropic --temps 0,0.7 --max-output 256 --retries 1`

Outputs go to `runs/run_<timestamp>/`. See README “Submission pack” for the run IDs to inspect (e.g. run_20260228T205121Z, run_20260228T205512Z, run_20260228T191921Z, run_20260228T215442Z).

## Three concrete findings (from the runs)

1. **Latency and tokens by provider**  
   In run_20260228T215442Z (long-doc suite, 56 calls): OpenAI averaged **5124 ms** and **2819 tokens** per call; Anthropic **7403 ms** and **3257 tokens**. So Anthropic was ~1.4× slower and used more tokens on this workload. In the smaller robust run (run_20260228T191921Z), OpenAI averaged 1894 ms and 42.7 tokens, Anthropic 4906 ms and 53 tokens—again Anthropic slower and heavier.

2. **JSON repair and final compliance**  
   In run_20260228T215442Z there were **8 invalid primary** JSON responses; **8 were repaired to valid** (100% repair success). Final JSON compliance rate was 100% (every slot ended with valid JSON). So repair-on-same-provider worked; fallback wasn’t needed for that run.

3. **QA grounding (heuristic)**  
   Same run: for `_qa` cases, the heuristic (answer substring in doc → SUPPORTED, “unknown” → UNKNOWN, else HALLUCINATED) gave **openai** 66.67% supported / 12.50% hallucinated and **anthropic** 91.67% supported / 8.33% hallucinated. By temp, 0.0 had 75% supported / 16.67% hallucinated and 0.7 had 83.33% supported / 4.17% hallucinated. So on this suite Anthropic had higher supported rate and lower hallucinated rate.

## What worked

- OpenAI and Anthropic both worked from dashboard and from the script; `/v1/responses` and `usage` were consistent.
- Strict JSON prompts usually came back valid; when they didn’t, repair (re-ask same model with the invalid output) fixed them in the long-doc run.
- Guardrails redacted email/phone in **model outputs** as expected ([EMAIL], [PHONE]).
- Treating 424 (and 429/5xx) as retryable and then doing one fallback to the other provider kept the run from failing completely when Anthropic returned 424.

## What didn’t / surprises

- **Anthropic HTTP 424**  
  In run_20260228T191921Z (suite_robust, 3 cases × 2 providers): 6 calls, 4 success, 2 failures—both Anthropic, HTTP 424 “Provider Error” (provider unavailable). So the failure was intermittent and provider-specific; the runner recorded it and could retry/fallback.

- **Guardrails “Both” and Logs**  
  With Redact set to Both (Input + Output), the **output** was redacted but the **request body in Logs** still showed raw email/phone. So “Both” doesn’t redact what’s stored in Logs for the request; only the response was redacted. That’s a mismatch if users assume Logs are PII-safe when Both is on.

- **Playground params**  
  Effective request params (e.g. max_output_tokens, top_p) weren’t obvious in the UI; responses sometimes showed defaults (e.g. 128000) that didn’t match what I thought I’d set. I didn’t dig into whether that’s UI vs actual backend.

## Tradeoff: CLI artifacts instead of a UI

I kept everything as files (results.jsonl, summary.json, summary.md) and didn’t add a web UI. Reason: reproducibility and review. Anyone can re-run the same commands, diff summaries, and grep results without depending on a custom app. A small UI would be nice for browsing runs later, but for this exercise I prioritized “run once, inspect with standard tools.”

## Next improvements (if I had more time)

- Streaming support (when available) and handling partial failures.
- A minimal UI to browse runs and compare summaries.
- More suites closer to real tasks (e.g. domain-specific long-doc QA).