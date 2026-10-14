"""PRE-LIVE CONNECT — verify: initialize · HARD-GATE demo · symbol · 1 M1 candle vào DB MỚI.
Chạy: SSL_CERT_FILE=$PWD/.venv/lib/python3.12/site-packages/certifi/cacert.pem ./.venv/bin/python test_connect.py
"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.getcwd(), ".env"))

from src import config as C
from src.models import Candle, Timeframe
from src.metaapi_client import MetaAPIClient
from src.storage import get_storage


async def main() -> None:
    token = os.environ["METAAPI_TOKEN"]
    account = os.environ["ACCOUNT_ID"]
    print(f"[1] token={token[:8]}... account={account}")
    client = MetaAPIClient(token, account)
    ok = await client.initialize()
    print(f"[2] initialize ok={ok}")
    if not ok:
        raise SystemExit("INIT FAIL")

    # HARD-GATE: chỉ DEMO (MetaApi raw: type='ACCOUNT_TRADE_MODE_DEMO')
    raw = await client.rpc_connection.get_account_information()
    tmode = str(raw.get("type", "")).upper()
    print(f"[3] trade-mode={raw.get('type')!r} · server={raw.get('server')} · login={raw.get('login')} · balance={raw.get('balance')} · lev={raw.get('leverage')}")
    if "DEMO" not in tmode:
        raise SystemExit(f"[GATE] trade-mode={raw.get('type')!r} != DEMO → CHẶM (không cho chạy LIVE)")

    # symbol
    si = await client.get_symbol_info(C.SYMBOL)
    print(f"[4] {C.SYMBOL}: point={si.pip_size} digits_ok={si is not None} contract={si.contract_size}")

    # 1 M1 candle thật → DB MỚI (scalp5.db)
    storage = await get_storage("data/scalp5.db")
    c = await client.fetch_candles(C.SYMBOL, Timeframe.M1, limit=3)
    if c:
        last = c[-1]
        ts = last.timestamp  # datetime
        await storage.insert_candle(Candle(
            symbol=C.SYMBOL, timeframe=Timeframe.M1, timestamp=ts,
            open=last.open, high=last.high, low=last.low, close=last.close,
        ))
        rows = await storage.get_candles(C.SYMBOL, Timeframe.M1, 5)
        print(f"[5] M1 candles fetched={len(c)} · last close={last.close} @ {ts} · rows in scalp5.db={len(rows)}")
    else:
        print("[5] FETCH M1 CANDLE FAIL")
        raise SystemExit(1)

    print("\nCONNECT OK ✅ — đủ điều kiện chạy LIVE")


if __name__ == "__main__":
    asyncio.run(main())
