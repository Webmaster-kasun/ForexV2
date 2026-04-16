"""
signals.py — Signal checks for GBP/USD scalp bot

FIXES:
  FIX-01: check_pullback threshold raised 0.0010 → 0.0025
  FIX-02: check_pullback body ratio loosened 0.35 → 0.25
  FIX-03: check_atr min_atr lowered 0.0005 → 0.0003
  FIX-04: check_breakout now uses a HISTORICAL window (bars -15 to -5)
           so a trending market does not permanently block the signal.
           Secondary EMA8/EMA21 continuation entry added for smooth trend days.
  FIX-05: check_trend uses dual EMA (EMA20 > EMA50) — stable in all conditions
"""


def check_trend(df_h1):
    """
    BUY  if EMA20 > EMA50 (uptrend).
    SELL if EMA20 < EMA50 (downtrend).
    Returns None only when EMAs are exactly equal (extremely rare).
    """
    ema20 = df_h1["close"].ewm(span=20).mean().iloc[-1]
    ema50 = df_h1["close"].ewm(span=50).mean().iloc[-1]

    if ema20 > ema50:
        return "BUY"
    elif ema20 < ema50:
        return "SELL"
    return None


def check_breakout(df_m15):
    """
    Two-mode breakout detector:

    Mode 1 — Classic breakout:
        Close above the HIGH of bars[-15:-5] → BUY
        Close below the LOW  of bars[-15:-5] → SELL
        Uses a confirmed historical window so a trending market (where the
        rolling high keeps rising with price) does not permanently block entry.

    Mode 2 — Trend continuation (catches smooth trend days with no breakout):
        If price is within 20 pips of M15 EMA21 AND EMA8 > EMA21 → BUY
        If price is within 20 pips of M15 EMA21 AND EMA8 < EMA21 → SELL
    """
    if len(df_m15) < 20:
        return None

    hist_high = df_m15["high"].iloc[-15:-5].max()
    hist_low  = df_m15["low"].iloc[-15:-5].min()
    close     = df_m15["close"].iloc[-1]

    if close > hist_high:
        return "BUY"
    if close < hist_low:
        return "SELL"

    # Continuation mode — price riding EMA21 in a trending M15
    ema8  = df_m15["close"].ewm(span=8).mean().iloc[-1]
    ema21 = df_m15["close"].ewm(span=21).mean().iloc[-1]

    if abs(close - ema21) < 0.0020:
        if ema8 > ema21:
            return "BUY"
        if ema8 < ema21:
            return "SELL"

    return None


def check_pullback(df_m5, direction):
    """
    Price pulled back toward M5 EMA21 and printed a decisive candle.

    Conditions:
      - Price within 25 pips of EMA21
      - Candle body is at least 25% of total range
      - Candle body direction matches the trend direction
    """
    if len(df_m5) < 22:
        return None

    ema21  = df_m5["close"].ewm(span=21).mean().iloc[-1]
    candle = df_m5.iloc[-1]
    close  = candle["close"]
    open_  = candle["open"]
    high   = candle["high"]
    low    = candle["low"]

    diff  = abs(close - ema21)
    body  = abs(close - open_)
    total = high - low

    if diff > 0.0025:
        return None

    if total == 0 or (body / total) < 0.25:
        return None

    # Candle body must point in the right direction
    if direction == "BUY"  and close > open_:
        return "BUY"
    if direction == "SELL" and close < open_:
        return "SELL"

    return None


def check_atr(df_m15):
    """
    Volatility gate — skip if market is dead flat.
    14-bar ATR on M15 must exceed 0.0003 (3 pips).
    """
    if len(df_m15) < 15:
        return False
    atr = (df_m15["high"] - df_m15["low"]).rolling(14).mean().iloc[-1]
    return atr > 0.0003
