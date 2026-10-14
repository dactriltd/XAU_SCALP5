"""DIAG 18:00 — tại sao không có entry nào sau 17:47?
Fetch M1 trong ngày (MetaApi, 1 RPC) → replay decide() thật → dump ladder state + entry list.
Chạy: .venv/bin/python _diag_today.py   (giữ data/diag_m1_today.json để reuse cho lần replay code MỚI)
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))
from dotenv import load_dotenv

load_dotenv(".env")

from src import config as C
from src.metaapi_client import MetaAPIClient
from src.models import Timeframe
from src.scalp_strategy import ScalpStrategy

JSON_PATH = os.path.join("data", "diag_m1_today.json")


async def fetch(force: bool = False):
    if os.path.exists(JSON_PATH) and not force:
        with open(JSON_PATH) as f:
            return json.load(f)
    token = os.environ.get("METAAPI_TOKEN", "")
    account = os.environ.get("ACCOUNT_ID", "")
    client = MetaAPIClient(token, account)
    assert await client.initialize(), "MetaApi initialize fail"
    now = int(datetime.now(timezone.utc).timestamp())
    today = now - now % 86400
    cut = now - now % 60
    bars = await client.fetch_candles(C.SYMBOL, Timeframe.M1, limit=C.S1_SWINGS)
    rows = [(int(c.timestamp.timestamp()), c.open, c.high, c.low, c.close)
            for c in bars if today <= int(c.timestamp.timestamp()) < cut]
    await client.shutdown()
    with open(JSON_PATH, "w") as f:
        json.dump(rows, f)
    return rows


def replay(rows, label: str):
    s = ScalpStrategy(C)
    open_pos, ents, nxt = [], [], 1
    for ts, o, h, l, c in rows:
        for dt, px in ((10, o), (25, h), (40, l), (58, c)):
            s.on_tick(ts + dt, px)
            for a in s.decide(open_pos, C.WINDOWS, C.ROLLOVER_MIN):
                if a["kind"].startswith("ENTER"):
                    open_pos.append({"id": str(nxt), "side": "L" if a["kind"] == "ENTER_LONG" else "S",
                                    "entry": a["px"], "entry_ts": ts + dt, "anchor": a["anchor"]})
                    ents.append((datetime.fromtimestamp(ts + dt, timezone.utc).strftime("%H:%M"),
                                 a["kind"], round(a["px"], 2), round(a["anchor"], 2), a.get("touch")))
                    nxt += 1
                else:
                    open_pos = [p for p in open_pos if p["id"] != a["pos_id"]]
    lv = [(datetime.fromtimestamp(x.ts, timezone.utc).strftime("%H:%M"), x.kind, round(x.px, 1),
          "conf" if x.confirmed else "raw", "T%d" % x.touches, "CONSUMED" if x.consumed else "")
          for x in s.levels if not x.broken]
    print(f"--- {label} ---")
    print(f"entries today ({len(ents)}):")
    for e in ents:
        print("  ", e)
    print("L-alive:", [x for x in lv if x[1] == "L"])
    print("H-alive:", [x for x in lv if x[1] == "H"])
    print(f"state cuối: px={s.last_px} · drift5m={s.drift5m():+.2f} · lowest_conf_l={s.lowest_conf_l} · highest_conf_h={s.highest_conf_h}")
    return ents, lv


def main():
    rows = asyncio.run(fetch())
    print(f"M1 trong ngày (khép) = {len(rows)} nến · {datetime.fromtimestamp(rows[0][0], timezone.utc):%H:%M}→{datetime.fromtimestamp(rows[-1][0], timezone.utc):%H:%M}Z")
    replay(rows, "REPLAY (code hiện tại)")


if __name__ == "__main__":
    main()
