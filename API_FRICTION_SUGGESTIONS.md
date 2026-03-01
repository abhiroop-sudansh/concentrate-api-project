# API Friction / Bugs / Doc Improvement Suggestions

Feedback from building the experiment runner and running benchmarks. Observed behavior is from dashboard + local script; suggestions are aimed at making the platform easier to integrate and debug.

---

## 1) Guardrails “Both” does not redact request payloads in Logs

**Observed:** With Redact set to **Both** (Input + Output), model **outputs** are redacted ([EMAIL], [PHONE]) but the **request body** shown in Logs still contains raw email/phone.

**Expected:** “Both” would imply both request and response are redacted (or at least not stored in full in Logs).

**Actual:** Only the response is redacted; the stored request payload in Logs remains unredacted.

**Why it matters:** Users may assume Logs are safe for PII when “Both” is on. Auditors or support could see raw PII in request bodies.

**Steps to reproduce (short):** Enable Guardrails, set Redact to Both, send a prompt containing an email and phone, check Logs: open the request detail and inspect the body.

**Suggestion:** Clarify in docs whether Logs are exempt from input redaction; add a UI note when “Both” is selected; optionally redact stored request payloads or offer a “redacted view” in Logs.

---

## 2) Provider outage surfaced as HTTP 424

**Observed:** Anthropic calls failed with **HTTP 424** and message “provider errored or was unavailable”. Seen in run_20260228T191921Z (2 of 6 calls failed, both Anthropic).

**Expected:** Either a standard availability code (e.g. 503) or a documented custom code with clear retry/failover guidance.

**Actual:** 424 with a short message; no documented semantics in the materials I had.

**Why it matters:** Clients need to know whether to retry, back off, or fail over to another provider. Without docs, we had to guess (we treated 424 like 429/5xx and retried then fallback).

**Steps to reproduce (short):** Call Anthropic repeatedly (e.g. suite_robust); 424 can appear intermittently. Check Logs for the failed request and response.

**Suggestion:** Document what 424 means (proxy vs provider, retryable or not). Consider mapping to 503 or exposing a dedicated `code` field. Add brief guidance on retry/backoff and when to fail over.

---

## 3) Parameter support / effective params unclear in Playground

**Observed:** Responses sometimes showed defaults like `max_output_tokens: 128000` and `top_p: 0.98` even when I tried to change params in the Playground.

**Expected:** UI controls (or a visible “effective request”) that reflect what’s actually sent.

**Actual:** Unclear which params are applied and how they map per provider.

**Suggestion:** Document which params are supported per provider and how they’re mapped. In Playground, show the effective request payload (or a clear note when defaults override user input).

---

## 4) Response schema differences across providers

**Observed:** OpenAI responses included fields like `top_p` / `max_output_tokens`; Anthropic responses were leaner.

**Why it matters:** Code that expects a single schema can break or need branching per provider.

**Suggestion:** Document which fields are guaranteed vs provider-specific so integrators can normalize safely.

---

## 5) Token usage / billing alignment

**Observed:** `usage` appeared consistently in responses and Billing updated per model.

**Suggestion:** Add docs on how tokens and cost are computed across providers (e.g. rounding, what counts as input vs output).

---

## 6) Output text location in response body

**Observed:** Final assistant text can live under `output[*].content[*].text` (with `type: "output_text"` or `"text"`), or top-level `output_text`, or `choices[0].message.content`, depending on provider/format.

**Why it matters:** Parsers that only check one path get empty `output_text`; we had to handle multiple shapes in the runner.

**Suggestion:** Document the canonical path(s) for “final text” and whether Concentrate normalizes to a single field.

---

## 7) No response `id` on failed calls

**Observed:** On HTTP 424 (and likely other errors), there’s no response body to parse, so `response_id` isn’t available.

**Why it matters:** Harder to correlate a failed call in Logs with a client-side record (e.g. in results.jsonl) without a server-side attempt ID.

**Suggestion:** Return a request/attempt ID in the error response body or headers for failed calls.

---

## 8) Rate limits and headers

**Observed:** 429 indicates rate limiting; unclear whether `Retry-After` or provider-specific headers are forwarded.

**Suggestion:** Document rate-limit semantics per provider and which headers (if any) clients should use for backoff.

---

## 9) Model identifier stability

**Observed:** Model IDs like `openai/gpt-5.2` and `anthropic/claude-opus-4-6` worked; unclear if they’re stable across provider version bumps.

**Suggestion:** Document model ID format and versioning (e.g. when a new minor is added, does the old ID keep working?).

---

## 10) Timeout and long-running requests

**Observed:** Long prompts or high `max_output_tokens` can approach typical HTTP timeouts.

**Suggestion:** Document recommended client timeouts and whether the API supports long-polling or streaming for very long generations.

---

## 11) Error response body shape

**Observed:** Error payloads look like `{ "error": "...", "message": "..." }`; structure may differ by status code.

**Suggestion:** Document a single error response schema (e.g. `code`, `message`, optional `details`) for all non-2xx responses.

---

## 12) Idempotency / replay for billing

**Observed:** Retries and fallback mean one logical “task” can generate multiple billable calls.

**Suggestion:** Clarify whether idempotency keys are supported and how billing treats retries vs distinct requests.

---

## 13) CORS / browser usage

**Observed:** Not tested in this exercise.

**Suggestion:** If browser clients are in scope, document CORS policy and API-key-in-header considerations.
