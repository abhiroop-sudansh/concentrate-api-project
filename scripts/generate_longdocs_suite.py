#!/usr/bin/env python3
"""
Generate a long-document benchmark suite: synthetic docs (meeting/incident/policy)
with 3 prompt cases per doc (summary, extraction, QA). Deterministic with --seed.
Stdlib only. Output: JSONL with unique ids, valid JSON per line.
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Document type templates
DOC_TYPES = [
    ("meeting", "Meeting Transcript", "{} — {:%B %d, %Y}"),
    ("incident", "Incident Report", "{} — Incident ID {}"),
    ("policy", "Policy Memo", "{} — Effective {:%B %d, %Y}"),
]

SECTION_HEADERS = [
    "Attendance & roll call",
    "Agenda overview",
    "Budget and resource allocation",
    "Timeline and milestones",
    "Risks and mitigation",
    "Decisions made",
    "Action items and owners",
    "Open questions",
    "Follow-up from last meeting",
    "Stakeholder feedback",
    "Technical constraints",
    "Compliance and security",
    "Scope changes",
    "Dependencies and blockers",
    "Success metrics",
    "Communication plan",
    "Next steps",
    "Appendices and references",
]

NAMES = [
    "Alex Chen", "Jordan Kim", "Sam Rivera", "Morgan Taylor", "Casey Lee",
    "Riley Walsh", "Quinn O'Brien", "Drew Patel", "Blake Foster", "Reese Hayes",
    "Jamie Liu", "Skyler Dunn", "Parker Bell", "Avery Clark", "Cameron Wright",
]

BULLET_STARTERS = [
    "The team agreed that",
    "It was noted that",
    "Action required:",
    "Decision:",
    "Risk identified:",
    "Timeline update:",
    "Budget impact:",
    "Owner assigned:",
    "Due date:",
    "Follow-up:",
    "Out of scope:",
    "Approved:",
    "Deferred to",
    "Escalated to",
    "Recommendation:",
]

MISSING_PHRASES = [
    "The exact budget figure was not disclosed in this document.",
    "Final headcount for the project is TBD.",
    "The vendor contract value is redacted.",
    "Specific date for phase 2 kickoff was not confirmed.",
    "Owner for the security review was not assigned.",
    "The incident root cause code is pending analysis.",
    "Compliance waiver expiration date is not specified here.",
]


def _make_rng(seed: int, doc_index: int) -> random.Random:
    return random.Random(seed + doc_index * 10000)


def _pick(rng: random.Random, seq: list):
    return rng.choice(seq)


def _generate_document(rng: random.Random, doc_index: int, num_sections: int) -> str:
    """Build one synthetic document (~1500–3000 tokens). Includes title, date, participants, sections, and 1–2 missing facts."""
    doc_type_key, title_tpl, date_tpl = _pick(rng, DOC_TYPES)
    if doc_type_key == "meeting":
        doc_date = datetime(2024, 1, 1) + timedelta(days=rng.randint(0, 364))
        title = title_tpl.format(_pick(rng, ["Q4 Planning", "Sprint Retrospective", "Board Sync", "Engineering All-Hands", "Product Review"]) + " Meeting", doc_date)
        date_line = date_tpl.format("Date", doc_date)
    elif doc_type_key == "incident":
        inc_id = f"INC-2024-{rng.randint(1000, 9999)}"
        title = title_tpl.format("API Outage / Service Degradation", inc_id)
        date_line = f"Report date: {datetime(2024, 2, 1) + timedelta(days=rng.randint(0, 90)):%Y-%m-%d}"
    else:
        doc_date = datetime(2024, 3, 1) + timedelta(days=rng.randint(0, 120))
        title = title_tpl.format(_pick(rng, ["Remote Work", "Data Retention", "Access Control", "Incident Response"]) + " Policy", doc_date)
        date_line = f"Effective: {doc_date:%B %d, %Y}"

    participants = rng.sample(NAMES, k=rng.randint(4, 7))
    participants_line = "Participants: " + ", ".join(participants)

    lines = [title, "", date_line, participants_line, ""]
    headers_used = rng.sample(SECTION_HEADERS, k=min(num_sections, len(SECTION_HEADERS)))
    if len(headers_used) < num_sections:
        headers_used += rng.choices(SECTION_HEADERS, k=num_sections - len(headers_used))

    for i, header in enumerate(headers_used):
        lines.append(f"## {header}")
        num_bullets = rng.randint(5, 10)
        for _ in range(num_bullets):
            starter = _pick(rng, BULLET_STARTERS)
            if "Owner" in starter or "Due" in starter:
                name = _pick(rng, NAMES)
                date_str = (datetime(2024, 4, 1) + timedelta(days=rng.randint(0, 60))).strftime("%Y-%m-%d")
                lines.append(f"  - {starter} {name}; target {date_str}. Scope and acceptance criteria to be confirmed in next sync.")
            elif "Budget" in starter or "Decision" in starter:
                pct = rng.randint(5, 25) * 5
                lines.append(f"  - {starter} allocation adjusted by {pct}%; details in appendix. Finance to confirm by end of week.")
            elif "Risk" in starter:
                sev = _pick(rng, ["low", "medium", "high"])
                lines.append(f"  - {starter} severity {sev}; mitigation in progress. Owner to update status in risk register.")
            else:
                lines.append(f"  - {starter} see section {i + 1} for details. Follow-up required with stakeholders.")
        lines.append("")

    # Insert 1–2 missing-fact phrases in random sections
    insert_pos = rng.randint(len(lines) // 3, max(len(lines) // 2, 1))
    for phrase in rng.sample(MISSING_PHRASES, k=min(2, len(MISSING_PHRASES))):
        lines.insert(insert_pos, "  - " + phrase)
        insert_pos += 1

    return "\n".join(lines)


# Prompt templates (exact text as specified)
SUMMARY_PROMPT = """Summarize the document into:
- 10 bullets
- top 5 action items (owner, due_date, action)
- top 3 risks
Keep it concise."""

EXTRACTION_PROMPT = """Return EXACT JSON and nothing else. Schema:
{
  "title": str,
  "date": str,
  "summary": [str],
  "decisions": [str],
  "action_items": [{"owner": str, "due_date": str, "action": str}],
  "risks": [{"risk": str, "severity": "low|medium|high"}],
  "open_questions": [str]
}
If a field is not present, use [] or "UNKNOWN"."""

QA_PROMPT = """Return EXACT JSON and nothing else:
{
  "questions": [{"q": str, "a": str}]
}
Ask 6 questions about specifics (numbers, dates, owners, decisions). Answer using ONLY the document; if missing, answer "UNKNOWN"."""

DOCUMENT_PREFIX = "\n\nDocument:\n\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate long-document benchmark suite (JSONL).")
    parser.add_argument("--docs", type=int, default=25, help="Number of synthetic documents")
    parser.add_argument("--sections", type=int, default=18, help="Sections per document")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for deterministic output")
    parser.add_argument("--out", type=Path, default=Path("prompts/suite_longdocs.jsonl"), help="Output JSONL path")
    args = parser.parse_args()

    if args.docs < 1 or args.sections < 1:
        print("ERROR: --docs and --sections must be >= 1", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []

    for d in range(args.docs):
        rng = _make_rng(args.seed, d)
        doc_text = _generate_document(rng, d, args.sections)
        doc_id = f"longdoc_{d+1:03d}"

        # A) summary (text)
        cases.append({
            "id": f"{doc_id}_summary",
            "category": "longdocs",
            "input": SUMMARY_PROMPT + DOCUMENT_PREFIX + doc_text,
            "expect": {"format": "text"},
        })
        # B) extraction (json)
        cases.append({
            "id": f"{doc_id}_extraction",
            "category": "longdocs",
            "input": EXTRACTION_PROMPT + DOCUMENT_PREFIX + doc_text,
            "expect": {"format": "json"},
        })
        # C) QA (json)
        cases.append({
            "id": f"{doc_id}_qa",
            "category": "longdocs",
            "input": QA_PROMPT + DOCUMENT_PREFIX + doc_text,
            "expect": {"format": "json"},
        })

    with open(args.out, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"Wrote {len(cases)} cases ({args.docs} docs × 3) to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
