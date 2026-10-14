---
name: price-chart-verify
description: >
  Runs 5-minute bucket price chart analysis with swing detection, S/R levels,
  and entry/exit mapping. Generates ASCII charts and data tables for loop-engineering
  verification. Validates price action against trading strategy rules.
user_invocable: true
---

# Price Chart Verification Skill

This skill runs empirical price chart analysis for XAU_SCALP5 using 5-minute buckets
from 1-minute candle data. It detects fractal swing points, clusters them into
support/resistance levels, maps entries/exits, and generates verification reports.

## Inputs

- `data/scalp5.db` — 1m candles, entry_log, exit_log
- `src/price_chart.py` — chart generation module
- `CHECKLIST_VERIFY.md` — 7-block verification framework

## Outputs

- `logs/price_chart_latest.txt` — ASCII chart + data table
- `logs/price_chart_report.json` — structured JSON for loop-engineering
- Updates `STATE.md` with chart-based observations

## Execution

```bash
cd /path/to/XAU_SCALP5
./.venv/bin/python -m src.price_chart --hours 4 --bucket 5m --save logs/price_chart_latest.txt
```

## Price Chart Verification Checks (extends 7-block framework)

### Block 8: PRICE STRUCTURE ANALYSIS (NEW)

**What**: 5-minute bucket chart structure — swing highs/lows, S/R levels, price position relative to key levels

**Why**: Price structure determines entry quality (MOM1 pullback vs chase), exit timing (TP at resistance, SL at support), and risk (near unbroken swing high/low)

**How**: Run `price_chart.py` → parse swings, S/R levels, current price position

**How Much**: 
- PASS: Current price not at strong unbroken S/R, clear swing structure
- WARN: Price within 1.0 pts of strong unbroken resistance/support
- FAIL: Price at strong unbroken level with >3 touches, no bounce confirmation

### Block 9: SWING REACTION TIMING (NEW)

**What**: Time price spends at swing high/low before bouncing or breaking

**Why**: Reaction time indicates strength of level. Fast bounce (< 3 buckets = 15 min) = strong level. Slow reaction or break = weak level.

**How**: For each confirmed swing, measure buckets until price moves > 2.5 pts away (S_CONFIRM_BOUNCE)

**How Much**:
- PASS: Swing confirmed with bounce within 3 buckets (15 min)
- WARN: Swing unconfirmed after 5 buckets (25 min) — level weakening
- FAIL: Swing broken after test — level invalidated

### Block 10: ENTRY QUALITY VS STRUCTURE (NEW)

**What**: Entry price relative to swing structure and S/R levels

**Why**: MOM1 PULLBACK entries should be at dip from swing high (SHORT) or bounce from swing low (LONG). Entries chasing momentum into unbroken resistance/support = low quality.

**How**: For each entry, check:
- Distance to nearest swing high/low
- Whether entry is WITH or AGAINST local structure
- S/R level proximity (±1.0 pts = "at level")

**How Much**:
- PASS: Entry at pullback from swing (≥ 1.5 pts from extreme), against-drift
- WARN: Entry within 1.0 pts of unbroken S/R level
- FAIL: Entry chasing momentum into strong unbroken resistance/support

## Verification Logic

### Swing Detection (Fractal ±2 buckets)
- Swing HIGH: bucket.high > high of 2 buckets before AND after
- Swing LOW: bucket.low < low of 2 buckets before AND after
- Confirmed if price bounces ≥ $2.5 (S_CONFIRM_BOUNCE) within 5 buckets (S_CONFIRM_MINS)

### Support/Resistance Clustering
- Merge swings within $5.0 (S_MERGE)
- Strong level = touches ≥ 2 (FZ_MIN_TOUCH)
- Track first/last test timestamps

### Price Action Patterns to Verify

| Pattern | Description | Expected Behavior |
|---------|-------------|-------------------|
| **Pullback Entry** | Price retraces 1.5+ pts from swing extreme | HIGH quality entry |
| **Chase Entry** | Entry within 0.5 pts of swing extreme | LOW quality entry |
| **S/R Test** | Price touches strong level (±0.5 pts) | Watch for bounce/break |
| **S/R Break** | Price closes > 1.0 pts beyond strong level | Level invalidated, trend continuation |
| **Failed Bounce** | Price tests level 3+ times without 2.5 pts bounce | Level weakening |

## State Updates (append to STATE.md)

### High Priority
- `[Block 8] Price at strong unbroken RESISTANCE 4165.30 (14 touches) — distance 0.3 pts — FAIL`
- `[Block 9] Swing HIGH 4166.14 @ 01:30 unconfirmed after 5 buckets — WARN`
- `[Block 10] ENTRY_LONG at 4165.99 chasing momentum into resistance — FAIL`

### Watch List
- `[Block 8] Price approaching SUPPORT 4158.71 (16 touches) — distance 1.2 pts`
- `[Block 9] Swing LOW 4144.25 @ 01:45 confirmed with bounce — PASS`

### Recent Noise
- `[Block 8] Swing structure clear, no immediate S/R conflict`

## Integration with Loop-Engineering

### Daily Triage Loop
- Runs price-chart-verify as part of morning triage
- Reads `logs/price_chart_report.json`
- Cross-references with `scalp5_verify_report.json` (7-block system)
- Adds structure-based findings to STATE.md

### Scalp5 Verify Loop (5-min)
- Lightweight check: current price vs last known S/R levels
- Only runs full chart analysis on demand (not every 5 min)

### Verification Report JSON Format

```json
{
  "ts": 1791908508,
  "chart_period": "2026-10-13 19:20 → 2026-10-14 03:15",
  "price_range": {"low": 4144.25, "high": 4169.74, "range": 25.49},
  "swings": [
    {"ts": "01:30", "type": "HIGH", "price": 4166.14, "confirmed": true, "broken": false, "touches": 0},
    {"ts": "01:45", "type": "LOW", "price": 4144.25, "confirmed": true, "broken": false, "touches": 0}
  ],
  "sr_levels": [
    {"price": 4165.30, "type": "RESISTANCE", "touches": 14, "strong": true, "distance_from_current": -0.3},
    {"price": 4158.71, "type": "SUPPORT", "touches": 16, "strong": true, "distance_from_current": 1.2}
  ],
  "current_price": 4165.0,
  "blocks": {
    "8_PRICE_STRUCTURE": {"status": "FAIL", "details": "Price at strong unbroken resistance"},
    "9_SWING_REACTION": {"status": "WARN", "details": "Recent swing unconfirmed"},
    "10_ENTRY_QUALITY": {"status": "PASS", "details": "Recent entries at pullbacks"}
  }
}
```

## Example User Scenario Analysis

User's example: `01:35→02:30` — Price from 4159 → bottom 4157.6 (01:35-39) → bounce to 4166 (02:25-30)

**Verification Questions:**
1. Was 4157.6 a confirmed swing LOW? → Check fractal detection at 01:35 bucket
2. Did price bounce ≥ $2.5 from 4157.6 within 5 buckets? → 4166.1 - 4157.6 = 8.5 pts ✓
3. Was 4166.1 a swing HIGH? → Check fractal at 02:25-30
4. Is 4166 near previous unbroken resistance? → Check S/R level at 4165.30 (14 touches)
5. Reaction time at 4166? → How many buckets at resistance before drop?
6. If drop 2.5 pts from 4166 → 4163.5, was there SHORT entry? → Check entries near 4163-4164

**Automated Answers from Chart:**
- Swing LOW 4144.25 @ 01:45 confirmed (bounce to 4155+ within 5 buckets)
- Swing HIGH 4166.14 @ 01:30 confirmed (later tested at 03:00)
- Strong RESISTANCE 4165.30 (14 touches, unbroken) — price at 4166.1 tested it
- Entries at 02:30-03:10: mostly LONG chasing into resistance → LOW quality

## Safety

- Read-only: only reads DB, writes to logs/ and STATE.md
- No trading decisions — analysis only
- Integrates with loop-constraints.md denylist

## Configuration

Thresholds from `src/config.py`:
- `S_CONFIRM_BOUNCE = 2.5` — bounce confirmation threshold
- `S_CONFIRM_MINS = 5` — time confirmation (5 min for M5, 1 min for M1)
- `S_MERGE = 5.0` — level merge threshold
- `FZ_MIN_TOUCH = 2` — strong level threshold
- `FZ_BAND_PTS = 0.5` — "at level" band
- `MOM_PUB_PTS = 0.8` — pullback entry offset