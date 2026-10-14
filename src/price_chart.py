#!/usr/bin/env python3
"""
XAU_SCALP5 — Price Chart Visualization & Swing Analysis
Builds 5-minute bucket charts, detects swing points, identifies S/R levels,
marks entries/exits, and generates ASCII charts for loop-engineering verification.

Usage:
    python -m src.price_chart --hours 4 --bucket 5m
    python -m src.price_chart --session --save logs/price_chart_latest.txt
"""

import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "scalp5.db"
LOGS_DIR = BASE_DIR / "logs"

# ─────────────────────────── DATA CLASSES ───────────────────────────

@dataclass
class Candle1m:
    timestamp: int      # UTC epoch seconds
    open: float
    high: float
    low: float
    close: float

@dataclass
class Bucket5m:
    """5-minute OHLCV bucket"""
    start_ts: int       # bucket start (UTC epoch, aligned to 5-min)
    open: float
    high: float
    low: float
    close: float
    volume: int = 0     # tick count proxy
    
    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2

@dataclass
class SwingPoint:
    """Fractal swing high/low"""
    timestamp: int
    price: float
    swing_type: str     # "HIGH" or "LOW"
    strength: int       # number of confirming candles on each side
    touches: int = 0    # how many times price tested this level
    confirmed: bool = False
    broken: bool = False

@dataclass
class SRLevel:
    """Support/Resistance level from clustered swing points"""
    price: float
    level_type: str     # "RESISTANCE" (swing highs) or "SUPPORT" (swing lows)
    touches: int        # total touches across clustered swings
    first_ts: int
    last_ts: int
    strength: float     # composite score
    is_strong: bool = False  # touches >= 2

@dataclass
class ChartMark:
    """Entry/Exit mark on chart"""
    timestamp: int
    price: float
    mark_type: str      # "ENTRY_LONG", "ENTRY_SHORT", "EXIT_TP", "EXIT_TIME", "EXIT_ROL", "EXIT_SL"
    position_id: str
    pnl: float = 0.0

@dataclass
class PriceChart:
    """Complete price chart with all annotations"""
    buckets: List[Bucket5m]
    swings: List[SwingPoint]
    sr_levels: List[SRLevel]
    marks: List[ChartMark]
    session_start_ts: int
    current_ts: int

# ─────────────────────────── DATA LOADERS ───────────────────────────

def load_candles_1m(hours_back: int = 6) -> List[Candle1m]:
    """Load 1-minute candles from DB (last N hours)"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    now = int(datetime.now(timezone.utc).timestamp())
    start_ts = now - hours_back * 3600
    
    cur.execute(
        """SELECT timestamp, open, high, low, close 
           FROM candles 
           WHERE timeframe = '1m' AND timestamp >= ? 
           ORDER BY timestamp""",
        (start_ts,)
    )
    rows = cur.fetchall()
    conn.close()
    
    return [Candle1m(ts, o, h, l, c) for ts, o, h, l, c in rows]

def load_candles_1m_range(start_ts: int, end_ts: int) -> List[Candle1m]:
    """Load 1-minute candles from DB within time range"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    
    cur.execute(
        """SELECT timestamp, open, high, low, close 
           FROM candles 
           WHERE timeframe = '1m' AND timestamp >= ? AND timestamp <= ?
           ORDER BY timestamp""",
        (start_ts, end_ts)
    )
    rows = cur.fetchall()
    conn.close()
    
    return [Candle1m(ts, o, h, l, c) for ts, o, h, l, c in rows]

def load_candles_m5(hours_back: int = 6) -> List[Candle1m]:
    """Load 5-minute candles from DB (if available)"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    now = int(datetime.now(timezone.utc).timestamp())
    start_ts = now - hours_back * 3600
    
    cur.execute(
        """SELECT timestamp, open, high, low, close 
           FROM candles 
           WHERE timeframe = 'M5' AND timestamp >= ? 
           ORDER BY timestamp""",
        (start_ts,)
    )
    rows = cur.fetchall()
    conn.close()
    
    return [Candle1m(ts, o, h, l, c) for ts, o, h, l, c in rows]

def load_entries_today() -> List[ChartMark]:
    """Load today's entry logs as chart marks"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    now = int(datetime.now(timezone.utc).timestamp())
    day_start = now - (now % 86400)
    
    cur.execute(
        """SELECT ts, pos_id, kind, entry, tp, drift5m, anchor, touch 
           FROM entry_log WHERE ts >= ? ORDER BY ts""",
        (day_start,)
    )
    rows = cur.fetchall()
    conn.close()
    
    marks = []
    for ts, pos_id, kind, entry, tp, drift, anchor, touch in rows:
        mark_type = "ENTRY_LONG" if kind == "ENTER_LONG" else "ENTRY_SHORT"
        marks.append(ChartMark(ts, entry, mark_type, str(pos_id), 0.0))
    return marks

def load_entries_range(start_ts: int, end_ts: int) -> List[ChartMark]:
    """Load entry logs within time range as chart marks"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    
    cur.execute(
        """SELECT ts, pos_id, kind, entry, tp, drift5m, anchor, touch 
           FROM entry_log WHERE ts >= ? AND ts <= ? ORDER BY ts""",
        (start_ts, end_ts)
    )
    rows = cur.fetchall()
    conn.close()
    
    marks = []
    for ts, pos_id, kind, entry, tp, drift, anchor, touch in rows:
        mark_type = "ENTRY_LONG" if kind == "ENTER_LONG" else "ENTRY_SHORT"
        marks.append(ChartMark(ts, entry, mark_type, str(pos_id), 0.0))
    return marks

def load_exits_today() -> List[ChartMark]:
    """Load today's exit logs as chart marks"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    now = int(datetime.now(timezone.utc).timestamp())
    day_start = now - (now % 86400)
    
    cur.execute(
        """SELECT ts, pos_id, reason, exit_px, pnl 
           FROM exit_log WHERE ts >= ? ORDER BY ts""",
        (day_start,)
    )
    rows = cur.fetchall()
    conn.close()
    
    marks = []
    reason_map = {
        "TP": "EXIT_TP",
        "TIME": "EXIT_TIME",
        "ROL": "EXIT_ROL",
        "S_BREAK": "EXIT_SL",
        "FADE": "EXIT_FADE",
        "TRAIL": "EXIT_TRAIL"
    }
    for ts, pos_id, reason, exit_px, pnl in rows:
        mark_type = reason_map.get(reason, f"EXIT_{reason}")
        marks.append(ChartMark(ts, exit_px, mark_type, str(pos_id), pnl or 0.0))
    return marks

def load_exits_range(start_ts: int, end_ts: int) -> List[ChartMark]:
    """Load exit logs within time range as chart marks"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    
    cur.execute(
        """SELECT ts, pos_id, reason, exit_px, pnl 
           FROM exit_log WHERE ts >= ? AND ts <= ? ORDER BY ts""",
        (start_ts, end_ts)
    )
    rows = cur.fetchall()
    conn.close()
    
    marks = []
    reason_map = {
        "TP": "EXIT_TP",
        "TIME": "EXIT_TIME",
        "ROL": "EXIT_ROL",
        "S_BREAK": "EXIT_SL",
        "FADE": "EXIT_FADE",
        "TRAIL": "EXIT_TRAIL"
    }
    for ts, pos_id, reason, exit_px, pnl in rows:
        mark_type = reason_map.get(reason, f"EXIT_{reason}")
        marks.append(ChartMark(ts, exit_px, mark_type, str(pos_id), pnl or 0.0))
    return marks

def get_session_start() -> int:
    """Get current trading session start (07:30 UTC)"""
    now = datetime.now(timezone.utc)
    # Session starts at 07:30 UTC (London open approx)
    session_start = datetime(now.year, now.month, now.day, 7, 30, tzinfo=timezone.utc)
    if now < session_start:
        session_start -= timedelta(days=1)
    return int(session_start.timestamp())

def get_data_time_range() -> Tuple[int, int]:
    """Get actual time range of available 1m candle data"""
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()
    cur.execute('SELECT MIN(timestamp), MAX(timestamp) FROM candles WHERE timeframe = "1m"')
    row = cur.fetchone()
    conn.close()
    if row and row[0] and row[1]:
        return row[0], row[1]
    # Fallback: last 24 hours
    now = int(datetime.now(timezone.utc).timestamp())
    return now - 86400, now

# ─────────────────────────── BUCKET BUILDER ───────────────────────────

def align_to_bucket(ts: int, bucket_seconds: int = 300) -> int:
    """Align timestamp to bucket boundary (5 min = 300s)"""
    return (ts // bucket_seconds) * bucket_seconds

def build_5m_buckets(candles: List[Candle1m]) -> List[Bucket5m]:
    """Aggregate 1m candles into 5m buckets"""
    if not candles:
        return []
    
    buckets_dict = defaultdict(lambda: {"opens": [], "highs": [], "lows": [], "closes": [], "volumes": []})
    
    for c in candles:
        bucket_ts = align_to_bucket(c.timestamp)
        buckets_dict[bucket_ts]["opens"].append(c.open)
        buckets_dict[bucket_ts]["highs"].append(c.high)
        buckets_dict[bucket_ts]["lows"].append(c.low)
        buckets_dict[bucket_ts]["closes"].append(c.close)
        buckets_dict[bucket_ts]["volumes"].append(1)
    
    buckets = []
    for ts in sorted(buckets_dict.keys()):
        data = buckets_dict[ts]
        buckets.append(Bucket5m(
            start_ts=ts,
            open=data["opens"][0],
            high=max(data["highs"]),
            low=min(data["lows"]),
            close=data["closes"][-1],
            volume=sum(data["volumes"])
        ))
    return buckets

# ─────────────────────────── SWING DETECTION (FRACTAL) ───────────────────────────

def detect_fractal_swings(buckets: List[Bucket5m], lookback: int = 2) -> List[SwingPoint]:
    """
    Detect fractal swing highs/lows using ±N bucket confirmation.
    Swing HIGH: bucket.high > high of N buckets before AND after
    Swing LOW: bucket.low < low of N buckets before AND after
    """
    swings = []
    n = len(buckets)
    
    for i in range(lookback, n - lookback):
        current = buckets[i]
        
        # Check swing HIGH
        is_high = True
        for j in range(1, lookback + 1):
            if buckets[i - j].high >= current.high or buckets[i + j].high >= current.high:
                is_high = False
                break
        
        if is_high:
            swings.append(SwingPoint(
                timestamp=current.start_ts,
                price=current.high,
                swing_type="HIGH",
                strength=lookback
            ))
            continue  # A bucket can't be both high and low
        
        # Check swing LOW
        is_low = True
        for j in range(1, lookback + 1):
            if buckets[i - j].low <= current.low or buckets[i + j].low <= current.low:
                is_low = False
                break
        
        if is_low:
            swings.append(SwingPoint(
                timestamp=current.start_ts,
                price=current.low,
                swing_type="LOW",
                strength=lookback
            ))
    
    return swings

def confirm_swings(swings: List[SwingPoint], buckets: List[Bucket5m], 
                   bounce_threshold: float = 2.5, time_threshold: int = 5) -> List[SwingPoint]:
    """
    Confirm swings: price must bounce away by bounce_threshold OR time_threshold minutes pass without break.
    """
    # Build price timeline for checking
    price_timeline = [(b.start_ts, b.high, b.low, b.close) for b in buckets]
    
    confirmed = []
    for swing in swings:
        swing_ts = swing.timestamp
        swing_price = swing.price
        
        # Find subsequent buckets
        subsequent = [(ts, h, l, c) for ts, h, l, c in price_timeline if ts > swing_ts]
        
        if not subsequent:
            continue
        
        confirmed_flag = False
        touches = 0
        
        for ts, high, low, close in subsequent:
            if swing.swing_type == "HIGH":
                # Check if price broke above (invalidates resistance)
                if high > swing_price + 0.5:  # S_CHAIN_BREAK
                    swing.broken = True
                    break
                # Check touch (price comes back to test)
                if abs(high - swing_price) <= 0.5:  # S_TOUCH_TOL
                    touches += 1
                # Check bounce away
                if low < swing_price - bounce_threshold:
                    confirmed_flag = True
                    break
            else:  # LOW
                if low < swing_price - 0.5:
                    swing.broken = True
                    break
                if abs(low - swing_price) <= 0.5:
                    touches += 1
                if high > swing_price + bounce_threshold:
                    confirmed_flag = True
                    break
        
        # Time-based confirmation: if no break after time_threshold buckets
        if not swing.broken and not confirmed_flag:
            if len(subsequent) >= time_threshold:
                confirmed_flag = True
        
        swing.touches = touches
        swing.confirmed = confirmed_flag
        confirmed.append(swing)
    
    return confirmed

# ─────────────────────────── SUPPORT/RESISTANCE LEVELS ───────────────────────────

def cluster_swings_to_levels(swings: List[SwingPoint], merge_threshold: float = 5.0) -> List[SRLevel]:
    """Cluster nearby swing points into S/R levels"""
    if not swings:
        return []
    
    # Separate highs and lows
    highs = [s for s in swings if s.swing_type == "HIGH" and s.confirmed and not s.broken]
    lows = [s for s in swings if s.swing_type == "LOW" and s.confirmed and not s.broken]
    
    levels = []
    
    # Cluster highs -> Resistance
    for swing in highs:
        # Find existing level within merge_threshold
        found = False
        for level in levels:
            if level.level_type == "RESISTANCE" and abs(level.price - swing.price) <= merge_threshold:
                level.price = (level.price * level.touches + swing.price) / (level.touches + 1)
                level.touches += swing.touches + 1
                level.last_ts = max(level.last_ts, swing.timestamp)
                level.strength = level.touches * 1.0  # simple strength
                found = True
                break
        if not found:
            levels.append(SRLevel(
                price=swing.price,
                level_type="RESISTANCE",
                touches=swing.touches + 1,
                first_ts=swing.timestamp,
                last_ts=swing.timestamp,
                strength=swing.touches + 1,
                is_strong=(swing.touches + 1) >= 2
            ))
    
    # Cluster lows -> Support
    for swing in lows:
        found = False
        for level in levels:
            if level.level_type == "SUPPORT" and abs(level.price - swing.price) <= merge_threshold:
                level.price = (level.price * level.touches + swing.price) / (level.touches + 1)
                level.touches += swing.touches + 1
                level.last_ts = max(level.last_ts, swing.timestamp)
                level.strength = level.touches * 1.0
                found = True
                break
        if not found:
            levels.append(SRLevel(
                price=swing.price,
                level_type="SUPPORT",
                touches=swing.touches + 1,
                first_ts=swing.timestamp,
                last_ts=swing.timestamp,
                strength=swing.touches + 1,
                is_strong=(swing.touches + 1) >= 2
            ))
    
    return sorted(levels, key=lambda x: x.price)

# ─────────────────────────── ASCII CHART GENERATOR ───────────────────────────

def generate_ascii_chart(chart: PriceChart, width: int = 80, height: int = 20) -> str:
    """Generate ASCII price chart with annotations"""
    if not chart.buckets:
        return "No data available"
    
    # Price range
    all_prices = []
    for b in chart.buckets:
        all_prices.extend([b.high, b.low])
    for m in chart.marks:
        all_prices.append(m.price)
    for l in chart.sr_levels:
        all_prices.append(l.price)
    
    price_min = min(all_prices)
    price_max = max(all_prices)
    price_range = price_max - price_min
    if price_range == 0:
        price_range = 1.0
    
    # Add padding
    price_min -= price_range * 0.05
    price_max += price_range * 0.05
    price_range = price_max - price_min
    
    # Time range
    time_min = chart.buckets[0].start_ts
    time_max = chart.buckets[-1].start_ts + 300
    time_range = time_max - time_min
    
    # Create canvas
    canvas = [[" " for _ in range(width)] for _ in range(height)]
    
    # Draw price grid lines (horizontal)
    price_step = price_range / (height - 2)
    for row in range(height):
        price = price_max - row * price_step
        if row == 0 or row == height - 1 or abs(price - round(price)) < price_step / 2:
            price_label = f"{price:.1f}"
            label_str = f"{price_label:>6} "
            for i, ch in enumerate(label_str):
                if i < 7:
                    canvas[row][i] = ch
    
    # Draw Y-axis
    for row in range(height):
        canvas[row][7] = "│"
    
    # Draw X-axis labels (time)
    time_labels = 6
    for i in range(time_labels):
        ts = time_min + (time_range * i) // (time_labels - 1)
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        time_str = dt.strftime("%H:%M")
        col = 8 + (width - 8) * i // (time_labels - 1)
        if col < width - 4:
            for j, ch in enumerate(time_str):
                if height - 1 < height and col + j < width:
                    canvas[height - 1][col + j] = ch
    
    # Plot buckets (candlesticks)
    for bucket in chart.buckets:
        x = 8 + int((bucket.start_ts - time_min) / time_range * (width - 8))
        if x >= width:
            continue
        
        # High-low line
        y_high = int((price_max - bucket.high) / price_range * (height - 2))
        y_low = int((price_max - bucket.low) / price_range * (height - 2))
        y_open = int((price_max - bucket.open) / price_range * (height - 2))
        y_close = int((price_max - bucket.close) / price_range * (height - 2))
        
        y_high = max(0, min(height - 2, y_high))
        y_low = max(0, min(height - 2, y_low))
        y_open = max(0, min(height - 2, y_open))
        y_close = max(0, min(height - 2, y_close))
        
        # Wick
        for y in range(min(y_high, y_low), max(y_high, y_low) + 1):
            if canvas[y][x] == " ":
                canvas[y][x] = "│"
        
        # Body
        body_top = min(y_open, y_close)
        body_bottom = max(y_open, y_close)
        if body_top == body_bottom:
            canvas[body_top][x] = "─"
        else:
            for y in range(body_top, body_bottom + 1):
                if canvas[y][x] in (" ", "│"):
                    canvas[y][x] = "█" if bucket.close >= bucket.open else "░"
    
    # Plot S/R levels
    for level in chart.sr_levels:
        y = int((price_max - level.price) / price_range * (height - 2))
        y = max(0, min(height - 2, y))
        symbol = "═" if level.is_strong else "─"
        for x in range(8, width - 1):
            if canvas[y][x] == " ":
                canvas[y][x] = symbol
        # Label
        label = f"{level.price:.1f} {'R' if level.level_type == 'RESISTANCE' else 'S'}{level.touches}"
        for j, ch in enumerate(label):
            if y < height and 8 + j < width:
                canvas[y][8 + j] = ch
    
    # Plot marks (entries/exits)
    mark_symbols = {
        "ENTRY_LONG": "▲",
        "ENTRY_SHORT": "▼",
        "EXIT_TP": "✓",
        "EXIT_TIME": "✗",
        "EXIT_ROL": "↷",
        "EXIT_SL": "✕",
        "EXIT_FADE": "⟲",
        "EXIT_TRAIL": "⤴"
    }
    
    for mark in chart.marks:
        x = 8 + int((mark.timestamp - time_min) / time_range * (width - 8))
        y = int((price_max - mark.price) / price_range * (height - 2))
        x = max(8, min(width - 2, x))
        y = max(0, min(height - 2, y))
        symbol = mark_symbols.get(mark.mark_type, "?")
        if canvas[y][x] == " ":
            canvas[y][x] = symbol
        elif canvas[y][x] in ("│", "─", "═", "█", "░"):
            canvas[y][x] = symbol  # Override for visibility
    
    # Convert to string
    lines = []
    for row in canvas:
        lines.append("".join(row).rstrip())
    
    # Add legend
    lines.append("")
    lines.append("Legend: ▲=Long Entry  ▼=Short Entry  ✓=TP  ✗=TIME  ✕=SL  ↷=ROL  ⟲=FADE")
    lines.append("        █=Bullish Candle  ░=Bearish Candle  ═=Strong S/R  ─=Weak S/R")
    
    return "\n".join(lines)

def generate_data_table(chart: PriceChart) -> str:
    """Generate tabular data for loop-engineering verification"""
    lines = []
    lines.append("=" * 100)
    lines.append(f"PRICE CHART DATA TABLE — Session: {datetime.fromtimestamp(chart.session_start_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append(f"Generated: {datetime.fromtimestamp(chart.current_ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append("=" * 100)
    
    # 5-min buckets table
    lines.append("\n📊 5-MINUTE BUCKETS (OHLCV)")
    lines.append("-" * 100)
    lines.append(f"{'Time (UTC)':<12} {'Open':>8} {'High':>8} {'Low':>8} {'Close':>8} {'Mid':>8} {'Vol':>4} {'Trend':<8}")
    lines.append("-" * 100)
    
    prev_close = None
    for b in chart.buckets:
        dt = datetime.fromtimestamp(b.start_ts, tz=timezone.utc)
        time_str = dt.strftime("%H:%M")
        trend = ""
        if prev_close is not None:
            diff = b.close - prev_close
            trend = f"{diff:+.2f}"
        lines.append(f"{time_str:<12} {b.open:>8.2f} {b.high:>8.2f} {b.low:>8.2f} {b.close:>8.2f} {b.mid:>8.2f} {b.volume:>4} {trend:<8}")
        prev_close = b.close
    
    # Swing points table
    lines.append("\n🔄 SWING POINTS (Fractal ±2 buckets)")
    lines.append("-" * 100)
    lines.append(f"{'Time (UTC)':<12} {'Type':<6} {'Price':>8} {'Confirmed':>10} {'Broken':>8} {'Touches':>8} {'Strength':>8}")
    lines.append("-" * 100)
    for s in chart.swings:
        dt = datetime.fromtimestamp(s.timestamp, tz=timezone.utc)
        lines.append(f"{dt.strftime('%H:%M'):<12} {s.swing_type:<6} {s.price:>8.2f} {str(s.confirmed):>10} {str(s.broken):>8} {s.touches:>8} {s.strength:>8}")
    
    # S/R Levels table
    lines.append("\n🎯 SUPPORT/RESISTANCE LEVELS")
    lines.append("-" * 100)
    lines.append(f"{'Price':>8} {'Type':<12} {'Touches':>8} {'Strong':>8} {'First Seen':<12} {'Last Test':<12} {'Strength':>8}")
    lines.append("-" * 100)
    for l in chart.sr_levels:
        dt_first = datetime.fromtimestamp(l.first_ts, tz=timezone.utc)
        dt_last = datetime.fromtimestamp(l.last_ts, tz=timezone.utc)
        lines.append(f"{l.price:>8.2f} {l.level_type:<12} {l.touches:>8} {str(l.is_strong):>8} {dt_first.strftime('%H:%M'):<12} {dt_last.strftime('%H:%M'):<12} {l.strength:>8.1f}")
    
    # Entries/Exits table
    lines.append("\n📍 ENTRIES & EXITS")
    lines.append("-" * 100)
    lines.append(f"{'Time (UTC)':<12} {'Type':<14} {'Price':>8} {'Position':<12} {'PnL':>8}")
    lines.append("-" * 100)
    all_marks = sorted(chart.marks, key=lambda m: m.timestamp)
    for m in all_marks:
        dt = datetime.fromtimestamp(m.timestamp, tz=timezone.utc)
        pnl_str = f"{m.pnl:+.2f}" if m.pnl != 0 else "—"
        lines.append(f"{dt.strftime('%H:%M'):<12} {m.mark_type:<14} {m.price:>8.2f} {m.position_id:<12} {pnl_str:>8}")
    
    # Key observations
    lines.append("\n🔍 KEY OBSERVATIONS")
    lines.append("-" * 100)
    
    # Price range
    if chart.buckets:
        session_low = min(b.low for b in chart.buckets)
        session_high = max(b.high for b in chart.buckets)
        lines.append(f"Session Range: {session_low:.2f} → {session_high:.2f} ({session_high - session_low:.2f} pts)")
    
    # Strong levels near current price
    if chart.buckets:
        current_price = chart.buckets[-1].close
        for level in chart.sr_levels:
            if level.is_strong:
                dist = abs(current_price - level.price)
                if dist <= 2.0:
                    side = "ABOVE" if current_price > level.price else "BELOW"
                    lines.append(f"⚠️  Strong {level.level_type} at {level.price:.2f} ({level.touches} touches) — Current price {side} by {dist:.2f} pts")
    
    # Recent swing analysis
    recent_swings = [s for s in chart.swings if s.timestamp > chart.current_ts - 7200]  # last 2 hours
    if recent_swings:
        last_high = max((s for s in recent_swings if s.swing_type == "HIGH"), key=lambda x: x.timestamp, default=None)
        last_low = min((s for s in recent_swings if s.swing_type == "LOW"), key=lambda x: x.timestamp, default=None)
        if last_high and last_low:
            lines.append(f"Last Swing HIGH: {last_high.price:.2f} @ {datetime.fromtimestamp(last_high.timestamp, tz=timezone.utc).strftime('%H:%M')} (confirmed={last_high.confirmed}, broken={last_high.broken})")
            lines.append(f"Last Swing LOW:  {last_low.price:.2f} @ {datetime.fromtimestamp(last_low.timestamp, tz=timezone.utc).strftime('%H:%M')} (confirmed={last_low.confirmed}, broken={last_low.broken})")
    
    lines.append("=" * 100)
    return "\n".join(lines)

# ─────────────────────────── MAIN BUILDER ───────────────────────────

def build_price_chart(hours_back: int = 6, bucket_minutes: int = 5, 
                       start_ts: Optional[int] = None, end_ts: Optional[int] = None) -> PriceChart:
    """Build complete price chart with all annotations"""
    now = int(datetime.now(timezone.utc).timestamp())
    
    # Determine time range
    if start_ts is None or end_ts is None:
        data_start, data_end = get_data_time_range()
        if start_ts is None:
            start_ts = data_start
        if end_ts is None:
            end_ts = data_end
    
    # Use session start if within data range
    session_start = get_session_start()
    if session_start >= start_ts and session_start <= end_ts:
        effective_start = session_start
    else:
        effective_start = start_ts
    
    # Load data
    candles_1m = load_candles_1m_range(effective_start, end_ts)
    entries = load_entries_range(effective_start, end_ts)
    exits = load_exits_range(effective_start, end_ts)
    
    # Build buckets
    if bucket_minutes == 5:
        buckets = build_5m_buckets(candles_1m)
    else:
        # Convert 1m candles directly to buckets
        buckets = [Bucket5m(align_to_bucket(c.timestamp, bucket_minutes*60), c.open, c.high, c.low, c.close, 1) 
                   for c in candles_1m]
    
    # Filter to session
    buckets = [b for b in buckets if b.start_ts >= effective_start]
    
    # Detect swings
    swings = detect_fractal_swings(buckets, lookback=2)
    swings = confirm_swings(swings, buckets)
    
    # Build S/R levels
    sr_levels = cluster_swings_to_levels(swings, merge_threshold=5.0)
    
    # Combine marks
    marks = entries + exits
    
    return PriceChart(
        buckets=buckets,
        swings=swings,
        sr_levels=sr_levels,
        marks=marks,
        session_start_ts=effective_start,
        current_ts=now
    )

# ─────────────────────────── CLI ───────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="XAU_SCALP5 Price Chart Visualization")
    parser.add_argument("--hours", type=int, default=6, help="Hours of history to load (from data end)")
    parser.add_argument("--bucket", type=str, default="5m", choices=["1m", "5m", "15m"], help="Bucket timeframe")
    parser.add_argument("--width", type=int, default=100, help="Chart width")
    parser.add_argument("--height", type=int, default=25, help="Chart height")
    parser.add_argument("--save", type=str, help="Save output to file")
    parser.add_argument("--table-only", action="store_true", help="Only output data table")
    parser.add_argument("--chart-only", action="store_true", help="Only output ASCII chart")
    parser.add_argument("--date", type=str, help="Specific date (YYYY-MM-DD) to chart (uses that day's session)")
    args = parser.parse_args()
    
    bucket_min = int(args.bucket.replace("m", ""))
    
    # Determine time range
    if args.date:
        # Parse date and get session range
        target_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        session_start = datetime(target_date.year, target_date.month, target_date.day, 7, 30, tzinfo=timezone.utc)
        session_end = session_start + timedelta(hours=24)
        start_ts = int(session_start.timestamp())
        end_ts = int(session_end.timestamp())
    else:
        # Use data time range
        data_start, data_end = get_data_time_range()
        # Default to last N hours from data end
        start_ts = data_end - args.hours * 3600
        end_ts = data_end
    
    chart = build_price_chart(start_ts=start_ts, end_ts=end_ts, bucket_minutes=bucket_min)
    
    output_parts = []
    
    if not args.table_only:
        ascii_chart = generate_ascii_chart(chart, args.width, args.height)
        output_parts.append(ascii_chart)
    
    if not args.chart_only:
        data_table = generate_data_table(chart)
        output_parts.append(data_table)
    
    output = "\n\n".join(output_parts)
    print(output)
    
    if args.save:
        save_path = BASE_DIR / args.save
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(output)
        print(f"\n✅ Saved to {save_path}")

if __name__ == "__main__":
    main()