# Codex agents — V2 promotions

The project keeps 2 custom Codex agents and 3 skills:

| Role | Config | Skill |
|---|---|---|
| Developer | `.codex/agents/promotion-dev.toml` | `$add-promotion-source` |
| Independent QA | `.codex/agents/promotion-qa.toml` | `$validate-promotion-source` |
| Coordinator (root thread) | `.codex/config.toml` + root `AGENTS.md` | `$integrate-promotion-source` |

## Important fixes since v4

1. **Remove `sandbox_mode = "read-only"` from custom QA agent TOML.** Official Codex custom-agent configuration inherits parent permissions and does not allow agent-specific sandbox override. The previous field gave misleading safety assurances. QA is instructed not to write; enforce *technical* read-only in a separate environment if needed.
2. **Agent role is not a model.** An attempted `create_session(model="promotion_dev")` previously failed. Delegate using the client-specific subagent/role mechanism, not a model string. Report any fallback to a generic separate session honestly.
3. V2 now uses `benefits`, `limits`, full payment alternatives, nullable validity, merchant-verification flag, and `specific_conditions`. All types of benefits are eligible, including fee waivers, crypto cashback and free services.
4. Independent QA checks all small-catalog items, exact bytes/codepoints before claiming UTF-8 corruption, and rejects substring day matching (`"sab"` within `responsabilidad`). Failures in browser/SSL/network are not automatically code defects.
5. Distinguish `ScrapeResult.complete` from normalization completeness and safe Supabase deactivation. No reference/golden test system is being introduced.

## Usage

Start a **new Codex session from repository root** after installing/updating the files:

> Use `$integrate-promotion-source` to add **Buepp**. Determine the official promotion catalogue, delegate to `promotion_dev`, then to a fresh `promotion_qa`. On FAIL, return numbered findings to Dev and re-audit, up to 3 QA audits. Use V2; do not sync to Supabase, edit GitHub Actions or deploy.

To work only on implementation use `$add-promotion-source`, or QA alone in a new session use `$validate-promotion-source`.

## Installation

- Extract the kit **at the repository root**, replacing the matching files. Keep old code, tests and user edits unchanged.
- If `.codex/config.toml` already contains additional project settings, **merge the `[agents]` table** rather than overwrite it.
- See `INSTALL.md` in the kit root for complete replacement/removal instructions.
- Codex reads repository-local skills in `.agents/skills/`; restart if updated skills do not appear.
- The skill cannot guarantee that every client/version supports custom-agent delegation. Require real tool/session evidence of the handoff.

This is instruction-driven coordination and **does not itself enforce a deterministic workflow or production deployment**.
