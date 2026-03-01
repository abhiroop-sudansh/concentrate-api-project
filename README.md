# concentrate_ai_project

Minimal Python client and smoke test for [Concentrate AI](https://api.concentrate.ai) OpenAI-compatible `/v1/responses` endpoint.

## Submission pack (what to review)

### 1) Quick smoke test
- `python scripts/smoke_test.py`

### 2) Main benchmark runs (artifacts already generated)
Recommended run folders to inspect under `runs/`:
- **run_20260228T205121Z** — basic suite (80 calls): latency/tokens comparison across providers and temperatures  
- **run_20260228T205512Z** — json suite (60 calls): JSON compliance + repair/fallback behavior  
- **run_20260228T191921Z** — robust suite with provider failure evidence (Anthropic HTTP 424 Provider Error)  
- **run_20260228T215442Z** — long-doc suite (56 calls) with judge scoring + QA grounding metrics + JSON repair success  

Each run folder contains:
- `results.jsonl` — every call/attempt recorded
- `summary.json` — aggregate metrics
- `summary.md` — human-readable report

### 3) Human writeup and API feedback
- `EXERCISE_WRITEUP.md` — experiment narrative and findings.
- `API_FRICTION_SUGGESTIONS.md`

### 4) Screenshots
- See `screenshots/` (Playground examples, Logs, Billing, Guardrails behavior).

## Setup

1. **Clone or create the project** and enter the repo:

   ```bash
   cd concentrate_ai_project
   ```

2. **Create a virtual environment** (recommended):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate   # Linux/macOS
   # or:  .venv\Scripts\activate   # Windows
   ```

3. **Install dependencies**:

   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**:

   - Copy `.env.example` to `.env`.
   - Set `CONCENTRATE_API_KEY` to your Concentrate API key.
   - Optionally set `CONCENTRATE_BASE_URL`, `OPENAI_MODEL`, `ANTHROPIC_MODEL`, `REQUEST_TIMEOUT_SECONDS`.

   **Never commit `.env`** — it is listed in `.gitignore` and may contain secrets.

## Run smoke test

From the **repo root** (`concentrate_ai_project/`):

```bash
python scripts/smoke_test.py
```

The script calls two providers via Concentrate:

- **OpenAI** (default model: `openai/gpt-5.2`)
- **Anthropic** (default model: `anthropic/claude-opus-4-6`)

For each call it prints: `model`, `output_text`, `usage.total_tokens`, and client-side latency. On failure it prints HTTP status code and error body (API keys are never printed).

## Run experiments (Milestone 2)

From the repo root, run the experiment runner with a prompt suite:

```bash
python scripts/run_experiments.py --suite prompts/suite_basic.jsonl
```

**Options:**

- `--suite` (required) — path to prompt suite JSONL (e.g. `prompts/suite_basic.jsonl`, `prompts/suite_json.jsonl`, `prompts/suite_robust.jsonl`)
- `--providers` — comma-separated (default: `openai,anthropic`)
- `--temps` — comma-separated temperatures (default: `0,0.3,0.7`)
- `--max-output` — max_output_tokens (default: 256)
- `--retries` — retries on 429/5xx (default: 2)
- `--out` — output directory (default: `runs/run_<UTC timestamp>`)
- `--limit` — limit number of prompt cases (optional)

**Example:**

```bash
python scripts/run_experiments.py \
  --suite prompts/suite_basic.jsonl \
  --providers openai,anthropic \
  --temps 0,0.7 \
  --max-output 256 \
  --retries 1 \
  --limit 3
```

**Artifacts** (written under the output folder, e.g. `runs/run_20250228T120000Z/`):

- `results.jsonl` — one JSON object per API call (run_id, provider, model, prompt_id, success, latency_ms, usage, json_valid, attempt_type, final_for_case, repair/fallback fields, etc.)
- `summary.json` — aggregates: total calls, success rate, avg latency and avg tokens by provider, JSON compliance rate, top 3 slowest and top 3 highest-token calls
- `summary.md` — human-readable report

**Note:** Request parameters (e.g. `temperature`, `max_output_tokens`) may not be supported by every provider; failures are recorded in `results.jsonl` and the run continues.

### Format repair & fallback (Milestone 3)

For prompts that expect JSON (`expect.format == "json"`), the runner behaves like a production LLM pipeline:

1. **Repair** — If the model returns invalid JSON, the same provider/model is re-called with a strict repair prompt that includes the invalid output (truncated to 800 chars). This is repeated up to 2 times (configurable via `REPAIR_ATTEMPTS` in `.env`).
2. **Fallback** — If JSON is still invalid after repairs, the runner calls the other provider once (OpenAI ↔ Anthropic) with the original prompt and `temperature=0`. If that returns valid JSON, it is treated as the final output for that slot.

Every attempt (primary, repair, fallback) is logged in `results.jsonl` with `attempt_type`, `parent_response_id`, `repair_attempt`, `fallback_provider`, and `final_for_case`. Exactly one record per (provider, temperature, prompt_id) slot is marked `final_for_case=true`. The summary reports JSON repair success rate, fallback usage, and final JSON compliance rate. This mirrors production patterns: validate output, repair with same model, then fail over to another model when needed.

Optional env (no CLI flags): `REPAIR_ATTEMPTS` (default `2`), `ENABLE_FALLBACK` (default `true`).

### Judge scoring (optional)

When `ENABLE_JUDGE=true`, the runner runs a separate judge model on each slot’s **final** output (one judge call per provider × temp × prompt_id). The judge scores instruction_following, format_compliance, conciseness, and grounding (0–5) and optional notes; results are stored as extra records with `attempt_type="judge"` and linked via `parent_response_id`. Summary reports average scores by provider and by temperature.

- **ENABLE_JUDGE** — set to `true` to enable (default: `false`).
- **JUDGE_MODEL** — model used for judging (default: `openai/gpt-5.2`).
- **JUDGE_TEMPERATURE** — temperature for judge calls (default: `0`).

Example: `ENABLE_JUDGE=true python scripts/run_experiments.py --suite prompts/suite_basic.jsonl --limit 3`

### Long-document benchmark suite

The `suite_longdocs.jsonl` suite is **generated** (not hand-written) to create token-heavy prompts. Each synthetic document is a meeting transcript, incident report, or policy memo with 12–18 sections; each document gets 3 cases: summary (text), structured extraction (json), and QA (json). The full document is embedded in each prompt so API calls use many input tokens.

**Generate the suite** (stdlib only, deterministic with `--seed`):

```bash
python scripts/generate_longdocs_suite.py --docs 25 --sections 18 --seed 42 --out prompts/suite_longdocs.jsonl
```

Then run experiments as usual, e.g. `--suite prompts/suite_longdocs.jsonl` (consider `--limit` for a quick test).

**Long-doc QA grounding (heuristic):** For prompt cases whose id ends with `_qa` (e.g. longdoc QA), the runner computes a simple grounding metric on the final JSON output: each answer is classified as SUPPORTED (answer substring appears in the document), UNKNOWN (answer is “unknown”), or HALLUCINATED. The summary reports average supported_rate and hallucinated_rate by provider and by temperature. This is a heuristic only—it detects obvious hallucinations (answers not present in the doc) and does not assess correctness or paraphrasing. Parsing or document extraction failures leave the metric null; the run does not crash.

## Project layout

- `src/concentrate_client.py` — `ConcentrateClient` for `POST /v1/responses`
- `src/response_parsing.py` — helpers to extract `output_text` and `usage` from responses
- `src/experiment_types.py` — `PromptCase`, `ResultRecord` types
- `src/experiment_runner.py` — grid runner with retries and JSONL logging
- `src/reporting.py` — summary.json and summary.md generation
- `scripts/smoke_test.py` — smoke test for both models
- `scripts/run_experiments.py` — experiment runner CLI
- `scripts/generate_longdocs_suite.py` — generates `prompts/suite_longdocs.jsonl` (long-doc benchmark)
- `prompts/` — prompt suites (JSONL); committed. Output goes to `runs/` (gitignored).
