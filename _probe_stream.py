"""Probe 2: WS PIPELINE KÈT TEST (không redeploy — Forbidden trên plan này).
Chuỗi kiểm chứng đường ống streaming:
  connect(30s) -> wait_synchronized(200s) -> subscribe(XAUUSDm) -> đếm tick thật 30s.
Kết luận:
  - sync OK + tick>0   = pipeline THÔNG, gateway đã hồi
  - sync OK + tick=0   = pipeline KẸT ở lớp subscribe/push
  - sync timeout 200s  = terminal-state channel phía cloud vẫn kẹt
"""
import asyncio, os, time
from dotenv import load_dotenv

load_dotenv()


def _make_listener(tc):
    from metaapi_cloud_sdk.clients.metaapi.synchronization_listener import SynchronizationListener

    class L(SynchronizationListener):
        async def on_symbol_price_updated(self, instance_index, price):
            tc["n"] += 1
            tc["last_px"] = price.get("price") if isinstance(price, dict) else getattr(price, "price", None)

    return L()


async def main():
    from metaapi_cloud_sdk import MetaApi
    api = MetaApi(os.environ["METAAPI_TOKEN"])
    account = await asyncio.wait_for(
        api.metatrader_account_api.get_account(os.environ["ACCOUNT_ID"]),
        timeout=20,
    )
    print(f"account state={account.state} conn={account.connection_status}")

    conn = account.get_streaming_connection()
    await asyncio.wait_for(conn.connect(), timeout=30)
    print("WS connected ✓")

    t0 = time.time()
    try:
        await asyncio.wait_for(conn.wait_synchronized(), timeout=200)
        print(f"SYNC OK after {time.time()-t0:.0f}s ✓")
    except Exception as e:
        print(f"SYNC FAIL after {time.time()-t0:.0f}s: {type(e).__name__} — pipeline kẹt phía cloud, bỏ subscribe")
        return

    tc = {"n": 0, "last_px": None}
    conn.add_synchronization_listener(_make_listener(tc))

    try:
        await asyncio.wait_for(conn.subscribe_to_market_data("XAUUSDm"), timeout=30)
        print("SUBSCRIBED ✓")
    except Exception as e:
        print(f"SUBSCRIBE FAIL: {type(e).__name__}: {str(e)[:200]} — KẸT ở lớp subscribe")
        return

    await asyncio.sleep(30)
    print(f"TICKS 30s: n={tc['n']} last_px={tc['last_px']}")
    print("VERDICT:", "PIPELINE THÔNG" if tc["n"] > 0 else "KẸT TAY (sync OK nhưng không có tick push)")


asyncio.run(main())
