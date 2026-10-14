# Loop Constraints — XAU_SCALP5

> Add rules below with `/constraints <rule>` in your agent.
> The `loop-constraints` skill reads this file at the start of every run.
> Constraints here are **binding** — the agent MUST follow them.

## Push & Merge

- Don't push before telling me
- Never auto-merge to main without human approval
- Always create a draft PR first; let me review before marking ready
- L1 loops: NO code changes, report only

## Paths — Trading Bot Specific

- **NEVER** edit `.env`, `.env.*`, `.metaapi/`, `auth/`, `payments/`, `secrets/`, `credentials/`
- **NEVER** edit `src/config.py` (trading params) without explicit human approval
- **NEVER** edit `src/scalp_strategy.py` (core logic) without L2+ verifier + human approval
- **NEVER** edit `src/scalp_executor.py` (order execution) without L2+ verifier + human approval
- **NEVER** edit `src/metaapi_client.py` (broker connection) — hard denylist
- **NEVER** edit `data/scalp5.db` (live telemetry) — read only
- **NEVER** edit `logs/scalp5.status.json`, `logs/scalp5.pid` — read only
- Infrastructure configs (VPS, systemd, cron) require human approval

## Code Changes

- Always run tests before proposing a fix: `python test_offline.py` or `python test_s2.py`
- Never disable tests to make CI green
- Never refactor unrelated code — one fix per run
- Max 3 fix attempts per item; escalate after
- Enforce attempt limit: log each try to `loop-run-log.md` and run `loop-context --check` before retrying
- For trading logic changes: must backtest with `_replay_*.py` before proposing

## Communication

- Always tell me what you're about to do before doing it
- Never close an issue or PR without my approval
- Reference the specific block (1-7) from CHECKLIST_VERIFY.md when reporting issues
- Include concrete evidence from `scalp5_verify_report.json` (ts, px, drift, PnL, win_rate, etc.)

## Budget

- If token spend hits 80% of daily cap (50k for Daily Triage), switch to report-only
- If `loop-pause-all` is active, exit immediately
- Scalp5 Verify loop uses 0 tokens (pure Python) — no budget limit

## Trading-Specific Constraints

- Do not suggest strategy parameter changes (MOM_PUB_PTS, FZ_MIN_TOUCH, K_CONTEXT, DAILY_LOSS_STOP) without:
  1. Backtest evidence from `_replay_*.py`
  2. Clear 5 Whys analysis from CHECKLIST_VERIFY.md
  3. Human approval
- Do not suggest position sizing changes without risk analysis
- Do not suggest new instruments/symbols without full config review
- When reporting High Priority: always include financial impact estimate ($)

## Verification Loop Constraints (Scalp5 Verify)

- Runs every 5 minutes via cron/nohup — do not modify schedule without human approval
- Reads: `logs/scalp5.status.json`, `data/scalp5.db`, `logs/scalp5.log`, `logs/scalp5.pid`
- Writes: `logs/scalp5_verify_report.json`, `logs/scalp5_verify.log`, appends to `STATE.md`
- Exit codes: 0=PASS, 1=WARN (Telegram notify), 2=FAIL (Telegram alert + High Priority in STATE.md)
- Does NOT use LLM — pure Python empirical checks

## Daily Triage Loop Constraints

- Runs 1-2x per day (morning + optional mid-day)
- Reads: `STATE.md`, `scalp5_verify_report.json` (last 24h), GitHub issues/PRs (if any)
- Writes: Updates `STATE.md` High Priority, Watch List, State Updates
- L1: Report only — no code edits, no PRs
- L2+: Only for items explicitly approved by human in STATE.md

---

<!-- Add your own rules below. Use plain English. The loop reads this verbatim. -->