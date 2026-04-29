"""
signals.py — Multi-Pair Signal Engine
======================================

Two strategies:

1. TRIPLE EMA MOMENTUM  (GBP/USD, AUD/USD)
   - EMA5 / EMA10 / EMA20 must all be aligned
   - ATR gate ≥ 5 pips on M15
   - Direction: SELL in downtrend, BUY in uptrend

2. FOUR-LAYER ENGINE  (EUR/USD)
   - L0: H4 EMA50 macro trend
   - L1: H1 dual EMA alignment
   - L2: M15 impulse candle break (saved to state, checked next scan)
   - L3: M5 EMA13 pullback + RSI7 confirmation
   - V1: H1 EMA200 veto
   - V2: M30 counter-trend veto
"""

import os
import requests
import logging
from datetime import datetime, timezone
from config import FOUR_LAYER, TRIPLE_EMA

log = logging.getLogger(__name__)


def _fetch_candles(instrument, granularity, count=60):
    api_key  = os.environ.get("OANDA_API_KEY", "")
    base_url = "https://api-fxpractice.oanda.com"
    headers  = {"Authorization": "Bearer " + api_key}
    url      = base_url + "/v3/instruments/" + instrument + "/candles"
    params   = {"count": str(count), "granularity": granularity, "price": "M"}
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 200:
                c = [x for x in r.json()["candles"] if x["complete"]]
                return (
                    [float(x["mid"]["c"]) for x in c],
                    [float(x["mid"]["h"]) for x in c],
                    [float(x["mid"]["l"]) for x in c],
                    [float(x["mid"]["o"]) for x in c],
                )
            log.warning("Candle %s %s HTTP %s", instrument, granularity, r.status_code)
        except Exception as e:
            log.warning("Candle fetch error: %s", e)
    return [], [], [], []


def _ema(data, period):
    if not data:
        return [0.0]
    if len(data) < period:
        return [sum(data) / len(data)] * len(data)
    seed = sum(data[:period]) / period
    emas = [seed] * period
    mult = 2 / (period + 1)
    for p in data[period:]:
        emas.append((p - emas[-1]) * mult + emas[-1])
    return emas


def _rsi(closes, period=7):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))


def _atr(highs, lows, closes, period=14):
    if len(highs) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(highs)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    return sum(trs[-period:]) / period


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 1: TRIPLE EMA MOMENTUM (GBP/USD, AUD/USD)
# ─────────────────────────────────────────────────────────────────────────────

def triple_ema_signal(instrument: str) -> tuple:
    """
    Returns (direction, reason)
    direction: 'BUY' | 'SELL' | None
    """
    PIP       = 0.0001
    min_atr   = TRIPLE_EMA["min_atr_pips"]
    spans     = TRIPLE_EMA["spans"]

    # H1 bars for EMAs
    h1_c, h1_h, h1_l, _ = _fetch_candles(instrument, "H1", 50)
    if len(h1_c) < max(spans) + 5:
        return None, "Not enough H1 data"

    ema5  = _ema(h1_c, spans[0])[-1]
    ema10 = _ema(h1_c, spans[1])[-1]
    ema20 = _ema(h1_c, spans[2])[-1]

    # Triple EMA alignment check
    if ema5 < ema10 < ema20:
        direction = "SELL"
    elif ema5 > ema10 > ema20:
        direction = "BUY"
    else:
        return None, f"EMAs mixed — no trend (EMA5={ema5:.5f} EMA10={ema10:.5f} EMA20={ema20:.5f})"

    # ATR volatility gate on M15
    m15_c, m15_h, m15_l, _ = _fetch_candles(instrument, "M15", 30)
    if len(m15_c) < 15:
        return None, "Not enough M15 data for ATR"

    atr_pips = _atr(m15_h, m15_l, m15_c, 14) / PIP
    if atr_pips < min_atr:
        return None, f"ATR too low ({atr_pips:.1f}p < {min_atr}p)"

    reason = (
        f"Triple EMA {direction} | "
        f"EMA5={ema5:.5f} EMA10={ema10:.5f} EMA20={ema20:.5f} | "
        f"ATR={atr_pips:.1f}p"
    )
    return direction, reason


# ─────────────────────────────────────────────────────────────────────────────
# STRATEGY 2: FOUR-LAYER ENGINE (EUR/USD)
# ─────────────────────────────────────────────────────────────────────────────

def four_layer_signal(instrument: str, state: dict) -> tuple:
    """
    Returns (score, direction, details, layer_breakdown)
    Fires when score >= FOUR_LAYER['signal_threshold'].
    """
    cfg      = FOUR_LAYER
    PIP      = 0.0001
    reasons  = []
    score    = 0

    # ── FIX-A: Check if L2 already fired ─────────────────────────────
    if state is not None:
        pending = state.get("l2_pending_" + instrument, {})
        if pending:
            age_min = (
                datetime.now(timezone.utc) -
                datetime.fromisoformat(pending["timestamp"])
            ).total_seconds() / 60

            if age_min <= cfg["l2_expiry_minutes"]:
                log.info("%s: L2 pending (%s) — checking L3 [%.1f min]",
                         instrument, pending["direction"], age_min)
                return _check_l3(instrument, pending["direction"], 3,
                                 ["(L0+L1+L2 confirmed — checking L3)"], state, cfg)
            else:
                log.info("%s: L2 pending EXPIRED (%.1f min) — resetting", instrument, age_min)
                state.pop("l2_pending_" + instrument, None)

    # ── L0: H4 EMA50 macro trend ──────────────────────────────────────
    h4_c, h4_h, h4_l, _ = _fetch_candles(instrument, "H4", 60)
    if len(h4_c) < 51:
        return 0, "NONE", "Not enough H4 data", {"L0": "⚠️ NO DATA"}

    h4_ema50 = _ema(h4_c, 50)[-1]
    direction = "BUY" if h4_c[-1] > h4_ema50 else "SELL" if h4_c[-1] < h4_ema50 else None
    if not direction:
        return 0, "NONE", "H4 EMA50 flat", {"L0": "❌ FLAT"}
    reasons.append(f"✅ L0 H4 {direction} EMA50={h4_ema50:.5f}")
    score = 1

    # ── ATR veto ──────────────────────────────────────────────────────
    h1_c, h1_h, h1_l, _ = _fetch_candles(instrument, "H1", 60)
    if len(h1_c) < 20:
        return score, "NONE", " | ".join(reasons) + " | No H1 data", {"L0": "✅", "ATR": "⚠️"}

    atr_pip = _atr(h1_h, h1_l, h1_c, 14) / PIP
    if atr_pip < cfg["min_atr_pips"]:
        return score, "NONE", " | ".join(reasons), {
            "L0": "✅ " + direction, "ATR": f"❌ {atr_pip:.1f}p"
        }
    reasons.append(f"✅ ATR={atr_pip:.1f}p")

    # ── L1: H1 dual EMA alignment ─────────────────────────────────────
    h1_ema21 = _ema(h1_c, 21)[-1]
    h1_ema50 = _ema(h1_c, 50)[-1]
    bull_h1  = h1_c[-1] > h1_ema21 > h1_ema50
    bear_h1  = h1_c[-1] < h1_ema21 < h1_ema50

    if (direction == "BUY" and bull_h1) or (direction == "SELL" and bear_h1):
        reasons.append(f"✅ L1 H1 {'BULL' if direction=='BUY' else 'BEAR'}: aligned")
        score = 2
    else:
        return score, "NONE", " | ".join(reasons) + " | L1 H1 EMAs not aligned", {
            "L0": "✅ " + direction, "ATR": "✅", "L1": "❌ NOT ALIGNED"
        }

    # ── L2: M15 impulse candle break ──────────────────────────────────
    m15_c, m15_h, m15_l, m15_o = _fetch_candles(instrument, "M15", 20)
    if len(m15_c) < 8:
        return score, "NONE", " | ".join(reasons) + " | No M15 data", {
            "L0": "✅", "ATR": "✅", "L1": "✅", "L2": "⚠️ NO DATA"
        }

    s_high   = max(m15_h[-6:-1])
    s_low    = min(m15_l[-6:-1])
    lc, lo   = m15_c[-1], m15_o[-1]
    lh, ll   = m15_h[-1], m15_l[-1]
    c_rng    = max(lh - ll, 0.00001)
    buf      = cfg["l2_break_buffer"]

    bull_body = (lc > lo) and ((lc - ll) / c_rng >= 0.50)
    bear_body = (lc < lo) and ((lh - lc) / c_rng >= 0.50)
    bull_brk  = (lc > s_high) and (lc <= s_high + buf) and bull_body
    bear_brk  = (lc < s_low)  and (lc >= s_low - buf)  and bear_body

    if (direction == "BUY" and bull_brk) or (direction == "SELL" and bear_brk):
        reasons.append("✅ L2 M15 break")
        score = 3
        if state is not None:
            state["l2_pending_" + instrument] = {
                "direction": direction,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            reasons.append(f"⏳ L2 confirmed — awaiting L3 (up to {cfg['l2_expiry_minutes']}min)")
            return score, "NONE", " | ".join(reasons), {
                "L0": "✅ " + direction, "ATR": "✅",
                "L1": "✅", "L2": "✅ FIRED — awaiting L3", "L3": "⏳ pending"
            }
    else:
        return score, "NONE", " | ".join(reasons) + " | L2 no M15 impulse", {
            "L0": "✅ " + direction, "ATR": "✅", "L1": "✅", "L2": "❌ NO BREAK"
        }

    return _check_l3(instrument, direction, score, reasons, state, cfg)


def _check_l3(instrument, direction, score_so_far, reasons, state, cfg):
    PIP   = 0.0001
    score = score_so_far

    m5_c, m5_h, m5_l, m5_o = _fetch_candles(instrument, "M5", 50)
    if len(m5_c) < 15:
        return score, "NONE", " | ".join(reasons) + " | No M5 data", {
            "L0": "✅", "ATR": "✅", "L1": "✅", "L2": "✅", "L3": "⚠️ NO DATA"
        }

    ema13  = _ema(m5_c, 13)[-1]
    rsi7   = _rsi(m5_c, 7)
    lc, lo = m5_c[-1], m5_o[-1]
    lh, ll = m5_h[-1], m5_l[-1]
    m5_rng = max(lh - ll, 0.00001)
    tol    = cfg["ema_tol"]
    min_rng = cfg["min_m5_range"]

    bull_body = (lc > lo) and ((lc - ll) / m5_rng >= 0.50) and (m5_rng >= min_rng)
    bear_body = (lc < lo) and ((lh - lc) / m5_rng >= 0.50) and (m5_rng >= min_rng)
    bull_pb   = any(l <= ema13 + tol for l in m5_l[-3:-1])
    bear_pb   = any(h >= ema13 - tol for h in m5_h[-3:-1])
    bull_rsi  = rsi7 < cfg["rsi_buy_max"]
    bear_rsi  = rsi7 > cfg["rsi_sell_min"]

    if (direction == "BUY" and bull_pb and bull_body and bull_rsi) or \
       (direction == "SELL" and bear_pb and bear_body and bear_rsi):
        reasons.append(f"✅ L3 M5 bounce EMA13={ema13:.5f} RSI7={rsi7:.1f}")
        score = 4
    else:
        fails = []
        if direction == "BUY":
            if not bull_pb:   fails.append("no EMA touch")
            if not bull_body: fails.append("weak body")
            if not bull_rsi:  fails.append(f"RSI high ({rsi7:.1f})")
        else:
            if not bear_pb:   fails.append("no EMA touch")
            if not bear_body: fails.append("weak body")
            if not bear_rsi:  fails.append(f"RSI low ({rsi7:.1f})")
        msg = "L3 FAIL — " + ", ".join(fails)
        reasons.append(msg)
        return score, "NONE", " | ".join(reasons), {
            "L0": "✅", "ATR": "✅", "L1": "✅", "L2": "✅", "L3": "❌ " + ", ".join(fails)
        }

    # ── V1: H1 EMA200 veto ────────────────────────────────────────────
    h1_long, _, _, _ = _fetch_candles(instrument, "H1", 210)
    if len(h1_long) >= 200:
        ema200 = _ema(h1_long, 200)[-1]
        if (direction == "BUY" and m5_c[-1] < ema200) or \
           (direction == "SELL" and m5_c[-1] > ema200):
            msg = f"🚫 V1 VETO price vs EMA200={ema200:.5f}"
            reasons.append(msg)
            return score, "NONE", " | ".join(reasons), {
                "L0": "✅", "ATR": "✅", "L1": "✅", "L2": "✅", "L3": "✅", "V1": "❌ EMA200"
            }
        reasons.append(f"✅ V1 EMA200={ema200:.5f} ok")

    # ── V2: M30 counter-trend veto ────────────────────────────────────
    m30_c, m30_h, m30_l, m30_o = _fetch_candles(instrument, "M30", 10)
    if len(m30_c) >= 4:
        ct = 0
        for i in range(-3, 0):
            rng = max(m30_h[i] - m30_l[i], 0.00001)
            if direction == "BUY":
                if (m30_c[i] < m30_o[i]) and ((m30_h[i] - m30_c[i]) / rng >= 0.65):
                    ct += 1
            else:
                if (m30_c[i] > m30_o[i]) and ((m30_c[i] - m30_l[i]) / rng >= 0.65):
                    ct += 1
        if ct >= 3:
            reasons.append("🚫 V2 M30 3/3 counter-trend")
            return score, "NONE", " | ".join(reasons), {
                "L0": "✅", "ATR": "✅", "L1": "✅", "L2": "✅",
                "L3": "✅", "V1": "✅", "V2": "❌ M30 COUNTER"
            }
        reasons.append(f"✅ V2 M30 ok ({ct}/3)")

    if state is not None:
        state.pop("l2_pending_" + instrument, None)

    rsi_str = f"RSI7={rsi7:.1f}"
    return score, direction, " | ".join(reasons), {
        "L0": "✅ H4 " + direction, "ATR": "✅",
        "L1": "✅ H1 stack", "L2": "✅ M15 break",
        "L3": "✅ M5 " + rsi_str, "V1": "✅ EMA200", "V2": "✅ M30",
    }
