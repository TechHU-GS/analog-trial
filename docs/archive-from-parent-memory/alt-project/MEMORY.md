# Project Discipline (cc-discipline framework)

This project has cc-discipline installed. Note the following at the start of each new conversation.

## Three Lines of Defense
1. **Rules** (`.claude/rules/`) — Auto-injected by file path; editing source code triggers checklists
2. **Hooks** (`.claude/hooks/`) — Run automatically before/after edits; can block operations (exit 2)
3. **Agents** (`.claude/agents/`) — Reviewer audits proposals; investigator performs isolated research

## Hook Behavior
- `pre-edit-guard.sh` — **Blocks source code edits** when there are unverified hypotheses; update docs/debug-log.md first
- `streak-breaker.sh` — Warns at >=3 edits to the same file, **hard stop** at >=5
- `post-error-remind.sh` — Injects debugging process reminder when errors are detected (via exit 2 feedback)

## Key Files
- `docs/progress.md` — Progress log, updated at each milestone; first thing to read after compact
- `docs/debug-log.md` — Debug log, hypotheses marked "pending"/"confirmed"; affects pre-edit-guard

## Core Discipline
- Understand before acting; don't lock onto first explanation (>=2 alternative hypotheses)
- 3 consecutive failures → stop and report
- Don't mole-whack — repeated edits to the same file means root cause not found
- Four debugging phases: gather → hypothesize → verify → fix; no skipping steps
