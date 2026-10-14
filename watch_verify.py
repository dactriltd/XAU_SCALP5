#!/usr/bin/env python3
"""XAU_SCALP5 — TERMINAL DASHBOARD (watch mode).

Poll logs/scalp5_verify_report.json mỗi 30s, vẽ dashboard 7 blocks.
Tự-clear + redraw (không scroll, giữ màn hình gọn).

Sử dụng ANSI colors (macOS Terminal / iTerm2 / VSCode terminal).

Chạy:
  ./.venv/bin/python watch_verify.py          # foreground (Ctrl+C dừng)
  ./.venv/bin/python watch_verify.py --once   # show 1 lần rồi exit

Thư viện: stdlib only (Karpathy Law 1)
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

# ── COLORS ──
class C:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    WHITE   = "\033[37m"

    @staticmethod
    def status_color(s: str) -> str:
        return {"PASS": C.GREEN, "WARN": C.YELLOW, "FAIL": C.RED}.get(s, C.WHITE)

    @staticmethod
    def status_icon(s: str) -> str:
        return {"PASS": "✓", "WARN": "⚠", "FAIL": "✗"}.get(s, "?")


# ── PATHS ──
REPORT_FILE = Path(__file__).parent / "logs" / "scapy_verify_report.json"
# fallback
if not REPORT_FILE.exists():
    REPORT_FILE = Path(__file__).parent / "logs" / "scalp5_verify_report.json"

POLL_SECONDS = 30
BLOCK_LABELS = {
    "1_TICK_STREAM":           "TICK STREAM",
    "2_STRATEGY_STATE":        "STRATEGY",
    "3_POSITIONS":             "POSITIONS",
    "4_TELEMETRY":             "TELEMETRY",
    "5_SUPERVISOR":            "SUPERVISOR",
    "6_ENTRY_QUALITY":         "ENTRY QUALITY",
    "7_STRUCTURE_RESISTANCE":  "STRUCTURE",
}


def load_report() -> Dict:
    """Đọc report JSON mới nhất."""
    try:
        with open(REPORT_FILE) as f:
            return json.load(f)
    except Exception:
        return {"overall": "N/A", "n_fail": 0, "n_warn": 0, "checks": []}


def render(report: Dict) -> str:
    """Vẽ 1 frame dashboard (ANSI escape, clear + redraw)."""
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    overall = report.get("overall", "N/A")
    n_fail  = report.get("n_fail", 0)
    n_warn  = report.get("n_warn", 0)

    # Header
    oc = C.status_color(overall)
    icon = C.status_icon(overall)
    lines = [
        f"\033[2J\033[H" +  # clear screen + home
        f"{C.BOLD}{C.CYAN}╔══════════════════════════════════════════════════════╗{C.RESET}",
        f"{C.CYAN}║{C.RESET}  {C.BOLD}XAU_SCALP5 · 5-MIN VERIFICATION DASHBOARD{C.RESET}          {C.CYAN}║{C.RESET}",
        f"{C.CYAN}╚══════════════════════════════════════════════════════╝{C.RESET}",
        f"{C.DIM}  Updated: {now_str} · Report ts: {report.get('ts', 'N/A')}{C.RESET}",
        f"  {C.BOLD}OVERALL: {oc}{icon} {overall}{C.RESET}"
        + (f"  ({n_fail} FAIL · {n_warn} WARN)" if (n_fail or n_warn) else f"  {C.DIM}(all clear){C.RESET}"),
        "",
    ]

    # 7 blocks
    for i, chk in enumerate(report.get("checks", []), 1):
        blk_id   = chk.get("block", "")
        label    = BLOCK_LABELS.get(blk_id, blk_id.replace("_", " ").title())
        status   = chk.get("status", "N/A")
        observed = chk.get("observed", "")
        color    = C.status_color(status)
        sicon    = C.status_icon(status)
        issues   = chk.get("detail", {}).get("issues", [])

        lines.append(
            f"  {color}{sicon} {label:<16s}{C.RESET}"
            f"  {color}{observed[:52] if len(observed) <= 52 else observed[:49]+'…'}"
        )
        # Show issues (max 1, truncated)
        if issues and status != "PASS":
            lines.append(f"     {C.DIM}→ {issues[0][:70]}{C.RESET}")

    # Footer
    lines.append("")
    lines.append(f"{C.DIM}  Legend: {C.GREEN}✓ PASS{C.RESET}{C.DIM}  {C.YELLOW}⚠ WARN{C.RESET}{C.DIM}  {C.RED}✗ FAIL{C.RESET}")
    lines.append(f"{C.DIM}  Data: logs/scalp5_verify_report.json · poll every {POLL_SECONDS}s · Ctrl+C to exit{C.RESET}")
    lines.append("")

    return "\n".join(lines)


def run(once: bool = False) -> None:
    """Chạy watch loop (hoặc 1 lần nếu --once)."""
    print(f"[WATCH] Monitoring {REPORT_FILE} every {POLL_SECONDS}s...")
    try:
        while True:
            report = load_report()
            print(render(report), end="\n")
            sys.stdout.flush()
            if once:
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print(f"\n[WATCH] Stopped.")


if __name__ == "__main__":
    once = "--once" in sys.argv
    run(once=once)
