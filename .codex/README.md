# Codex Dev → QA multi-agent workflow

This repository uses project-scoped Codex subagents:

- `.codex/agents/promotion-dev.toml` — implement and fix a promotion source.
- `.codex/agents/promotion-qa.toml` — independent **read-only** review and issue report.
- `.agents/skills/integrate-promotion-source/SKILL.md` — orchestration, handoffs and maximum three QA audits.
- The existing `$add-promotion-source` and `$validate-promotion-source` skills remain available independently.

## Start in Codex (repository root)

Request: `Use $integrate-promotion-source to add <bank or wallet>. Official URL: <URL>. Delegate to promotion_dev and promotion_qa. Do not sync to Supabase or edit GitHub Actions.`

The coordinator waits for Dev, delegates fresh QA, sends any findings back to Dev, and asks fresh QA to review the fixes. It stops after QA passes, is blocked, or fails for the third time. **There is no automated deployment.**

## Notes

- Project `.codex/` configuration loads for **trusted projects** in Codex. Restart/open a new Codex session after installing the files.
- Multi-agent tools need to be available in the chosen Codex client; the skill cannot force unavailable delegation. If unavailable, use the two original skills in separate sessions and request manual QA.
- A read-only QA may be unable to run pytest if it tries to write cache, bytecode or temporary files. QA should report the environment limitation and the developer can run the tests; test results alone never justify PASS.
- `.codex/config.toml` uses only the `[agents]` table. If the repo already has `.codex/config.toml`, **merge** this table rather than overwriting your existing settings.
- Do not use elevated unrestricted sandbox/approval overrides, which may supersede the QA agent's read-only default.
- This is prompt-driven orchestration, not a deterministic Python state machine; review the subagent history and final verdict before accepting changes.
