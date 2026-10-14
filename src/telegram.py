"""TelegramNotifier — Async, fire-and-forget alerts via Telegram Bot API.

Design (chốt 2026-08-07):
- Async queue + worker task: enqueue() KHÔNG bao giờ block luồng 1Hz
  (loop chỉ put vào queue, worker gửi HTTP riêng).
- httpx.AsyncClient với timeout giới hạn — không giữ event loop lâu.
- HTTP 429 (Too Many Requests): retry 1 lần với Retry-After (mặc định 30s).
- HTML escape toàn bộ text → không phá parse_mode="HTML".
- Fire-and-forget: lỗi gửi chỉ log WARNING, không raise (không làm chết 1Hz loop).

Trade event formatters + report builders (2026-08-08):
- format_swing(), format_startup(), format_status(), format_trade_open(), format_partial_close(), format_trade_closed()

Usage:
    notifier = TelegramNotifier(token, chat_id)
    await notifier.start()
    notifier.enqueue("hello")          # non-blocking
    await notifier.stop()
"""
import asyncio
import html
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import httpx

logger = logging.getLogger("XAU_NOTIFY")

CommandHandler = Callable[[str], Awaitable[Optional[str]]]


class TelegramNotifier:
    """Async notifier with bounded queue (drop-oldest when full)."""

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        timeout_sec: float = 5.0,
        queue_max: int = 50,
        max_429_retries: int = 1,
        enable_commands: bool = True,
        poll_interval: float = 2.0,
    ):
        if not bot_token or not chat_id:
            raise ValueError("TelegramNotifier requires bot_token + chat_id")
        self._token = bot_token
        self._chat_id = chat_id
        self._timeout = timeout_sec
        self._queue_max = queue_max
        self._max_429_retries = max_429_retries
        self._enable_commands = enable_commands
        self._poll_interval = poll_interval

        self._client = httpx.AsyncClient(timeout=timeout_sec)
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_max)
        self._worker: Optional[asyncio.Task] = None
        self._poller: Optional[asyncio.Task] = None
        self._started = False
        self._send_count = 0
        self._drop_count = 0
        self._last_update_id: int = 0
        self._command_handler: Optional[CommandHandler] = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def set_command_handler(self, handler: CommandHandler) -> None:
        """Register async handler: command_text -> response_text | None."""
        self._command_handler = handler

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._worker = asyncio.create_task(self._worker_loop(), name="telegram-worker")
        if self._enable_commands:
            self._poller = asyncio.create_task(self._poll_loop(), name="telegram-poller")

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        if self._poller:
            self._poller.cancel()
            try:
                await self._poller
            except asyncio.CancelledError:
                pass
        # Drain queue before exit so pending alerts still go out
        while not self._queue.empty():
            text = self._queue.get_nowait()
            try:
                await self._send_message(text)
            except Exception as e:
                logger.warning(f"[TELEGRAM] Failed draining alert: {e}")
            self._queue.task_done()
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        await self._client.aclose()

    # ── public API (fire-and-forget) ───────────────────────────────────────

    def enqueue(self, text: str) -> None:
        """Non-blocking. Drop oldest if queue full (keep newest alerts)."""
        if not self._started:
            logger.debug("[TELEGRAM] enqueue before start — dropping")
            self._drop_count += 1
            return
        try:
            self._queue.put_nowait(text)
        except asyncio.QueueFull:
            try:
                self._queue.get_nowait()  # drop oldest
                self._drop_count += 1
                self._queue.put_nowait(text)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                self._drop_count += 1

    # ── command polling ────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Long-poll Telegram getUpdates, dispatch commands to handler."""
        url = f"https://api.telegram.org/bot{self._token}/getUpdates"
        while True:
            try:
                payload = {"offset": self._last_update_id + 1, "timeout": 30}
                resp = await self._client.post(url, json=payload, timeout=35.0)
                if resp.status_code != 200:
                    await asyncio.sleep(self._poll_interval)
                    continue
                data = resp.json()
                if not data.get("ok"):
                    await asyncio.sleep(self._poll_interval)
                    continue
                for update in data.get("result", []):
                    self._last_update_id = update["update_id"]
                    message = update.get("message", {})
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    text = message.get("text", "").strip()
                    if chat_id != self._chat_id or not text:
                        continue
                    cmd = text.split()[0].lower().lstrip("/")
                    response = await self._dispatch_command(cmd)
                    if response:
                        self.enqueue(response)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[TELEGRAM] Poll error: {e}")
                await asyncio.sleep(self._poll_interval)

    async def _dispatch_command(self, cmd: str) -> Optional[str]:
        """Route command to registered handler."""
        if self._command_handler:
            try:
                return await self._command_handler(cmd)
            except Exception as e:
                logger.warning(f"[TELEGRAM] Command handler error: {e}")
                return f"⚠️ Error processing /{cmd}"
        return None

    # ── internals ──────────────────────────────────────────────────────────

    async def _worker_loop(self) -> None:
        while True:
            try:
                text = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._send_message(text)
            except Exception as e:
                logger.warning(f"[TELEGRAM] Send failed: {e}")
            finally:
                self._queue.task_done()

    async def _send_message(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        for attempt in range(self._max_429_retries + 1):
            try:
                resp = await self._client.post(url, json=payload)
            except httpx.HTTPError as e:
                logger.warning(f"[TELEGRAM] HTTP error: {e}")
                return
            if resp.status_code == 200:
                self._send_count += 1
                return
            if resp.status_code == 429 and attempt < self._max_429_retries:
                retry_after = 30.0
                try:
                    ra = resp.json().get("parameters", {}).get("retry_after")
                    if ra:
                        retry_after = float(ra)
                except Exception:
                    pass
                logger.warning(f"[TELEGRAM] 429 — retry in {retry_after:.0f}s")
                await asyncio.sleep(min(retry_after, 30.0))
                continue
            # Non-429 or retries exhausted — log and drop (fire-and-forget)
            logger.warning(
                f"[TELEGRAM] API {resp.status_code}: {resp.text[:200]}"
            )
            return

    @staticmethod
    def esc(value: object) -> str:
        """HTML-escape arbitrary value — safe for parse_mode='HTML'."""
        return html.escape(str(value), quote=False)

    # ── message builders ───────────────────────────────────────────────────

    @staticmethod
    def format_swing(symbol: str, swing) -> str:
        arrow = "🔻" if swing.swing_type.value == "low" else "🔺"
        return (
            f"<b>{TelegramNotifier.esc(symbol)}</b> {arrow} "
            f"SWING {TelegramNotifier.esc(swing.swing_type.value.upper())}\n"
            f"Price: <code>{swing.price:.2f}</code>\n"
            f"Phase: <b>{TelegramNotifier.esc(swing.phase.value)}</b> · "
            f"Strength: {swing.strength:.1f}"
        )

    @staticmethod
    def format_startup(symbols: list[str]) -> str:
        return (
            f"🤖 <b>XAU Bot online</b>\n"
            f"Symbols: {', '.join(TelegramNotifier.esc(s) for s in symbols)}\n"
            f"Mode: Live 24/5 (Demo)"
        )

    # ── trade event formatters (Order Lifecycle) ─────────────────────────

    @staticmethod
    def format_trade_open(intent) -> str:
        """TRADE_OPEN: Institutional HFT format."""
        side_emoji = "🟢" if intent.side == "BUY" else "🔴"
        strategy = intent.metadata.get("strategy", "N/A")
        return (
            f"{side_emoji} <b>NEW {intent.side} ENTRY</b> | <code>{intent.symbol}</code>\n"
            f"<code>{'━' * 28}</code>\n"
            f"💰 <b>Price:</b> <code>{intent.entry_price:.2f}</code>  | "
            f"<b>Vol:</b> <code>{intent.lot_size:.2f}</code>\n"
            f"📊 <b>Strategy:</b> {TelegramNotifier.esc(strategy)}\n"
            f"🛑 <b>SL:</b> <code>{intent.sl_price:.2f}</code>  "
            f"🚀 <b>TP:</b> <code>{intent.tp_price:.2f}</code>\n"
            f"<code>{'━' * 28}</code>\n"
            f"💡 <b>Risk:</b> ${intent.risk_amount:.2f}\n"
            f"⏱ {intent.created_at.strftime('%H:%M:%S UTC')}"
        )

    @staticmethod
    def format_partial_close(symbol: str, action: dict, position) -> str:
        """PARTIAL_CLOSE: Institutional HFT format."""
        return (
            f"🟡 <b>PARTIAL CLOSE (50%)</b> | <code>{TelegramNotifier.esc(symbol)}</code>\n"
            f"<code>{'━' * 28}</code>\n"
            f"🎯 <b>Closed Vol:</b> <code>{action.get('lot', 0):.2f}</code>\n"
            f"💵 <b>Locked Profit:</b> +${position.unrealized_pnl:.2f}\n"
            f"🛡️ <b>Status:</b> Moved SL to Entry (Break-even)\n"
            f"   → Position is now <b>RISK-FREE</b>!\n"
            f"<code>{'━' * 28}</code>\n"
            f"⚡ <b>Remaining:</b> <code>{position.lot_size:.2f}</code> lots\n"
            f"⏱ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
        )

    @staticmethod
    def format_trade_closed(symbol: str, position, reason: str, pnl: float = 0.0) -> str:
        """TRADE_CLOSED: Institutional HFT format with MFE/MAE."""
        result_emoji = "💰" if pnl >= 0 else "🩸"
        result_text = "WIN" if pnl >= 0 else "LOSS"
        mfe = getattr(position, 'max_favorable_excursion', 0.0)
        mae = getattr(position, 'max_adverse_excursion', 0.0)
        duration = getattr(position, 'created_at', None)
        duration_str = ""
        if duration:
            secs = int((datetime.now(timezone.utc) - duration).total_seconds())
            duration_str = f"{secs // 60}m {secs % 60}s"
        return (
            f"🏁 <b>TRADE CLOSED</b> | <code>{TelegramNotifier.esc(symbol)}</code> ({position.side})\n"
            f"<code>{'━' * 28}</code>\n"
            f"{result_emoji} <b>Net PnL:</b> {'+' if pnl >= 0 else ''}${pnl:.2f} ({result_text})\n"
            f"📌 <b>Reason:</b> {TelegramNotifier.esc(reason)}\n"
            f"<code>{'━' * 28}</code>\n"
            f"📈 <b>MFE:</b> +${mfe:.2f} (best)\n"
            f"📉 <b>MAE:</b> -${abs(mae):.2f} (worst)\n"
            f"⏱ <b>Duration:</b> {duration_str}\n"
            f"⏱ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
        )

    @staticmethod
    def format_status(orchestrator_status: dict) -> str:
        """STATUS: real-time bot status for /status command."""
        pos = orchestrator_status.get("position")
        kill = "🔴 KILLED" if orchestrator_status.get("killed") else "🟢 ACTIVE"
        lines = [
            f"🤖 <b>XAU Bot Status</b>\n",
            f"Mode: <b>{kill}</b>",
            f"Queue: <code>{orchestrator_status.get('queue_size', 0)}</code>",
            f"Equity: <code>${orchestrator_status.get('equity', 0):.2f}</code>",
        ]
        if pos:
            lines.extend([
                f"<code>{'─' * 32}</code>",
                f"<b>Open Position:</b>",
                f"Side: <b>{pos['side']}</b> | Lot: <code>{pos['lot']:.2f}</code>",
                f"Entry: <code>{pos['entry']:.2f}</code>",
                f"SL: <code>{pos['sl']:.2f}</code> | TP: <code>{pos['tp']:.2f}</code>",
                f"State: <b>{pos['state']}</b>",
            ])
        else:
            lines.append("Position: <i>None</i>")
        return "\n".join(lines)

    @staticmethod
    def format_regime_shift(old, new) -> str:
        """REGIME SHIFT: regime analyzer notifies on regime change.

        Lives in TelegramNotifier (like the other 6 formatters) so the
        anti-drift tests can lock its fields (NOTIF-01, log 2026-08-08).
        """
        emoji_map = {"EARLY_CHOPPY": "🚨", "CHOPPY": "🛡️", "RANGING": "📊", "TRENDING": "📈"}
        emoji = emoji_map.get(new.active_regime, "⚡")
        return (
            f"{emoji} <b>Regime Shift</b>\n"
            f"{old.active_regime} → <b>{new.active_regime}</b>\n"
            f"Action: <code>{new.action}</code>\n"
            f"Churn(30m): {new.metrics.get('churn_30m', 0):.1f} | "
            f"Cancel(15m): {new.metrics.get('cancel_rate_15m', 0):.2f} | "
            f"ATR Trend: {new.metrics.get('atr_trend', 1):.2f}"
        )
