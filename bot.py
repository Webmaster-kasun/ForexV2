"""
bot.py — Unified Multi-Pair Trading Bot
=========================================

Pairs & Strategies:
  GBP/USD  Triple EMA Momentum    London 15:00–19:00 SGT
  EUR/USD  4-Layer Signal Engine  London 15:00–19:00 + NY 20:00–00:00 SGT
  AUD/USD  Triple EMA Momentum    Asia 07:00–10:00 + London 15:00–19:00 SGT

Each pair has its own:
  - Session windows
  - Signal strategy
  - TP / SL settings
  - Trade size
  - Independent cooldown and state tracking

Account: SGD
"""

import os
import logging
import requests
from datetime import datetime, timezone
import pytz

from config        import PAIRS, RISK, FOUR_LAYER
from signals       import triple_ema_signal, four_layer_signal
from oanda_trader  import OandaTrader
from telegram_alert import TelegramAlert
from calendar_filter import EconomicCalendar

log   = logging.getLogger(__name__)
sg_tz = pytz.timezone("Asia/Singapore")


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_active_session(hour: int, pair_cfg: dict) -> dict | None:
    for s in pair_cfg["sessions"]:
        if s["start"] <= hour < s["end"]:
            return s
    return None


def set_cooldown(state: dict, key: str):
    state.setdefault("cooldowns", {})[key] = datetime.now(timezone.utc).isoformat()
    log.info("%s cooldown set (30 min)", key)


def in_cooldown(state: dict, key: str) -> bool:
    ts = state.get("cooldowns", {}).get(key)
    if not ts:
        return False
    try:
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 60
        return elapsed < 30
    except Exception:
        return False


def detect_closed_trades(state: dict, trader: OandaTrader, alert: TelegramAlert):
    """Check if any open position closed (TP/SL hit) and send alert."""
    for pair in list(state.get("open_times", {}).keys()):
        if trader.get_position(pair):
            continue
        try:
            url  = (trader.base_url + "/v3/accounts/" + trader.account_id +
                    "/trades?state=CLOSED&instrument=" + pair + "&count=1")
            data = requests.get(url, headers=trader.headers, timeout=10).json().get("trades", [])
            if data:
                trade     = data[0]
                pnl       = float(trade.get("realizedPL", "0"))
                open_px   = float(trade.get("price", 0))
                close_px  = float(trade.get("averageClosePrice", open_px))
                balance   = trader.get_balance()
                cfg       = PAIRS[pair]

                state["daily_pnl"] = state.get("daily_pnl", 0.0) + pnl

                if pnl < 0:
                    set_cooldown(state, pair)
                    state["losses"]        = state.get("losses", 0) + 1
                    state["consec_losses"] = state.get("consec_losses", 0) + 1
                    alert.send_sl_hit(pair, cfg["emoji"], pnl, balance,
                                      state.get("wins", 0), state.get("losses", 0),
                                      open_px, close_px)
                else:
                    state["wins"]          = state.get("wins", 0) + 1
                    state["consec_losses"] = 0
                    alert.send_tp_hit(pair, cfg["emoji"], pnl, balance,
                                      state.get("wins", 0), state.get("losses", 0),
                                      open_px, close_px)
        except Exception as e:
            log.warning("Closed trade detect error %s: %s", pair, e)
        state["open_times"].pop(pair, None)


def session_open_alert(state: dict, alert: TelegramAlert, trader: OandaTrader,
                       now: datetime, today: str):
    """Send session-open alert once per window per day, for each pair."""
    hour = now.hour
    sent = state.setdefault("session_alerted", {})

    for pair, cfg in PAIRS.items():
        for s in cfg["sessions"]:
            if hour == s["start"]:
                key = f"{pair}_{today}_{s['label']}_open"
                if not sent.get(key):
                    sent[key] = True
                    try:
                        balance = trader.get_balance() if trader.login() else 0.0
                    except Exception:
                        balance = 0.0
                    alert.send_session_open(
                        pair=pair, emoji=cfg["emoji"],
                        session_label=s["label"], session_hours=s["hours"],
                        balance=balance,
                        trades_today=state.get("trades", 0),
                        wins=state.get("wins", 0),
                        losses=state.get("losses", 0),
                    )


# ── Main bot loop ──────────────────────────────────────────────────────────────

def run_bot(state: dict):
    now   = datetime.now(sg_tz)
    hour  = now.hour
    today = now.strftime("%Y%m%d")

    alert    = TelegramAlert()
    calendar = EconomicCalendar()

    log.info("Scan at %s SGT", now.strftime("%H:%M:%S"))

    trader = OandaTrader(demo=True)
    if not trader.login():
        log.warning("OANDA login failed")
        return

    balance = trader.get_balance()

    # Session open alerts
    session_open_alert(state, alert, trader, now, today)

    # Check for closed trades (TP/SL hits)
    detect_closed_trades(state, trader, alert)

    # ── Scan each pair ─────────────────────────────────────────────────
    for pair, cfg in PAIRS.items():

        session = get_active_session(hour, cfg)
        if not session:
            log.info("%s: outside session windows (%02d:xx SGT)", pair, hour)
            continue

        # Already has open position
        if trader.get_position(pair):
            log.info("%s: position already open", pair)
            continue

        # Cooldown check
        if in_cooldown(state, pair):
            log.info("%s: in cooldown", pair)
            continue

        # Daily trade limit
        pair_trades = state.get(f"trades_{pair}", 0)
        if pair_trades >= cfg["max_trades"]:
            log.info("%s: max trades reached (%d)", pair, cfg["max_trades"])
            continue

        # Price + spread check
        price, bid, ask = trader.get_price(pair)
        if price is None:
            log.warning("%s: price fetch error", pair)
            continue

        spread = (ask - bid) / cfg["pip"]
        if spread > session["max_spread"] + 0.05:
            log.info("%s: spread %.2fp > %.1fp — skip", pair, spread, session["max_spread"])
            continue

        # News filter
        news_active, news_reason = calendar.is_news_time(pair)
        if news_active:
            nkey = f"{pair}_news_{now.strftime('%Y%m%d%H')}"
            if not state.get("news_alerted", {}).get(nkey):
                state.setdefault("news_alerted", {})[nkey] = True
                alert.send_news_block(pair, cfg["emoji"], news_reason)
            log.info("%s: news block — %s", pair, news_reason)
            continue

        # ── Run signal strategy ────────────────────────────────────────
        strategy = cfg["strategy"]

        if strategy == "triple_ema":
            direction, reason = triple_ema_signal(pair)
            score = 1 if direction else 0
            layer_breakdown = {}
            log.info("%s: triple_ema score=%s dir=%s | %s", pair, score, direction, reason)
            if not direction:
                continue

        elif strategy == "four_layer":
            threshold = FOUR_LAYER["signal_threshold"]
            score, direction, reason, layer_breakdown = four_layer_signal(pair, state)
            log.info("%s: four_layer score=%d/%d dir=%s | %s",
                     pair, score, threshold, direction, reason)
            if score < threshold or direction == "NONE":
                continue

        else:
            log.warning("%s: unknown strategy %s", pair, strategy)
            continue

        # ── Place order ────────────────────────────────────────────────
        sl_pips = cfg["sl_pips"]
        tp_pips = cfg["tp_pips"]
        size    = cfg["trade_size"]

        result = trader.place_order(
            instrument     = pair,
            direction      = direction,
            size           = size,
            stop_distance  = sl_pips,
            limit_distance = tp_pips,
        )

        if result.get("success"):
            state["trades"]              = state.get("trades", 0) + 1
            state[f"trades_{pair}"]      = pair_trades + 1
            state.setdefault("open_times", {})[pair] = now.isoformat()

            log.info("%s: PLACED %s SL=%dp TP=%dp", pair, direction, sl_pips, tp_pips)

            alert.send_trade_open(
                pair          = pair,
                emoji         = cfg["emoji"],
                direction     = direction,
                entry_price   = price,
                sl_pips       = sl_pips,
                tp_pips       = tp_pips,
                size          = size,
                spread        = spread,
                score         = score,
                session_label = session["label"],
                layer_breakdown = layer_breakdown,
                balance       = balance,
                trades_today  = state["trades"],
            )
        else:
            set_cooldown(state, pair)
            log.warning("%s: order failed — %s", pair, result.get("error", ""))

    log.info("Scan complete.")
