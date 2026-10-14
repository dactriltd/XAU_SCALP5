"""RPC ORDER PIPELINE TEST: chứng minh đường ống vào-lệnh SÓNG (độc lập với streaming).
Chạy THẪY: connect RPC -> sync -> mở market buy 0.02 lot (magic 20261099 = RÁC,
bot không adopt) -> find position -> close_position -> verify closed.
Demo account: chi phí ≈ spread, không giữ vị thế.
"""
import asyncio, os, time
from dotenv import load_dotenv

load_dotenv()
MAGIC_TEST = 20261099  # khác magic bot (20261013) → bot không adopt
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
    print(f"RPC connect OK ({time.time()-t0:.0f}s)")
    await asyncio.wait_for(conn.wait_synchronized(), timeout=120)
    print("RPC sync OK ✓")

    info = await conn.get_account_information()
    print(f"account: balance={info.get('balance')} login={info.get('login')}")

    # 1) MỞ: market buy 0.02, không SL/TP (TP phải xa để khỏi chạm)
    res = await conn.create_market_buy_order(
        symbol="XAUUSDm", volume=VOLUME,
        options={"magic": MAGIC_TEST, "comment": "PIPETEST"},
    )
    await asyncio.sleep(2)
    pos = [
        p for p in (await conn.get_positions() or [])
        if p.get("magic") == MAGIC_TEST
    ]
    assert pos, f"VỊ THẾ KHÔNG HIỆN SAU LỆNH — pipe order CHƯA SÓNG. res={res}"
    p0 = pos[0]
    print(f"OPEN ✓ pos_id={p0['id']} side={p0.get('side')} entry={p0.get('openPrice')}")

    # 2) ĐÓNG: close_position -> verify biến mất
    await conn.close_position(str(p0["id"]))
    await asyncio.sleep(2)
    still = [
        p for p in (await conn.get_positions() or [])
        if p.get("magic") == MAGIC_TEST
    ]
    print(f"CLOSE {'✓ (biến mất)' if not still else '✖ VẪN MỞ: ' + str(still)}")
    print(f"TOTAL {time.time()-t0:.0f}s — RPC ORDER PIPE: {'SÓNG' if not still else 'CHƯA CHAK'}")
    await conn.close()


asyncio.run(main())
