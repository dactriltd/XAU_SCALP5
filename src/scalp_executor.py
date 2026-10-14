"""XAU_SCALP5 EXECUTOR — market + TP (KHÔNG SL) · K=2 · recover · daily-loss cap.

0.02 lot = 2 oz → PnL$ ≈ pts × 2.0
Position keys (MetaApi): id, side='buy'/'sell', openPrice, openTime, magic, profit
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("SCALP5")


class ScalpExecutor:
    def __init__(self, client, cfg, oz_per_lot: float = 2.0):
        self.client = client
        self.cfg = cfg
        self.oz = oz_per_lot
        self.positions: List[Dict] = []   # {id, side 'L'/'S', entry, entry_ts, anchor}
        self._tp_last: Dict[str, Optional[float]] = {}  # MOM1 ratchet: TP cuối đã áp dụng per vị thế
        self.day_utc = 0
        self.day_loss = 0.0
        self.halted = False
        # S2: vị thế branch (b) sync() phát hiện broker-đã-đóng (TP fill) → main ghi exit_log
        self.synced_exits: List[Dict] = []

    # ───────────────────── position helpers ─────────────────────
    def _mine(self, p: dict) -> bool:
        try:
            return int(p.get("magic", -1)) == self.cfg.MAGIC
        except (TypeError, ValueError):
            return str(p.get("magic", "")) == str(self.cfg.MAGIC)

    @staticmethod
    def _parse_ts(raw) -> int:
        try:
            return int(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp())
        except Exception:
            return int(datetime.now(timezone.utc).timestamp())

    @staticmethod
    def _pos_side(p: dict):
        """Hướng vị thế từ dict broker → 'L'/'S'/None.
        RPC get_positions KHÔNG có key 'side' — có 'type'='POSITION_TYPE_BUY/SELL'
        (bug 14-10 03:16: p.get('side')=None → mọi vị thế adopt bị đảo thành 'S'
        → pnl_pts đảo dấu → EXIT 'TP' giả chốt LỖ −3.14$). Streaming state có thể
        có 'side'='buy'/'sell' → kiểm tra cả hai."""
        raw = str(p.get("side") or p.get("type") or "").lower()
        if "buy" in raw:
            return "L"
        if "sell" in raw:
            return "S"
        return None

    async def adopt(self) -> None:
        """Recover vị thế MỘC này (magic) sau restart — TP vẫn nằm ở broker."""
        self.positions = []
        for p in await self.client.get_positions() or []:
            if not isinstance(p, dict) or not self._mine(p):
                continue
            side = self._pos_side(p)
            if side is None:
                log.warning(f"[EXEC] adopt: side không nhận diện (side={p.get('side')!r} type={p.get('type')!r}) → skip {p.get('id')} (TP broker vẫn giữ)")
                continue
            entry = float(p.get("openPrice", 0) or 0)
            if not entry:
                continue
            self.positions.append({
                "id": str(p.get("id")),
                "side": side,
                "entry": entry,
                "entry_ts": self._parse_ts(p.get("openTime") or p.get("time") or p.get("brokerTime")),
                "anchor": None,   # không biết S anchor sau restart → bỏ điều kiện S_BREAK
            })
        log.info(f"[EXEC] adopt {len(self.positions)} positions (magic={self.cfg.MAGIC})")

    async def sync(self) -> None:
        """Đối soát broker 2 chiều:
        (a) ADOPT vị thế magic-của-mình MỚI mà enter() đã lỡ track (missed polling)
        (b) Gỡ vị thế không còn open (TP filled bên broker)
        """
        found: Dict[str, dict] = {}
        for p in await self.client.get_positions() or []:
            if isinstance(p, dict) and self._mine(p):
                found[str(p.get("id"))] = p
        # (b)
        for pos in list(self.positions):
            if pos["id"] not in found:
                self.positions.remove(pos)
                pnl_est = self.cfg.TP_POINTS * self.oz * (1 if pos["side"] == "L" else -1)
                self.note_closed(pnl_est, reason="TP_BROKER")
                # S2: expose cho main → ghi exit_log (trước đây không ai log vị thế broker-đóng)
                self.synced_exits.append({"pos_id": pos["id"], "pnl_est": pnl_est, "ts": int(time.time())})
                log.info(f"[EXEC] {pos['id']} đã đóng (TP broker) side={pos['side']} entry={pos['entry']} ≈{pnl_est:+.2f}$")
        # (a)
        known = {x["id"] for x in self.positions}
        for pid, p in found.items():
            if pid in known:
                continue
            side = self._pos_side(p)
            if side is None:
                log.warning(f"[EXEC] RECOVER {pid}: side không nhận diện (side={p.get('side')!r} type={p.get('type')!r}) → skip (TP broker vẫn giữ)")
                continue
            entry = float(p.get("openPrice", 0) or 0)
            if not entry:
                continue
            self.positions.append({
                "id": pid, "side": side, "entry": entry,
                "entry_ts": self._parse_ts(p.get("openTime") or p.get("time") or p.get("brokerTime")), "anchor": None,
            })
            log.warning(f"[EXEC] RECOVER {pid} (enter missed tracking) side={side} entry={entry} → manage lại")

    # ───────────────────── enter / exit ─────────────────────
    async def enter(self, action: dict, strategy) -> bool:
        c = self.cfg
        if self.halted:
            log.warning("[EXEC] halted (daily loss) → skip entry")
            return False
        if len(self.positions) >= c.K_CONTEXT:
            log.warning(f"[EXEC] K={c.K_CONTEXT} full → skip entry")
            return False
        side = 1 if action["kind"] == "ENTER_LONG" else -1
        px = float(action["px"])
        tp = round(px + side * c.TP_POINTS, 2)
        res = await self.client.create_market_order(
            c.SYMBOL, c.LOT, side,
            stop_loss=None,            # NO-SL (design)
            take_profit=tp,
            magic=c.MAGIC,
            comment="SCALP5",
        )
        if not res:
            log.error("[EXEC] create_market_order → no response (thất bại, không retry)")
            return False
        pos = None
        for _ in range(20):
            for p in await self.client.get_positions() or []:
                if (isinstance(p, dict) and self._mine(p)
                        and str(p.get("id")) not in {x["id"] for x in self.positions}):
                    pos = p
                    break
            if pos:
                break
            await asyncio.sleep(0.5)
        entry = float(pos.get("openPrice", 0) or 0) if pos else px
        if pos:
            # FIX 13-10 tối 4 (slippage TP "quá chặt"): TP submit theo px-strategy (tick decide),
            # nhưng FILL (openPrice) lệch theo spread + vận tốc giá (log 20:32: px=4187.14 → fill
            # 4188.528 → TP=4188.64 = +0.11pts thay vì +1.5). Sửa: TP tính theo FILL, modify broker
            # nếu lệch >0.1pts
            tp2 = round(entry + side * c.TP_POINTS, 2)
            if abs(tp2 - tp) > 0.1:
                await self.client.modify_position(str(pos.get("id")), None, tp2)
                log.info(f"[EXEC] TP sửa {tp}→{tp2} (slippage {abs(tp2 - tp):.2f}pts, fill={entry})")
                tp = tp2
            self.positions.append({
                "id": str(pos.get("id")),
                "side": "L" if side == 1 else "S",
                "entry": entry,
                "entry_ts": strategy.now_ts,
                "anchor": action.get("anchor"),
            })
        log.info(
            f"[EXEC] {action['kind']} entry={entry} TP={tp} SL=None anchor={action.get('anchor')} "
            f"T={action.get('touch')} d5m={action.get('drift5m'):+.2f}"
        )
        return bool(pos)

    async def exit(self, pos_id: str, px: float, reason: str) -> Tuple[float, bool]:
        """S2: trả (pnl, ok) thay float.
        ok=True khi close_position thành công HOẶC pos đã không còn ở broker
        (broker-side TP đã đóng → lệnh close vô hại). ok=False CHỈ khi pos vẫn còn
        ở broker mà close fail → main KHÔNG ghi exit_log (vị thế giữ trong
        self.positions → tick kế tiếp retry, không lặp row như CLOSE-FAIL cũ)."""
        pos = next((p for p in self.positions if p["id"] == pos_id), None)
        pnl: Optional[float] = None
        for p in await self.client.get_positions() or []:
            if isinstance(p, dict) and str(p.get("id")) == pos_id and p.get("profit") is not None:
                try:
                    pnl = float(p["profit"])
                except (TypeError, ValueError):
                    pnl = None
                break
        if pnl is None and pos:
            s = 1 if pos["side"] == "L" else -1
            pnl = s * (px - pos["entry"]) * self.oz
        res = await self.client.close_position(pos_id)
        ok = bool(res)
        if not ok:
            # close fail → kiểm tra lại: pos CÒN ở broker không? (TP có thể vừa fill
            # GIỮA HAI LẦN GỌI → vị thế đã không còn → lệnh close vô hại → ok=True)
            still_open = any(
                isinstance(p, dict) and str(p.get("id")) == pos_id
                for p in await self.client.get_positions() or []
            )
            ok = not still_open
        pnl_known = pnl is not None          # giữ semantics cũ: chỉ note_closed khi PnL biết thật
        pnl = pnl if pnl is not None else 0.0
        if ok:
            if pos:
                self.positions.remove(pos)
            if pnl_known:
                self.note_closed(pnl, reason=reason)
            log.info(f"[EXEC] EXIT {pos_id} reason={reason} px={px} pnl={pnl:+.2f}$ OK=True")
        else:
            log.warning(f"[EXEC] EXIT {pos_id} reason={reason} px={px} pnl≈{pnl:+.2f}$ OK=False (pos vẫn ở broker, chưa ghi exit_log)")
        return pnl, ok

    async def apply_tp_updates(self, plan: Dict[str, Optional[float]]) -> None:
        """MOM1 RATCHET (CHAIRMAN 19:xx "lệnh chạy cùng giá"): modify TP broker CHỈ khi thay đổi.
        plan = strategy.tp_plan(positions): {pos_id: new_tp_or_None(None=hủy TP để lệnh chạy tiếp)}."""
        for pid, tp in plan.items():
            if self._tp_last.get(pid, "INIT") == tp:
                continue
            ok = await self.client.modify_position(pid, None, tp)
            self._tp_last[pid] = tp
            log.info(f"[EXEC] RATCHET {pid} TP→{tp} {'OK' if ok else 'FAIL'}")
        live = {p["id"] for p in self.positions}
        for k in [k for k in self._tp_last if k not in live]:
            del self._tp_last[k]

    # ───────────────────── daily loss cap ─────────────────────
    def note_closed(self, pnl: float, reason: str) -> None:
        """Ghi PnL đã thực hiện theo ngày UTC (cap chỉ ảnh hưởng ENTRY)."""
        day = datetime.now(timezone.utc).toordinal()
        if day != self.day_utc:
            self.day_utc, self.day_loss, self.halted = day, 0.0, False
        self.day_loss += pnl

    @property
    def at_daily_cap(self) -> bool:
        return self.day_loss <= -self.cfg.DAILY_LOSS_STOP
