"""PROBE position-dict shape (magic 20261099 = RÁC, bot không adopt).
Mở 0.02 buy → get_positions() RAW → đóng. Mục đích: xác định dạng
'openPrice' (float/str/None) + 'side' (str/int) + 'magic' — bằng chứng
cho bug EXIT 'TP' giả @03:16 (chốt lệnh LỖ vì pnl_pts đảo dấu)."""
import asyncio, os, time
from dotenv import load_dotenv

load_dotenv(os.path.join(os.getcwd(), ".env"))
MAGIC_TEST = 20261099
VOLUME = 0.02


async def main():
    from metaapi_cloud_sdk import MetaApi
    t0 = time.time()
    api = MetaApi(os.environ["METAAPI_TOKEN"])
    account = await asyncio.wait_for(
        api.metatrader_account_api.get_account(os.environ["ACCOUNT_ID"]), timeout=20
    )
    conn = account.get_rpc_connection()
    await asyncio.wait_for(conn.connect(), timeout=30)
    await asyncio.wait_for(conn.wait_synchronized(), timeout=120)
    print(f"RPC sync OK ({time.time()-t0:.0f}s)")

    res = await conn.create_market_buy_order(
        symbol="XAUUSDm", volume=VOLUME,
        options={"magic": MAGIC_TEST, "comment": "SCALP5-SHAPE"},
    )
    await asyncio.sleep(3)
    pos = [p for p in (await conn.get_positions() or []) if p.get("magic") == MAGIC_TEST]
    if not pos:
        print("VỊ THẾ KHÔNG HIỆN — res=", res)
        await conn.close()
        return
    p0 = pos[0]
    print("RAW position dict:")
    for k, v in p0.items():
        print(f"  {k!r:20} = {v!r:18} ({type(v).__name__})")
    print(f"→ openPrice={p0.get('openPrice')!r} side={p0.get('side')!r} "
          f"takeProfit={p0.get('takeProfit')!r} openTime={p0.get('openTime')!r}")

    await conn.close_position(str(p0["id"]))
    await asyncio.sleep(2)
    still = [p for p in (await conn.get_positions() or []) if p.get("magic") == MAGIC_TEST]
    print(f"CLOSE {'✓ (biến mất)' if not still else '✖ VẪN MỞ: ' + str(still)} — {time.time()-t0:.0f}s")
    await conn.close()


asyncio.run(main())
