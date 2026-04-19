"""
strategy.py
===========
Asian Range Breakout + Liquidity Sweep strategy for GBP/USD.

STRATEGY LOGIC
──────────────
Step 1 — Asian Range (00:00–06:00 London Time)
  Calculate Asian High and Asian Low from M15 bars.
  Skip the day if Asian Range ≥ max_asian_range pips.

Step 2 — Liquidity Sweep Detection (06:00 onwards)
  Bearish setup (SELL):
    1. Price is at or near Asian High (buy-side liquidity resting above)
    2. Price breaks BELOW Asian Low during London session (07:00–11:30)
       This signals that sell-side liquidity was swept and the move is real.
    Entry: SELL at breakout below Asian Low.

  Bullish setup (BUY):
    1. Price breaks BELOW Asian Low (sell-side liquidity sweep)
    2. Price returns back INSIDE the Asian range
    3. Price then breaks ABOVE Asian High
    Entry: BUY at breakout above Asian High.

Step 3 — Time Filter
  Signals only accepted: 07:00–11:30 London Time.

Step 4 — Trend Filter (optional, default ON)
  Only trade in direction of H1 EMA20 vs EMA50.

Step 5 — Risk Management
  Default: TP = 30 pips, SL = 20 pips (RR = 1.5:1)
  Optimised: TP = 35 pips, SL = 18 pips (RR = 1.94:1)

Step 6 — One trade per day maximum.
"""

import pandas as pd
import numpy as np

PIP = 0.0001


def compute_asian_range(day_bars: pd.DataFrame) -> tuple:
    """
    Compute Asian session High and Low from M15 bars.

    Filters bars between 00:00–06:00 London time.
    Returns: (asian_high, asian_low, asian_range_pips)
    Returns (None, None, None) if insufficient bars.
    """
    hours = day_bars.index.hour + day_bars.index.minute / 60
    asian = day_bars[hours < 6]

    if len(asian) < 8:    # need at least 2 hours of M15 bars
        return None, None, None

    ah = round(asian['high'].max(), 5)
    al = round(asian['low'].min(), 5)
    ar = round((ah - al) / PIP, 1)
    return ah, al, ar


def check_trend_filter(h1_bars: pd.DataFrame) -> str | None:
    """
    Optional H1 trend filter using EMA20 vs EMA50.
    Returns 'BUY', 'SELL', or None (no clear trend).
    Requires at least 60 H1 bars.
    """
    if len(h1_bars) < 60:
        return None
    ema20 = h1_bars['close'].ewm(span=20).mean().iloc[-1]
    ema50 = h1_bars['close'].ewm(span=50).mean().iloc[-1]
    if ema20 > ema50:
        return 'BUY'
    elif ema20 < ema50:
        return 'SELL'
    return None


def scan_for_signal(day_bars: pd.DataFrame,
                    asian_high: float,
                    asian_low: float,
                    tp_pips: float = 30,
                    sl_pips: float = 20,
                    trend_bias: str = None) -> dict | None:
    """
    Scan London window (07:00–11:30) for a liquidity sweep signal.

    Args:
        day_bars:    All M15 bars for the day
        asian_high:  Asian session high price
        asian_low:   Asian session low price
        tp_pips:     Take profit in pips
        sl_pips:     Stop loss in pips
        trend_bias:  'BUY', 'SELL', or None (no filter)

    Returns:
        Trade signal dict or None if no signal triggered.
    """
    hours       = day_bars.index.hour + day_bars.index.minute / 60
    london_bars = day_bars[(hours >= 7) & (hours < 11.5)]

    if len(london_bars) == 0:
        return None

    swept_below = False   # price broke below Asian Low
    swept_above = False   # price broke above Asian High

    for ts, bar in london_bars.iterrows():

        # ── Track sweep events ─────────────────────────────────────────
        if bar['low'] < asian_low:
            swept_below = True
        if bar['high'] > asian_high:
            swept_above = True

        # After a sweep below, watch for recovery back inside range
        if swept_below and asian_low <= bar['close'] <= asian_high:
            swept_below = 'recovered'

        # After a sweep above, watch for recovery back inside range
        if swept_above and asian_low <= bar['close'] <= asian_high:
            swept_above = 'recovered'

        # ── SELL signal ────────────────────────────────────────────────
        # Classic: bar breaks below Asian Low (direct breakdown)
        # OR: price swept above AH first (buy-side swept), then breaks AL
        if bar['low'] < asian_low:
            if trend_bias in (None, 'SELL'):
                ep     = round(asian_low - 0.5 * PIP, 5)
                sl_px  = round(ep + sl_pips * PIP, 5)
                tp_px  = round(ep - tp_pips * PIP, 5)
                return _build_signal(ts, 'SELL', ep, sl_px, tp_px,
                                     asian_high, asian_low, tp_pips, sl_pips)

        # ── BUY signal (full sweep confirmation) ───────────────────────
        # Only valid if price first swept below AL (grabbed sell-side liquidity)
        # then recovered, then breaks above AH
        if swept_below == 'recovered' and bar['high'] > asian_high:
            if trend_bias in (None, 'BUY'):
                ep    = round(asian_high + 0.5 * PIP, 5)
                sl_px = round(ep - sl_pips * PIP, 5)
                tp_px = round(ep + tp_pips * PIP, 5)
                return _build_signal(ts, 'BUY', ep, sl_px, tp_px,
                                     asian_high, asian_low, tp_pips, sl_pips)

    return None


def _build_signal(ts, direction, ep, sl_px, tp_px,
                  asian_high, asian_low, tp_pips, sl_pips) -> dict:
    return {
        'entry_time':  ts,
        'entry_price': ep,
        'direction':   direction,
        'stop_loss':   sl_px,
        'take_profit': tp_px,
        'asian_high':  round(asian_high, 5),
        'asian_low':   round(asian_low, 5),
        'asian_range': round((asian_high - asian_low) / PIP, 1),
        'sl_pips':     sl_pips,
        'tp_pips':     tp_pips,
    }


def simulate_exit(signal: dict, bars_after_entry: pd.DataFrame) -> dict:
    """
    Simulate trade exit by scanning M15 bars after entry.

    On each bar checks whether SL or TP was hit.
    Worst-case assumption on ambiguous bars:
      - BUY: checks Low first (SL), then High (TP)
      - SELL: checks High first (SL), then Low (TP)

    Returns the signal dict with exit fields added.
    """
    direction = signal['direction']
    sl        = signal['stop_loss']
    tp        = signal['take_profit']

    for ts, bar in bars_after_entry.iterrows():
        if direction == 'BUY':
            if bar['low']  <= sl:
                return {**signal, 'exit_time': ts, 'exit_price': sl,
                        'result': 'LOSS', 'pips': -signal['sl_pips']}
            if bar['high'] >= tp:
                return {**signal, 'exit_time': ts, 'exit_price': tp,
                        'result': 'WIN',  'pips': signal['tp_pips']}
        else:  # SELL
            if bar['high'] >= sl:
                return {**signal, 'exit_time': ts, 'exit_price': sl,
                        'result': 'LOSS', 'pips': -signal['sl_pips']}
            if bar['low']  <= tp:
                return {**signal, 'exit_time': ts, 'exit_price': tp,
                        'result': 'WIN',  'pips': signal['tp_pips']}

    # End of data — force close at last bar's close
    last = bars_after_entry.iloc[-1]
    raw  = (last['close'] - signal['entry_price']) / PIP
    if direction == 'SELL':
        raw = -raw
    result = 'WIN' if raw > 0 else 'LOSS'
    return {**signal, 'exit_time': bars_after_entry.index[-1],
            'exit_price': round(last['close'], 5),
            'result': result, 'pips': round(raw, 1)}
