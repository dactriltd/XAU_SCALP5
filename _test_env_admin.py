"""TEST QUYẾT ĐỊNH: token MỚI trong .env có quyền reset terminal (undeploy+deploy) thật không?

Nếu UNDEPLOY OK → quyền admin thật → escalation self-heal của bot
(recover_streaming_after_stuck_sync → redeploy khi kẹt-sync) HOẠT ĐỘNG → bot tự chữa WS.
Nếu Forbidden → token có rule nhưng bị plan-gate (như token cũ tối 13/10).
An toàn: bot open=0, vị thế + TP sống bên broker, bot tự reconnect sau khi terminal về.

Chạy:  cd XAU_SCALP5 && SSL_CERT_FILE=$PWD/.venv/lib/python3.12/site-packages/certifi/cacert.pem \
           ./.venv/bin/python _test_env_admin.py
"""
import os, time, asyncio
from dotenv import load_dotenv

load_dotenv(os.path.join(os.getcwd(), ".env"))
os.environ.setdefault("SSL_CERT_FILE",
                      os.path.join(os.getcwd(), ".venv/lib/python3.12/site-packages/certifi/cacert.pem"))
TOK = os.environ["METAAPI_TOKEN"]
ACCT = os.environ.get("ACCOUNT_ID", "b7a150a8-431e-45a0-9e73-265fb52163bb")


async def main():
    from metaapi_cloud_sdk import MetaApi
    api = MetaApi(TOK)
    t0 = time.time()
    acc = await asyncio.wait_for(api.metatrader_account_api.get_account(ACCT), 30)
    print("REST OK: state=%s conn=%s" % (acc.state, acc.connection_status))
    try:
        await asyncio.wait_for(acc.undeploy(), 60)
        print("UNDEPLOY OK (%.0fs) — QUYEN ADMIN CO" % (time.time() - t0))
    except Exception as e:
        print("UNDEPLOY FAIL (%s): %s — token .env KHONG co quyen admin (plan-gate?)"
              % (type(e).__name__, str(e)[:150]))
        return
    try:
        await asyncio.wait_for(acc.deploy(), 60)
        await asyncio.wait_for(acc.wait_connected(), 120)
        print("DEPLOY+WAIT OK (%.0fs) — terminal da reset; bot se tu LIVE lai trong 1-3p" % (time.time() - t0))
    except Exception as e:
        print("DEPLOY/WAIT FAIL (%s): %s" % (type(e).__name__, str(e)[:150]))


if __name__ == "__main__":
    asyncio.run(main())
