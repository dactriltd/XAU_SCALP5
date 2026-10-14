#!/usr/bin/env python3
"""
XAU_SCALP5 — Price Chart Verification for Loop-Engineering
Generates structured JSON report from price chart analysis.
Integrates with loop-engineering verification framework.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import chart builder
sys.path.insert(0, str(Path(__file__).resolve().parent))
from price_chart import (
    build_price_chart, PriceChart, SwingPoint, SRLevel, ChartMark,
    get_data_time_range
)

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"
REPORT_PATH = LOGS_DIR / "price_chart_report.json"

# Thresholds from config
S_CONFIRM_BOUNCE = 2.5
S_CONFIRM_MINS = 5
FZ_MIN_TOUCH = 2
FZ_BAND_PTS = 0.5
MOM_PUB_PTS = 0.8


def analyze_price_structure(chart: PriceChart) -> Dict[str, Any]:
    """Block 8: Price structure analysis"""
    if not chart.buckets:
        return {"status": "WARN", "details": "No bucket data", "score": 0}
    
    current_price = chart.buckets[-1].close
    
    # Find strong unbroken levels near current price
    strong_resistance = [l for l in chart.sr_levels 
                        if l.level_type == "RESISTANCE" and l.is_strong and not any(
                            s for s in chart.swings 
                            if s.swing_type == "HIGH" and abs(s.price - l.price) <= 0.5 and s.broken
                        )]
    strong_support = [l for l in chart.sr_levels 
                     if l.level_type == "SUPPORT" and l.is_strong and not any(
                         s for s in chart.swings 
                         if s.swing_type == "LOW" and abs(s.price - l.price) <= 0.5 and s.broken
                     )]
    
    # Distance to nearest strong levels
    nearest_res = min(strong_resistance, key=lambda l: abs(l.price - current_price), default=None)
    nearest_sup = min(strong_support, key=lambda l: abs(l.price - current_price), default=None)
    
    dist_res = abs(nearest_res.price - current_price) if nearest_res else None
    dist_sup = abs(nearest_sup.price - current_price) if nearest_sup else None
    
    issues = []
    status = "PASS"
    
    if nearest_res and dist_res is not None and dist_res <= 1.0:
        issues.append(f"Price at strong unbroken RESISTANCE {nearest_res.price:.2f} ({nearest_res.touches} touches) — distance {dist_res:.2f} pts")
        status = "FAIL"
    elif nearest_res and dist_res is not None and dist_res <= 2.0:
        issues.append(f"Price approaching strong RESISTANCE {nearest_res.price:.2f} — distance {dist_res:.2f} pts")
        if status == "PASS":
            status = "WARN"
    
    if nearest_sup and dist_sup is not None and dist_sup <= 1.0:
        issues.append(f"Price at strong unbroken SUPPORT {nearest_sup.price:.2f} ({nearest_sup.touches} touches) — distance {dist_sup:.2f} pts")
        status = "FAIL"
    elif nearest_sup and dist_sup is not None and dist_sup <= 2.0:
        issues.append(f"Price approaching strong SUPPORT {nearest_sup.price:.2f} — distance {dist_sup:.2f} pts")
        if status == "PASS":
            status = "WARN"
    
    # Check swing structure clarity
    recent_swings = [s for s in chart.swings if s.timestamp > chart.current_ts - 7200]  # last 2 hours
    confirmed_swings = [s for s in recent_swings if s.confirmed]
    unconfirmed_swings = [s for s in recent_swings if not s.confirmed and not s.broken]
    
    if unconfirmed_swings:
        issues.append(f"{len(unconfirmed_swings)} recent swing(s) unconfirmed after {S_CONFIRM_MINS} buckets")
        if status == "PASS":
            status = "WARN"
    
    return {
        "status": status,
        "details": "; ".join(issues) if issues else "Price structure clear, no immediate S/R conflict",
        "score": 100 if status == "PASS" else (50 if status == "WARN" else 0),
        "current_price": current_price,
        "nearest_resistance": {"price": nearest_res.price, "touches": nearest_res.touches, "distance": dist_res} if nearest_res else None,
        "nearest_support": {"price": nearest_sup.price, "touches": nearest_sup.touches, "distance": dist_sup} if nearest_sup else None,
        "recent_swings": len(recent_swings),
        "confirmed_swings": len(confirmed_swings),
        "unconfirmed_swings": len(unconfirmed_swings)
    }


def analyze_swing_reaction(chart: PriceChart) -> Dict[str, Any]:
    """Block 9: Swing reaction timing analysis"""
    if not chart.swings:
        return {"status": "WARN", "details": "No swing data", "score": 0}
    
    issues = []
    status = "PASS"
    
    # Check each confirmed swing for reaction time
    for swing in chart.swings:
        if not swing.confirmed:
            continue
        
        # Find subsequent buckets
        subsequent = [b for b in chart.buckets if b.start_ts > swing.timestamp]
        if not subsequent:
            continue
        
        # Measure bounce
        max_bounce = 0
        bounce_bucket = None
        for i, bucket in enumerate(subsequent):
            if swing.swing_type == "HIGH":
                bounce = swing.price - bucket.low
            else:
                bounce = bucket.high - swing.price
            
            if bounce > max_bounce:
                max_bounce = bounce
                bounce_bucket = i
            
            if bounce >= S_CONFIRM_BOUNCE:
                # Confirmed bounce within expected time
                if i < S_CONFIRM_MINS:
                    break  # Good confirmation
                else:
                    issues.append(f"Swing {swing.swing_type} {swing.price:.2f} @ {datetime.fromtimestamp(swing.timestamp, tz=timezone.utc).strftime('%H:%M')} confirmed but slow ({i} buckets)")
                    if status == "PASS":
                        status = "WARN"
                break
        else:
            # No bounce ≥ threshold found
            if len(subsequent) >= S_CONFIRM_MINS:
                issues.append(f"Swing {swing.swing_type} {swing.price:.2f} unconfirmed after {len(subsequent)} buckets (max bounce {max_bounce:.2f} pts)")
                status = "WARN"
    
    # Check for broken swings that were previously strong
    broken_strong = [s for s in chart.swings if s.broken and s.touches >= FZ_MIN_TOUCH]
    if broken_strong:
        for s in broken_strong:
            issues.append(f"Strong swing {s.swing_type} {s.price:.2f} ({s.touches} touches) BROKEN — level invalidated")
        if status == "PASS":
            status = "WARN"
    
    return {
        "status": status,
        "details": "; ".join(issues) if issues else "All swings confirmed with proper reaction timing",
        "score": 100 if status == "PASS" else (50 if status == "WARN" else 0),
        "total_swings": len(chart.swings),
        "confirmed": len([s for s in chart.swings if s.confirmed]),
        "broken": len([s for s in chart.swings if s.broken]),
        "issues": issues
    }


def analyze_entry_quality_vs_structure(chart: PriceChart) -> Dict[str, Any]:
    """Block 10: Entry quality relative to price structure"""
    entries = [m for m in chart.marks if m.mark_type.startswith("ENTRY_")]
    if not entries:
        return {"status": "PASS", "details": "No entries in period", "score": 100}
    
    issues = []
    status = "PASS"
    entry_analysis = []
    
    for entry in entries:
        # Find nearest swing
        nearest_swing = min(chart.swings, key=lambda s: abs(s.price - entry.price), default=None)
        swing_dist = abs(nearest_swing.price - entry.price) if nearest_swing else None
        
        # Find nearest S/R level
        nearest_level = min(chart.sr_levels, key=lambda l: abs(l.price - entry.price), default=None)
        level_dist = abs(nearest_level.price - entry.price) if nearest_level else None
        
        # Determine entry quality
        quality = "GOOD"
        if nearest_level and level_dist is not None and level_dist <= FZ_BAND_PTS:
            if nearest_level.is_strong:
                quality = "POOR"  # Entry at strong S/R
                issues.append(f"ENTRY {entry.mark_type} at {entry.price:.2f} at strong {nearest_level.level_type} {nearest_level.price:.2f} ({nearest_level.touches} touches)")
                status = "FAIL"
            else:
                quality = "CAUTION"
                issues.append(f"ENTRY {entry.mark_type} at {entry.price:.2f} near weak {nearest_level.level_type} {nearest_level.price:.2f}")
                if status == "PASS":
                    status = "WARN"
        elif nearest_swing and swing_dist is not None and swing_dist <= MOM_PUB_PTS:
            # Entry very close to swing extreme = chasing
            quality = "POOR"
            issues.append(f"ENTRY {entry.mark_type} at {entry.price:.2f} chasing swing {nearest_swing.swing_type} {nearest_swing.price:.2f} (dist {swing_dist:.2f})")
            status = "FAIL"
        elif nearest_swing and swing_dist is not None and swing_dist >= 1.5:
            # Entry at pullback from swing = good
            quality = "GOOD"
        
        entry_analysis.append({
            "timestamp": datetime.fromtimestamp(entry.timestamp, tz=timezone.utc).strftime("%H:%M"),
            "type": entry.mark_type,
            "price": entry.price,
            "position_id": entry.position_id,
            "nearest_swing": {"price": nearest_swing.price, "type": nearest_swing.swing_type, "dist": swing_dist} if nearest_swing else None,
            "nearest_level": {"price": nearest_level.price, "type": nearest_level.level_type, "dist": level_dist, "strong": nearest_level.is_strong} if nearest_level else None,
            "quality": quality
        })
    
    poor_entries = [e for e in entry_analysis if e["quality"] == "POOR"]
    caution_entries = [e for e in entry_analysis if e["quality"] == "CAUTION"]
    
    if poor_entries and status == "PASS":
        status = "FAIL"
    elif caution_entries and status == "PASS":
        status = "WARN"
    
    return {
        "status": status,
        "details": "; ".join(issues) if issues else f"All {len(entries)} entries at good pullback positions",
        "score": 100 if status == "PASS" else (50 if status == "WARN" else 0),
        "total_entries": len(entries),
        "poor_entries": len(poor_entries),
        "caution_entries": len(caution_entries),
        "good_entries": len([e for e in entry_analysis if e["quality"] == "GOOD"]),
        "entries": entry_analysis
    }


def generate_verification_report(chart: PriceChart) -> Dict[str, Any]:
    """Generate complete verification report"""
    block8 = analyze_price_structure(chart)
    block9 = analyze_swing_reaction(chart)
    block10 = analyze_entry_quality_vs_structure(chart)
    
    # Overall status
    statuses = [block8["status"], block9["status"], block10["status"]]
    if "FAIL" in statuses:
        overall = "FAIL"
    elif "WARN" in statuses:
        overall = "WARN"
    else:
        overall = "PASS"
    
    # Price range
    price_range = {}
    if chart.buckets:
        session_low = min(b.low for b in chart.buckets)
        session_high = max(b.high for b in chart.buckets)
        price_range = {"low": session_low, "high": session_high, "range": session_high - session_low}
    
    # Swings summary
    swings_summary = []
    for s in chart.swings:
        dt = datetime.fromtimestamp(s.timestamp, tz=timezone.utc)
        swings_summary.append({
            "time": dt.strftime("%H:%M"),
            "type": s.swing_type,
            "price": s.price,
            "confirmed": s.confirmed,
            "broken": s.broken,
            "touches": s.touches
        })
    
    # S/R levels summary
    sr_summary = []
    for l in chart.sr_levels:
        dt_first = datetime.fromtimestamp(l.first_ts, tz=timezone.utc)
        dt_last = datetime.fromtimestamp(l.last_ts, tz=timezone.utc)
        sr_summary.append({
            "price": l.price,
            "type": l.level_type,
            "touches": l.touches,
            "strong": l.is_strong,
            "first_seen": dt_first.strftime("%H:%M"),
            "last_test": dt_last.strftime("%H:%M")
        })
    
    # Current price
    current_price = chart.buckets[-1].close if chart.buckets else 0
    
    return {
        "ts": int(datetime.now(timezone.utc).timestamp()),
        "chart_period": {
            "start": datetime.fromtimestamp(chart.session_start_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "end": datetime.fromtimestamp(chart.buckets[-1].start_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if chart.buckets else "N/A"
        },
        "price_range": price_range,
        "current_price": current_price,
        "swings": swings_summary,
        "sr_levels": sr_summary,
        "blocks": {
            "8_PRICE_STRUCTURE": block8,
            "9_SWING_REACTION": block9,
            "10_ENTRY_QUALITY": block10
        },
        "overall": overall,
        "n_fail": sum(1 for b in [block8, block9, block10] if b["status"] == "FAIL"),
        "n_warn": sum(1 for b in [block8, block9, block10] if b["status"] == "WARN")
    }


def update_state_md(report: Dict[str, Any]) -> None:
    """Update STATE.md with chart verification findings"""
    state_path = BASE_DIR / "STATE.md"
    if not state_path.exists():
        return
    
    content = state_path.read_text()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    # Build updates
    high_priority = []
    watch_list = []
    noise = []
    
    for block_name, block in report["blocks"].items():
        block_num = block_name.split("_")[0]
        if block["status"] == "FAIL":
            high_priority.append(f"[Block {block_num}] {block['details']} — FAIL")
        elif block["status"] == "WARN":
            watch_list.append(f"[Block {block_num}] {block['details']} — WARN")
        else:
            noise.append(f"[Block {block_num}] {block['details']} — PASS")
    
    # Add current price context
    if report.get("current_price"):
        noise.append(f"Current price: {report['current_price']:.2f}")
    
    # Add S/R context
    for level in report.get("sr_levels", []):
        if level["strong"]:
            watch_list.append(f"Strong {level['type']} at {level['price']:.2f} ({level['touches']} touches, last test {level['last_test']})")
    
    # Build new state content
    lines = content.split("\n")
    
    # Find sections
    hp_idx = lines.index("## High Priority (loop is acting or waiting on human)") if "## High Priority (loop is acting or waiting on human)" in lines else -1
    wl_idx = lines.index("## Watch List") if "## Watch List" in lines else -1
    rn_idx = lines.index("## Recent Noise (ignored this run)") if "## Recent Noise (ignored this run)" in lines else -1
    log_idx = lines.index("---") if "---" in lines else len(lines)
    
    # Rebuild
    new_lines = lines[:log_idx+1]
    new_lines.append(f"Run log: {now} | price-chart-verify | overall={report['overall']} | F={report['n_fail']} W={report['n_warn']}")
    new_lines.append("")
    new_lines.append("## High Priority (loop is acting or waiting on human)")
    for item in high_priority:
        new_lines.append(f"- {item}")
    new_lines.append("")
    new_lines.append("## Watch List")
    for item in watch_list:
        new_lines.append(f"- {item}")
    new_lines.append("")
    new_lines.append("## Recent Noise (ignored this run)")
    for item in noise:
        new_lines.append(f"- {item}")
    
    state_path.write_text("\n".join(new_lines))


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Price Chart Verification for Loop-Engineering")
    parser.add_argument("--hours", type=int, default=4, help="Hours of history from data end")
    parser.add_argument("--bucket", type=str, default="5m", choices=["1m", "5m", "15m"])
    parser.add_argument("--save-chart", action="store_true", help="Also save ASCII chart to logs/price_chart_latest.txt")
    parser.add_argument("--update-state", action="store_true", help="Update STATE.md with findings")
    args = parser.parse_args()
    
    bucket_min = int(args.bucket.replace("m", ""))
    
    # Use full available data range
    data_start, data_end = get_data_time_range()
    start_ts = data_end - args.hours * 3600
    
    chart = build_price_chart(start_ts=start_ts, end_ts=data_end, bucket_minutes=bucket_min)
    report = generate_verification_report(chart)
    
    # Save JSON report
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"✅ Price chart verification report saved to {REPORT_PATH}")
    print(f"Overall: {report['overall']} (F={report['n_fail']} W={report['n_warn']})")
    
    # Print block summaries
    for block_name, block in report["blocks"].items():
        icon = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}[block["status"]]
        print(f"  {icon} {block_name}: {block['details']}")
    
    # Save ASCII chart if requested
    if args.save_chart:
        from price_chart import generate_ascii_chart, generate_data_table
        ascii_chart = generate_ascii_chart(chart, width=100, height=25)
        data_table = generate_data_table(chart)
        chart_path = LOGS_DIR / "price_chart_latest.txt"
        chart_path.write_text(ascii_chart + "\n\n" + data_table)
        print(f"✅ ASCII chart saved to {chart_path}")
    
    # Update STATE.md if requested
    if args.update_state:
        update_state_md(report)
        print("✅ STATE.md updated with chart verification findings")
    
    # Exit code for loop-engineering
    exit_code = {"PASS": 0, "WARN": 1, "FAIL": 2}[report["overall"]]
    sys.exit(exit_code)


if __name__ == "__main__":
    main()