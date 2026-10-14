# Loop Budget — XAU_SCALP5

> Primary loop: **Daily Triage** (scaffolded by loop-init)
> Secondary loop: **Scalp5 Verify** (5-min health check, runs via cron/nohup)

## Daily limits

| Loop | Max runs/day | Max tokens/day | Max sub-agent spawns/run |
|------|--------------|----------------|--------------------------|
| Daily Triage | 2 | 50k | 0 (L1) / 2 (L2) |
| Scalp5 Verify | 288 (5min) | 10k | 0 (pure verify, no LLM) |

## On budget exceed

1. Pause schedulers (`scheduler_delete` or disable automations)
2. Append event to `loop-run-log.md`
3. Notify human (Telegram / STATE.md High Priority)

## Kill switch

- Command or issue label: `loop-pause-all`
- Resume only after human clears the flag in STATE.md

## Estimate spend

```bash
npx @cobusgreyling/loop-cost --pattern daily-triage
```

## Scalp5 Verify (non-LLM, runs every 5 min)

- Runs: `python scalp5_verify.py --once` (cron) or `--loop` (nohup)
- Tokens: 0 (pure Python, reads JSON/SQLite/log files)
- Output: `logs/scalp5_verify_report.json` + exit code (0=PASS, 1=WARN, 2=FAIL)
- Alert: Telegram on WARN/FAIL (see `src/telegram.py`)