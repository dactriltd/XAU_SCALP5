# XAU_SCALP5

Bot scalping XAUUSD (M1+M5) chạy trên MetaApi Cloud (MT5 broker-side TP/SL),
kiểm soát bằng gate xác suất (§14.3) + LVL M1 ladder + S3 constants.

## Kết cấu

| Đường dẫn | Vai trò |
|---|---|
| `main.py` | Boot sequence (ORDER BOOT: RPC warmup → WS + pipeline check → backfill/gap → LIVE loop) + retry backoff `StreamStalled` |
| `src/metaapi_client.py` | MetaApi SDK wrapper: REST/RPC/streaming, RPC warmup 3×, throttle historical ≥5s + 429 `recommendedRetryTime`, guards S4-BOOT |
| `src/lvl.py` | LVL M1 ladder (G2-LVL + R1/R2), M0 gate |
| `src/gap_filler.py` | Gap-fill M1 theo chunk 1000 nến |
| `scalp5_verify.py` | Verify-loop report-only (DB + logs + status) |
| `dashboard_streamlit.py` | Dashboard |
| `STATE.md` | Run-log SOT (triage daily) |
| `docs/`, `skills/` | Tài liệu + skill helpers |
| `.env.example` | Template cấu hình (copy → `.env`; `.env` không bao giờ commit) |

## Chạy

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # điền METAAPI_TOKEN, ACCOUNT_ID, TELEGRAM_*
python main.py
```

Bot live-standby khi MetaApi cloud down: RPC warmup 3× (120+120+60s) →
fail-open NO-TRADE → streaming escalation (1 redeploy/chu kỳ) → backoff
30s→300s → **auto-LIVE khi cloud recover** (DEMO re-confirm + backfill exit_log).

## Nguyên tắc (AGENTS.md)

First-principles · code tối giản (stdlib) · mọi khẳng định phải có evidence
(sanity check / benchmark / log) · 3-strike anti-loop · cao rủi ro = CHỜ NGƯỜI.
