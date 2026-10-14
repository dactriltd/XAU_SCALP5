"""Probe: can this plan undeploy+deploy the account (redeploy-perm denied)?
Pure RPC (no streaming). Time-boxed. Positions/TPs are broker-side → safe."""
import asyncio, os, sys
from dotenv import load_dotenv

load_dotenv()

async def main():
    from metaapi_cloud_sdk import MetaApi
    api = MetaApi(os.environ["METAAPI_TOKEN"])
    account = await asyncio.wait_for(
        api.metatrader_account_api.get_account(os.environ["ACCOUNT_ID"]),
        timeout=20,
    )
    print(f"BEFORE: state={account.state} conn={account.connection_status} region={account.region}")

    try:
        await asyncio.wait_for(account.undeploy(), timeout=30)
        print("UNDEPLOY OK")
    except Exception as e:
        print(f"UNDEPLOY FAIL: {type(e).__name__}: {str(e)[:220]}")
        return

    try:
        await asyncio.wait_for(account.deploy(), timeout=30)
        print("DEPLOY OK")
    except Exception as e:
        print(f"DEPLOY FAIL: {type(e).__name__}: {str(e)[:220]}")
        return

    try:
        await asyncio.wait_for(account.wait_connected(90), timeout=100)
        print(f"WAIT_CONNECTED OK, state={account.state}")
    except Exception as e:
        print(f"WAIT_CONNECTED FAIL: {type(e).__name__}: {str(e)[:150]}")

asyncio.run(main())
