# Loop Configuration — XAU_SCALP5

## Active Loops

| Pattern | Cadence | Status | Command |
|---------|---------|--------|---------|
| Daily Triage | 1d (morning) | L1 report-only | `opencode run "Run loop-triage" --agent loop-triage` |
| Scalp5 Verify | 5 min | L1 automated | `python scalp5_verify.py --once` (cron) or `--loop` (nohup) |

## State Management

- **state: STATE.md** (updated every loop run by both loops)
- **Verification reports**: `logs/scalp5_verify_report.json` (every 5 min, read by Daily Triage)
- **Audit trail**: `loop-run-log.md` (appended each run)
- **State sections** (mirrored in `STATE.md`):
  - `Last run` — timestamp of last loop execution
  - `High Priority` — items requiring action or human decision
  - `Watch List` — items to monitor, not yet actionable
  - `Recent Noise` — items evaluated and dismissed
  - `Run log` — brief summary of what the loop did

## High Priority (loop is acting or waiting on human)

*Managed by both loops — see `STATE.md` for current items*

## Watch List

*Managed by both loops — see `STATE.md` for current items*

## Recent Noise (ignored this run)

*Managed by both loops — see `STATE.md` for current items*

### Human Gates

- No auto-fix until L2 checklist complete (see docs/loop-design-checklist.md from loop-engineering)
- All high-risk paths require human review (see docs/safety.md denylist)
- Trading parameter changes (config.py) require backtest + human approval

### Worktrees

- Use an explicit `git worktree` and run opencode with `--dir <worktree>` for implementer runs (L2+)
- One worktree per fix attempt; discard after verifier REJECT
- Worktree naming: `fix/<issue>-<timestamp>`

### Connectors (MCP)

- MCP optional for L1 report-only loops
- For L2+: GitHub MCP can read CI/issues; scope connectors to read + comment until trusted
- No MCP for Scalp5 Verify (pure Python, no LLM)

### Budget & Observability

- Token caps: `loop-budget.md`
- Run history: `loop-run-log.md` (appended each run)
- Estimate: `npx @cobusgreyling/loop-cost --pattern daily-triage`
- Kill switch: `loop-pause-all` label or flag in `STATE.md`

### Safety & Gates (this repo)

- No auto-merge on main except trivial dependency patches (allowlist + verifier)
- Denylist: `.env`, `.env.*`, `.metaapi/`, `src/config.py`, `src/scalp_strategy.py`, `src/scalp_executor.py`, `src/metaapi_client.py`, `data/scalp5.db` (see `docs/safety.md`)
- Live loop state: `STATE.md` at repo root
- `loop-gate check` mechanically enforces the denylist + auto-merge allowlist from `gate.yaml`; see `tools/loop-gate`

### Verification

- **Scalp5 Verify** (5-min): Empirical 7-block check → `logs/scalp5_verify_report.json` + `STATE.md` updates
- **Daily Triage**: Reads verify reports + broader context → `STATE.md` High Priority / Watch List
- For L2+ changes: dispatch verifier sub-agent after implementation
- Run project's documented tests before proposing a fix: `python test_offline.py`, `python test_s2.py`
- Backtest trading changes with `_replay_*.py`

### Run log

*Appended to `loop-run-log.md` each run — see `STATE.md` for summary*

### Links

- Pattern: [daily-triage](../../../loop-engineering/patterns/daily-triage.md)
- Verify Framework: `CHECKLIST_VERIFY.md` (7 blocks, 5 Whys each)
- Checklist: [loop-design-checklist](../../../loop-engineering/docs/loop-design-checklist.md)
- Safety: `docs/safety.md`
- Constraints: `loop-constraints.md`
- Budget: `loop-budget.md`
- State file: `STATE.md`
- State file: `STATE.md`