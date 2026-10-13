---
name: integrate-promotion-source
description: Coordinate independent Codex promotion_dev and promotion_qa subagents for new bank/wallet source integrations with the V2 normalized model. Perform Dev → evidence-first QA → targeted fix → fresh QA, up to 3 QA audits, without production writes.
---

# Integrate promotion source — V2 orchestrator

The main Codex thread is **coordinator only**, not Dev or QA. Read `AGENTS.md` and `references/orchestration-checklist.md`. User provides a source name and optionally an official URL; identify/verify the URL before delegating if omitted. Avoid unrelated changes.

## Roles

- **`promotion_dev` custom subagent** implements the source and ordinary tests using `.agents/skills/add-promotion-source/SKILL.md`.
- **`promotion_qa` custom subagent** independently establishes source facts and audits the V2 model using `.agents/skills/validate-promotion-source/SKILL.md`, returning a numbered report. QA must never edit code.
- These are **agent roles, NOT model IDs**. Do NOT pass `"promotion_dev"` as the `model` argument to a session-creation API. Use the supported **agent-role/subagent type** mechanism in the actual client. If custom role selection is unavailable, either use truly separate sessions supplied with the relevant role instructions and disclose the fallback, or return BLOCKED; never pretend the TOML configuration was applied when it was not.
- Custom subagent config does not guarantee a distinct read-only sandbox. Avoid concurrent edits; if hard isolation matters, run QA with separate read-only filesystem permissions and disclose whether actually achieved.

## Sequence

1. **Preflight.** Inspect `git status`, live/source URL, public catalog scope and V2 `backend/normalization/models.py`, and existing Python repo integration conventions. Read no `.env` secrets. Do not sync to Supabase or modify Actions.
2. **Developer.** Delegate to `promotion_dev`; instruct use of V2 `Benefit`, `PromotionLimit`, `PaymentMethod`, grouping, nullable validity, adherent merchant link/flag, `specific_conditions`, and **all types of financial benefits**. Require scraper, normalizer, thin sync entry point (do not execute), ordinary tests, raw-to-V2 local export and evidence summary. Await completion.
3. **Independent QA #1.** Start **new context** with role `promotion_qa`; initially provide only source, official URLs/scope, instruction to inspect working tree after independently examining published facts. Do not contaminate QA by passing developer conclusions as expected results.
4. **QA decision.** On `PASS`: stop `READY_FOR_HUMAN_REVIEW`, no production approval. On `FAIL`: relay issue IDs/evidence to Dev, request fixes + ordinary regression tests, then launch fresh QA. On `BLOCKED` (e.g., live site or role inaccessible): stop with separate infrastructure/evidence note; do not ask Dev to “fix” a nonexistent code defect merely to clear blocked status.
5. **After each fix**, fresh QA assesses all previous issue IDs plus regression and whole catalog/normalization safety (not just the changed line); no developer claim alone closes QA issues.
6. **Max 3 QA audits total**, counting the initial. If third `FAIL`, stop with `NEEDS_HUMAN_REVIEW`; never simulate a fourth or automatically loosen validations. If a QA execution is genuinely blocked before review, record `BLOCKED` and stop rather than counting a pseudo-audit as a code failure.
7. **Final summary.** List Dev/QA chronology, actual role/session delegation (including fallback), changed files, test commands/results, official scope and timestamp, raw/normalized/variant counts, classified exclusions, field fidelity, **three separate gates** (`catalog_complete`, `normalization_complete`, `safe_to_deactivate`) and open QA findings. Confirm no Supabase writes / Actions changes / unauthorized commits.

## Guards and acceptance

- Ground QA in source evidence, not passing pytest or Dev-authored expectations; for a catalog of 30 or fewer entries, **check every item** and its variant.
- Respect nuanced V2 data: nullable dates, `applies_every_day`, multiple/conditional benefits, typed limits, currency, valid payment combinations, official merchant-verification links, `specific_conditions` plus `terms`.
- `ScrapeResult.complete=True` does **not** authorize desactivation by itself. Even a complete scrape can produce partial normalization or shifting variant IDs; report `safe_to_deactivate` separately and block production if uncertain.
- Tests must not depend on ignored raw data or external secrets; QA never edits files. No reference/golden test framework yet.
- A site timeout is an infrastructure observation, NOT a proven normalization bug. Do not force a PASS when no official verification was possible.
- No database operations even with `--from-file`; no migrations, workflow change, push, merge or deploy without the user's explicit approval.

## Outcomes

`READY_FOR_HUMAN_REVIEW` / `NEEDS_HUMAN_REVIEW` / `BLOCKED`. Nothing here deploys or schedules a new source automatically.
