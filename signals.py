"""
signals.py — Signal checks for GBP/USD scalp bot
FIXES:
  FIX-01: check_pullback threshold raised 0.0010 → 0.0025 (10 pip was too tight; GBP/USD
           routinely swings 20–30 pips from EMA21 on valid continuation setups)
  FIX-02: check_pullback body ratio loosened 0.35 → 0.25 (accept doji-continuation candles)
  FIX-03: check_atr min_atr lowered 0.0005 → 0.0003 (allow quieter pre-London periods)
  FIX-04: check_breakout buffer removed entirely (buffer was blocking most breakout confirmations;
           a close above rolling high is sufficient alongside trend + pullback)
  FIX-05: check_trend now uses dual EMA (EMA20 + EMA50 slope) so near-EMA price doesn't
           return None — trend determined by EMA alignment, not just price vs EMA50
"""


def check_trend(df_h1):
    """
    BUY  if EMA20 > EMA50 (uptrend), SELL if EMA20 < EMA50 (downtrend).
    FIX-05: was price > EMA50 — price sitting near EMA50 returned None too often.
    Dual-EMA alignment is more stable and doesn't block trending markets.
    """
    ema20 = df_h1['close'].ewm(span=20).mean().iloc[-1]
    ema50 = df_h1['close'].ewm(span=50).mean().iloc[-1]

    if ema20 > ema50:
        return "BUY"
    elif ema20 < ema50:
        return "SELL"
    return None


def check_breakout(df_m15):
    """
    Price must close above the 10-bar high (BUY) or below the 10-bar low (SELL).
    FIX-04: removed ATR buffer — buffer was preventing valid breakout confirmations.
    """
    high  = df_m15['high'].rolling(10).max().iloc[-2]
    low   = df_m15['low'].rolling(10).min().iloc[-2]
    close = df_m15['close'].iloc[-1]

    if close > high:
        return "BUY"
    elif close < low:
        return "SELL"
    return None


def check_pullback(df_m5, direction):
    """
    Price pulled back toward M5 EMA21 and printed a decisive candle.
    FIX-01: threshold 0.0010 → 0.0025  (25 pips — GBP/USD often retraces 15-25 pips to EMA21)
    FIX-02: body ratio 0.35 → 0.25     (accept more candle shapes; body just needs to dominate)
    """
    ema21 = df_m5['close'].ewm(span=21).mean().iloc[-1]
    price = df_m5['close'].iloc[-1]

    diff = abs(price - ema21)

    if diff < 0.0025:   # FIX-01: was 0.0010
        candle = df_m5.iloc[-1]
        body   = abs(candle['close'] - candle['open'])
        total  = candle['high'] - candle['low']

        if total > 0 and (body / total) > 0.25:   # FIX-02: was 0.35
            return direction

    return None


def check_atr(df_m15):
    """
    Volatility gate — skip if market is dead flat.
    FIX-03: lowered 0.0005 → 0.0003 (0.0005 blocked many valid pre-London setups)
    """
    atr = (df_m15['high'] - df_m15['low']).rolling(14).mean().iloc[-1]
    return atr > 0.0003   # FIX-03: was 0.0005
