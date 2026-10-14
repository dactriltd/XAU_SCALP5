---
name: scalp5-verify
description: >
  Runs the 5-minute verification loop for XAU_SCALP5 trading bot.
  Executes scalp5_verify.py, interprets the 7-block report, and updates STATE.md.
  Non-LLM skill — runs as a pure Python check every 5 minutes.
user_invocable: true
---

# Scalp5 Verify Skill

This skill runs the empirical 7-block verification for the XAU_SCALP5 trading bot.
It does NOT use LLM reasoning — it executes `python scalp5_verify.py --once` and
interprets the JSON output.

## Inputs

- `logs/scalp5_verify_report.json` — output from the verify script
- `STATE.md` — current loop state
- `CHECKLIST_VERIFY.md` — 5 Whys for each block failure mode

## Execution

```bash
cd /path/to/XAU_SCALP5
./.venv/bin/python scalp5_verify.py --once
# Exit codes: 0=PASS, 1=WARN, 2=FAIL
```

## Output Interpretation

Read `logs/scalp5_verify_report.json`:

```json
{
  "ts": 1791908508,
  "overall": "PASS|WARN|FAIL",
  "n_fail": 0,
  "n_warn": 0,
  "checks": [
    {"block": "1_TICK_STREAM", "status": "PASS", "observed": "age=12s, px=4157.286", ...},
    {"block": "2_STRATEGY_STATE", "status": "WARN", "observed": "drift5m=-25.5", ...},
    ...
  ]
}
```

## State Update Rules

### If overall == "PASS"
- Append to STATE.md Recent Noise: "All 7 blocks PASS at {timestamp}"
- No High Priority or Watch items needed

### If overall == "WARN"
- For each WARN block:
  - Add to Watch List: "[Block N] {observed} — {first why from CHECKLIST_VERIFY.md}"
  - Add State Update: "Block N WARN: {detail}"

### If overall == "FAIL"
- For each FAIL block:
  - Add to High Priority: "[Block N] {observed} — ROOT: {5th why from CHECKLIST_VERIFY.md} — Action: {suggested fix}"
  - Add State Update: "Block N FAIL: {detail} — requires human intervention"
- Send Telegram alert (see `src/telegram.py`)

## Telegram Alert Format

```
🚨 SCALP5 VERIFY {FAIL|WARN}
Block: {block_name}
Observed: {observed}
Root Cause: {5th_why}
Action: {suggested_action}
Time: {timestamp}
```

## Scheduling

- **Cron (recommended):** `*/5 * * * * cd /path/XAU_SCALP5 && ./.venv/bin/python scalp5_verify.py --once`
- **Nohup:** `nohup ./.venv/bin/python scalp5_verify.py --loop >> logs/verify5.out 2>&1 &`

## Integration with loop-triage

- `scalp5-verify` runs every 5 min (automated, no LLM)
- `loop-triage` runs daily (LLM-assisted, reads verify reports + broader context)
- Both update the same `STATE.md`

## Safety

- This skill does NOT edit source code.
- It only reads files and appends to STATE.md.
- All actions require human approval (L1 report-only).