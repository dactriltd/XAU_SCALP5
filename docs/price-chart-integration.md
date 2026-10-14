# Price Chart Integration with Loop-Engineering

## Overview

This document describes how the XAU_SCALP5 price chart verification integrates with the loop-engineering framework to provide automated price structure analysis alongside the existing 7-block verification system.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    LOOP-ENGINEERING FRAMEWORK                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐     ┌──────────────────┐                │
│  │  DAILY TRIAGE    │     │  SCALP5 VERIFY   │                │
│  │  (1d, LLM)       │     │  (5min, 0-token) │                │
│  │                  │     │                  │                │
│  │  • loop-triage   │     │  • 7-block check │                │
│  │  • price-chart   │◄────┤  • System health │                │
│  │    verify        │     │  • Trade quality │                │
│  └────────┬─────────┘     └────────┬─────────┘                │
│           │                        │                           │
│           ▼                        ▼                           │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                    STATE.md                               │  │
│  │  • High Priority (chart + 7-block findings)              │  │
│  │  • Watch List (S/R levels, swing reactions)              │  │
│  │  • Recent Noise (passed checks)                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Price Chart Generator (`src/price_chart.py`)

Builds 5-minute bucket charts from 1-minute candles:
- Fractal swing detection (±2 buckets)
- Support/Resistance level clustering
- Entry/Exit mapping on chart
- ASCII chart + data table output

### 2. Price Chart Verification (`src/price_chart_verify.py`)

Extends the 7-block framework with 3 new blocks:
- **Block 8**: Price Structure Analysis (S/R proximity, swing clarity)
- **Block 9**: Swing Reaction Timing (confirmation speed, broken levels)
- **Block 10**: Entry Quality vs Structure (pullback vs chase, S/R awareness)

Outputs JSON report for loop-engineering consumption.

### 3. Skills

- `skills/price-chart-verify/SKILL.md` — LLM skill for daily triage
- `skills/loop-triage/SKILL.md` — Updated to read price chart reports

## Automated Execution

### Daily Triage (Morning)

```bash
# Runs as part of daily triage loop
opencode run "Run loop-triage. Read price_chart_report.json and scalp5_verify_report.json. Update STATE.md." --agent loop-triage
```

### Scalp5 Verify (Every 5 min)

```bash
# Lightweight check only - full chart analysis on demand
# Cron entry:
*/5 * * * * cd /path/XAU_SCALP5 && ./.venv/bin/python scalp5_verify.py --once
```

### Price Chart Verification (On-demand / Daily)

```bash
# Full chart analysis (run daily or when needed)
./.venv/bin/python -m src.price_chart_verify --hours 4 --bucket 5m --save-chart --update-state
```

## Cron Setup

Add to crontab (`crontab -e`):

```bash
# Scalp5 Verify - every 5 minutes (system health + trade quality)
*/5 * * * * cd /Users/admin/Desktop/DESIGN/XAU_SCALP5 && ./.venv/bin/python scalp5_verify.py --once >> logs/verify5_cron.log 2>&1

# Price Chart Verification - daily at 04:00 UTC (after session)
0 4 * * * cd /Users/admin/Desktop/DESIGN/XAU_SCALP5 && ./.venv/bin/python -m src.price_chart_verify --hours 8 --bucket 5m --save-chart --update-state >> logs/price_chart_cron.log 2>&1

# Daily Triage - morning at 07:30 UTC
30 7 * * * cd /Users/admin/Desktop/DESIGN/XAU_SCALP5 && opencode run "Run loop-triage" --agent loop-triage >> logs/daily_triage_cron.log 2>&1
```

## Verification Flow

### 1. Price Chart Analysis (Blocks 8-10)

```
Input: 1m candles → 5m buckets → swings → S/R levels → entries/exits
         │
         ▼
┌─────────────────────────────────────────────┐
│ Block 8: Price Structure                    │
│ - Current price vs strong unbroken S/R      │
│ - Swing structure clarity                   │
│ - Session range analysis                    │
└─────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│ Block 9: Swing Reaction Timing              │
│ - Confirmed swings bounce within 5 buckets  │
│ - Broken strong levels = invalidated        │
│ - Unconfirmed swings after 5 buckets = WARN │
└─────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│ Block 10: Entry Quality vs Structure        │
│ - Pullback entries (≥1.5 pts from swing)    │
│ - Chase entries (<0.8 pts from swing)       │
│ - Entries at strong S/R (±0.5 pts) = POOR   │
└─────────────────────────────────────────────┘
```

### 2. Cross-Reference with 7-Block System

| 7-Block (scalp5_verify) | Price Chart (price_chart_verify) | Combined Insight |
|-------------------------|----------------------------------|------------------|
| Block 1: Tick Stream | — | System alive |
| Block 2: Strategy State | Block 8: Price Structure | Drift vs swing structure |
| Block 3: Positions | Block 10: Entry Quality | Open positions at good/bad levels |
| Block 4: Telemetry | Block 10: Entry Analysis | PnL vs structural entry quality |
| Block 5: Supervisor | Block 9: Swing Reaction | Bot stability vs level validity |
| Block 6: Entry Quality | Block 10: Structural Entry Quality | Win rate vs structure adherence |
| Block 7: Structure Resistance | Block 8/9: S/R + Swing Reaction | Unified structure view |

### 3. STATE.md Updates

Both loops append to the same `STATE.md`:

```markdown
## High Priority
- [Block 3] n_open=4 (K=4) — FAIL
- [Block 10] ENTRY_LONG at 4163.35 at strong RESISTANCE 4163.21 (5 touches) — FAIL

## Watch List
- [Block 9] Strong swing HIGH 4166.14 @ 01:30 unconfirmed after 5 buckets — WARN
- [Block 7] Price at RESISTANCE zone (±0.5 pts of 4165.30) — WARN
- Strong RESISTANCE at 4163.21 (5 touches, last test 02:10)

## Recent Noise
- [Block 8] Price structure clear — PASS
- [Block 1] Tick age=12s — PASS
```

## User Scenario: 01:35→02:30 Analysis

User's example: Price 4159 → bottom 4157.6 (01:35-39) → bounce to 4166 (02:25-30)

**Automated Verification:**

```json
{
  "swing_low": {"time": "01:35", "price": 4157.6, "confirmed": true, "bounce": 8.5},
  "swing_high": {"time": "02:25", "price": 4166.1, "confirmed": true, "tested_resistance": 4165.30},
  "reaction_time_at_resistance": "3 buckets (15 min) before drop",
  "drop_from_resistance": "4166.1 → 4163.5 = 2.6 pts",
  "short_signal_triggered": "ENTRY_SHORT at 4163.01 (at resistance)"
}
```

**Verification Questions Answered:**

1. **Was 4157.6 a confirmed swing LOW?** → Yes, fractal detected at 01:35, bounce 8.5 pts within 5 buckets ✓
2. **Did price bounce ≥$2.5?** → Yes, 8.5 pts bounce ✓
3. **Was 4166 a swing HIGH?** → Yes, fractal at 02:25 ✓
4. **Near previous unbroken resistance?** → Yes, 4165.30 (14 touches, unbroken) — price tested at 4166.1
5. **Reaction time at 4166?** → 3 buckets (15 min) at resistance before drop
6. **Drop 2.5 pts → SHORT entry?** → Yes, SHORT entries at 4163.01, 4163.33 (at resistance)

## Configuration

Thresholds from `src/config.py`:

```python
S_CONFIRM_BOUNCE = 2.5      # Bounce confirmation threshold
S_CONFIRM_MINS = 5          # Time confirmation (5 buckets for M5)
S_MERGE = 5.0               # Level merge threshold
FZ_MIN_TOUCH = 2            # Strong level = ≥2 touches
FZ_BAND_PTS = 0.5           # "At level" band
MOM_PUB_PTS = 0.8           # Pullback entry offset
```

## Loop-Engineering Compliance

| Check | Status |
|-------|--------|
| loop-audit score | 100/100 L3 |
| loop-sync | 100/100 healthy |
| loop-doctor | HEALTHY |
| Skills registered | loop-triage, loop-verifier, loop-constraints, price-chart-verify |
| Safety doc | docs/safety.md |
| Constraints | loop-constraints.md |
| Budget | loop-budget.md |
| Run log | loop-run-log.md |

## Next Steps

1. **Add GitHub Actions workflows** for automated daily triage
2. **Create gate.yaml** for explicit human approval gates
3. **Add patterns/registry.yaml** for custom pattern registration
4. **Integrate with harness-foundry** for versioned loop stacks
5. **Add memory tiers** for long-term pattern learning

## Files Summary

```
XAU_SCALP5/
├── src/
│   ├── price_chart.py           # Chart generator
│   └── price_chart_verify.py    # Verification + JSON report
├── skills/
│   ├── price-chart-verify/
│   │   └── SKILL.md             # LLM skill for daily triage
│   ├── loop-triage/
│   │   └── SKILL.md             # Updated to read chart reports
│   ├── loop-constraints/
│   ├── loop-budget/
│   └── loop-verifier/
├── docs/
│   ├── safety.md                # Trading-specific denylist
│   └── price-chart-integration.md  # This file
├── LOOP.md                      # Loop configuration
├── STATE.md                     # Shared state (updated by both loops)
├── loop-constraints.md          # Binding constraints
├── loop-budget.md               # Token budgets
└── loop-run-log.md              # Audit trail
```