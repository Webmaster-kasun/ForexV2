"""
signals.py — Signal checks for GBP/USD scalp bot
FIXES:
  FIX-01: check_pullback threshold raised 0.0005 → 0.0010 (was almost never triggering)
  FIX-02: check_pullback body ratio loosened 0.45 → 0.35 (was rejecting valid engulfing candles)
  FIX-03: check_atr min_atr lowered 0.0008 → 0.0005 (was blocking trades in early London session)
  FIX-04: check_breakout buffer reduced 0.5×ATR → 0.3×ATR (was too strict — rarely firing with pullback)
"""


def check_trend(df_h1):
    """BUY if price > H1 EMA50, SELL if below."""
    ema50 = df_h1['close'].ewm(span=50).mean().iloc[-1]
    price = df_h1['close'].iloc[-1]

    if price > ema50:
        return "BUY"
    elif price < ema50:
        return "SELL"
    return None


def check_breakout(df_m15):
    """
    Price must break the 10-bar high/low with a 0.3×ATR buffer.
    FIX-04: was 0.5×ATR — too wide, rarely aligned with pullback.
    """
    high  = df_m15['high'].rolling(10).max().iloc[-2]
    low   = df_m15['low'].rolling(10).min().iloc[-2]
    close = df_m15['close'].iloc[-1]

    atr    = (df_m15['high'] - df_m15['low']).rolling(14).mean().iloc[-1]
    buffer = atr * 0.3  # FIX-04

    if close > high + buffer:
        return "BUY"
    elif close < low - buffer:
        return "SELL"
    return None


def check_pullback(df_m5, direction):
    """
    Price pulled back close to M5 EMA21 and printed a decisive candle.
    FIX-01: threshold 0.0005 → 0.0010 (GBP/USD pip is 0.0001; 0.0005 was sub-pip noise)
    FIX-02: body ratio 0.45 → 0.35 (loosened to accept more valid continuation candles)
    """
    ema21 = df_m5['close'].ewm(span=21).mean().iloc[-1]
    price = df_m5['close'].iloc[-1]

    diff = abs(price - ema21)

    if diff < 0.0010:  # FIX-01: was 0.0005
        candle = df_m5.iloc[-1]
        body   = abs(candle['close'] - candle['open'])
        total  = candle['high'] - candle['low']

        if total > 0 and (body / total) > 0.35:  # FIX-02: was 0.45
            return direction

    return None


def check_atr(df_m15):
    """
    Volatility gate — skip if market is dead flat.
    FIX-03: lowered 0.0008 → 0.0005 (early London open often has ATR around 0.0006–0.0007)
    """
    atr = (df_m15['high'] - df_m15['low']).rolling(14).mean().iloc[-1]
    return atr > 0.0005  # FIX-03: was 0.0008
