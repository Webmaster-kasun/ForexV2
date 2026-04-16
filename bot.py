"""
bot.py — GBP/USD Multi-Session Scalp Bot

Sessions (SGT):
  06:00 – 08:00  Asian Pre-London
  07:00 – 13:00  London Open      (overlaps 07:00–08:00 with Asian; London takes priority)
  15:00 – 19:00  NY Overlap
  19:00 – 23:00  Late NY

Rules:
  - Max 4 trades per day
  - Max 1 trade per session window
  - Spread, ATR, trend, breakout and pullback must all align before entry
"""

import logging
from datetime import datetime
import pytz
import signals
import config
from oanda_trader   import OandaTrader
from telegram_alert import TelegramAlert

log   = logging.getLogger(__name__)
sg_tz = pytz.timezone("Asia/Singapore")

# Single source of truth — mirrors config.SESSIONS exactly
ASSETS = {
    "GBP_USD": {
        "sessions": [
            {"name": "Asian Pre-London", "start": 6,  "end": 8,  "max_spread": 1.8},
            {"name": "London Open",      "start": 7,  "end": 13, "max_spread": 2.0},
            {"name": "NY Overlap",       "start": 15, "end": 19, "max_spread": 2.2},
            {"name": "Late NY",          "start": 19, "end": 23, "max_spread": 2.5},
        ],
        "sl_pips":    13,
        "tp_pips":    26,
        "max_trades": 4,
    }
}


def is_in_session(hour, asset_cfg):
    """Return True if hour falls inside any session window. Used by main.py."""
    for s in asset_cfg["sessions"]:
        if s["start"] <= hour < s["end"]:
            return True
    return False


def _active_session(hour, asset_cfg):
    """
    Return the matching session dict, or None if outside all windows.
    London Open takes priority over Asian Pre-London in the 07:00–08:00 overlap
    because sessions are ordered by priority (London listed second, but we
    iterate in order and break on first match — so Asian wins 06:00–07:00,
    London wins 07:00–08:00 only if we reorder).

    To give London priority in the overlap we sort so that the wider/later
    window (London, start=7) is checked before Asian (start=6) only during
    the overlap hour. Simplest correct approach: iterate all sessions and
    prefer the one with the later start time when multiple match.
    """
    candidates = [s for s in asset_cfg["sessions"] if s["start"] <= hour < s["end"]]
    if not candidates:
        return None
    # Among overlapping sessions prefer the one with the latest start (most specific)
    return max(candidates, key=lambda s: s["start"])


def evaluate(df_h1, df_m15, df_m5, spread, active_session):
    """
    Run every signal gate in order. Return (direction, reason).
    direction is "BUY" / "SELL" on success, None on any failure.
    """
    if spread > active_session["max_spread"]:
        return None, f"High spread ({spread:.1f} > {active_session['max_spread']})"

    if not signals.check_atr(df_m15):
        return None, "Low volatility (ATR below threshold)"

    trend = signals.check_trend(df_h1)
    if not trend:
        return None, "No trend (EMA20 == EMA50)"

    breakout = signals.check_breakout(df_m15)
    if breakout != trend:
        return None, f"No breakout in trend direction (breakout={breakout}, trend={trend})"

    entry = signals.check_pullback(df_m5, trend)
    if entry != trend:
        return None, f"No pullback confirmation (got {entry}, need {trend})"

    return trend, "VALID"


def run_bot(state):
    """Called every 5 minutes by main.py."""
    instrument = "GBP_USD"
    asset_cfg  = ASSETS[instrument]

    now  = datetime.now(sg_tz)
    hour = now.hour

    # Determine active session
    session = _active_session(hour, asset_cfg)
    if not session:
        log.info(f"[{instrument}] Outside all sessions ({hour:02d}:xx SGT) — skipping")
        return

    # Daily trade cap
    trades_today = state.get("trades", 0)
    if trades_today >= asset_cfg["max_trades"]:
        log.info(f"[{instrument}] Max {asset_cfg['max_trades']} trades reached today — skipping")
        return

    # One trade per session window per day
    window_key   = f"{instrument}_{session['name']}"
    windows_used = state.setdefault("windows_used", {})
    if windows_used.get(window_key):
        log.info(f"[{instrument}] Window '{session['name']}' already traded today — skipping")
        return

    try:
        trader = OandaTrader(demo=True)
        if not trader.login():
            log.warning(f"[{instrument}] OANDA login failed")
            return

        if trader.get_position(instrument):
            log.info(f"[{instrument}] Position already open — skipping")
            return

        mid, bid, ask = trader.get_price(instrument)
        if mid is None:
            log.warning(f"[{instrument}] Could not fetch price")
            return

        spread_pips = round((ask - bid) / 0.0001, 1)
        log.info(
            f"[{instrument}] Price={mid:.5f}  Spread={spread_pips:.1f}pip"
            f"  Session={session['name']}"
        )

        df_h1  = trader.get_candles(instrument, "H1",  120)
        df_m15 = trader.get_candles(instrument, "M15", 80)
        df_m5  = trader.get_candles(instrument, "M5",  60)

        if df_h1 is None or df_m15 is None or df_m5 is None:
            log.warning(f"[{instrument}] Candle fetch failed — skipping")
            return

        direction, reason = evaluate(df_h1, df_m15, df_m5, spread_pips, session)

        if direction is None:
            log.info(f"[{instrument}] No signal — {reason}")
            return

        balance  = trader.get_balance()
        risk_amt = balance * (config.RISK["risk_per_trade"] / 100.0)
        sl_pips  = asset_cfg["sl_pips"]
        tp_pips  = asset_cfg["tp_pips"]
        size     = max(1000, int((risk_amt / sl_pips) * 10000))
        size     = min(size, 50000)

        log.info(
            f"[{instrument}] >>> {direction}"
            f" | Session={session['name']}"
            f" | SL={sl_pips}p TP={tp_pips}p size={size}"
        )

        result = trader.place_order(
            instrument     = instrument,
            direction      = direction,
            size           = size,
            stop_distance  = sl_pips,
            limit_distance = tp_pips,
        )

        if result.get("success"):
            state["trades"]          = trades_today + 1
            windows_used[window_key] = True
            log.info(f"[{instrument}] ✅ Trade placed! ID={result.get('trade_id', '?')}")

            TelegramAlert().send(
                f"✅ Trade Opened!\n"
                f"Pair:      GBP/USD\n"
                f"Direction: {direction}\n"
                f"Session:   {session['name']}\n"
                f"SL: {sl_pips} pip | TP: {tp_pips} pip\n"
                f"Size:      {size} units\n"
                f"Balance:   ${balance:.2f}\n"
                f"Time:      {now.strftime('%H:%M SGT')}"
            )
        else:
            log.error(f"[{instrument}] ❌ Order failed: {result.get('error')}")

    except Exception as e:
        log.error(f"[{instrument}] run_bot error: {e}", exc_info=True)
