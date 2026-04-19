"""
data_loader.py
==============
GBP/USD data loading module.

Supports two modes:
  1. CSV file (daily or M5/M15 OHLC) - for backtesting
  2. MetaTrader 5 API              - for live trading

For the Asian Range Breakout strategy, M15 data is ideal.
If only daily OHLC is available, the module synthesises realistic
intraday structure from daily High/Low/Open/Close anchors.
"""

import pandas as pd
import numpy as np
import os


# ─────────────────────────────────────────────────────────────────────────────
# CSV LOADER
# ─────────────────────────────────────────────────────────────────────────────

def load_from_csv(path: str) -> pd.DataFrame:
    """
    Load OHLCV data from a CSV file.

    Accepts both daily bars and intraday (M5/M15) bars.
    Auto-detects the date/datetime column and normalises column names.

    Required columns (case-insensitive): Date/Time, Open, High, Low, Close
    Optional: Volume, Spread

    Returns DataFrame with columns: [open, high, low, close]
    Index: pd.DatetimeIndex (UTC-aware or naive, treated as London time)
    """
    df = pd.read_csv(path)
    df.columns = [c.strip().lower().split()[0] for c in df.columns]

    # Find the datetime column
    date_col = None
    for candidate in ['date', 'time', 'datetime', 'timestamp']:
        if candidate in df.columns:
            date_col = candidate
            break
    if date_col is None:
        raise ValueError(f"No date/time column found. Columns: {list(df.columns)}")

    df[date_col] = pd.to_datetime(df[date_col])
    df = df.set_index(date_col).sort_index()
    df.index.name = 'time'

    # Keep only OHLC
    needed = ['open', 'high', 'low', 'close']
    for col in needed:
        if col not in df.columns:
            raise ValueError(f"Missing column: {col}")

    df = df[needed].astype(float)
    df = df[df['high'] != df['low']]   # drop zero-range bars
    df = df.dropna()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# MT5 LOADER
# ─────────────────────────────────────────────────────────────────────────────

def load_from_mt5(symbol: str = 'GBPUSD',
                  timeframe_str: str = 'M15',
                  start: str = '2026-01-01',
                  end: str = None) -> pd.DataFrame:
    """
    Load OHLCV data from MetaTrader 5.

    Requires: MetaTrader 5 desktop installed and running.
    Install MT5 Python package: pip install MetaTrader5

    Args:
        symbol:        MT5 symbol (e.g. 'GBPUSD')
        timeframe_str: '1min', '5min', '15min', '1H', '4H', '1D'
        start:         start date string YYYY-MM-DD
        end:           end date string YYYY-MM-DD (default: today)

    Returns DataFrame with columns: [open, high, low, close]
    Index: pd.DatetimeIndex
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise ImportError(
            "MetaTrader5 package not installed.\n"
            "Run: pip install MetaTrader5\n"
            "MT5 terminal must also be open and logged in."
        )

    tf_map = {
        '1min': mt5.TIMEFRAME_M1,   '5min':  mt5.TIMEFRAME_M5,
        '15min': mt5.TIMEFRAME_M15, '30min': mt5.TIMEFRAME_M30,
        '1h':   mt5.TIMEFRAME_H1,   '4h':    mt5.TIMEFRAME_H4,
        '1d':   mt5.TIMEFRAME_D1,
        'M1': mt5.TIMEFRAME_M1,  'M5':  mt5.TIMEFRAME_M5,
        'M15': mt5.TIMEFRAME_M15,'M30': mt5.TIMEFRAME_M30,
        'H1':  mt5.TIMEFRAME_H1, 'H4':  mt5.TIMEFRAME_H4,
        'D1':  mt5.TIMEFRAME_D1,
    }
    tf = tf_map.get(timeframe_str, mt5.TIMEFRAME_M15)

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialise failed: {mt5.last_error()}")

    from datetime import datetime
    dt_start = datetime.strptime(start, '%Y-%m-%d')
    dt_end   = datetime.strptime(end, '%Y-%m-%d') if end else datetime.now()

    rates = mt5.copy_rates_range(symbol, tf, dt_start, dt_end)
    mt5.shutdown()

    if rates is None or len(rates) == 0:
        raise ValueError(f"No data returned for {symbol} {timeframe_str} {start}–{end}")

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.set_index('time')[['open', 'high', 'low', 'close']]
    df = df[df['high'] != df['low']].dropna()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# DAILY → INTRADAY SYNTHESISER  (fallback when only daily data is available)
# ─────────────────────────────────────────────────────────────────────────────

def synthesise_m15_from_daily(daily: pd.DataFrame, seed: int = 2026) -> pd.DataFrame:
    """
    Synthesise M15 bars from daily OHLC data.

    Produces realistic intraday price structure:
      00:00–06:00 LDN: Asian session — confined range (~30% of daily)
      06:00–07:00 LDN: Pre-London — slight expansion
      07:00–12:00 LDN: London open — main directional move
      12:00–17:00 LDN: NY overlap — continuation or retracement
      17:00–00:00 LDN: Late session — drift back to close

    Used for backtesting when only daily OHLC is available.
    For production, always use real intraday data from MT5 or CSV.
    """
    rng      = np.random.default_rng(seed)
    all_rows = []
    PIP      = 0.0001

    for ts_day, row in daily.iterrows():
        date      = pd.Timestamp(ts_day).normalize()
        d_open    = row['open']
        d_high    = row['high']
        d_low     = row['low']
        d_close   = row['close']
        d_range   = d_high - d_low

        # Bars per day: 24h * 4 bars/hour = 96 M15 bars
        n         = 96
        bar_hours = np.array([i * 15 / 60 for i in range(n)])  # fractional hour

        # Session volatility multipliers
        def vmult(h):
            if   h < 6:    return 0.25
            elif h < 7:    return 0.55
            elif h < 12:   return 1.50
            elif h < 17:   return 1.10
            else:          return 0.40

        vols     = np.array([vmult(h) for h in bar_hours])
        base_vol = (d_range / 4) * 0.018
        drift    = (d_close - d_open) / n

        # Generate path
        prices    = np.zeros(n)
        prices[0] = d_open
        for i in range(1, n):
            prices[i] = prices[i-1] + drift + vols[i]*base_vol * rng.standard_normal()

        # Rescale to fit real H/L
        p_rng = prices.max() - prices.min()
        if p_rng > 1e-6:
            prices = (prices - prices.min()) / p_rng * d_range + d_low
        prices[-1] = d_close

        # Confine Asian session bars
        asian_mask   = bar_hours < 6
        asian_center = d_open
        asian_half   = d_range * 0.22
        prices[asian_mask] = np.clip(
            prices[asian_mask],
            asian_center - asian_half,
            asian_center + asian_half
        )

        # Build OHLC bars
        for i in range(n):
            ts   = date + pd.Timedelta(minutes=15 * i)
            o_   = prices[i-1] if i > 0 else d_open
            c_   = prices[i]
            nz   = abs(vols[i]) * base_vol * rng.uniform(0.3, 1.8)
            h_   = max(o_, c_) + nz * rng.uniform(0.1, 0.6)
            l_   = min(o_, c_) - nz * rng.uniform(0.1, 0.6)
            h_   = min(h_, d_high)
            l_   = max(l_, d_low)
            all_rows.append((ts, round(o_,5), round(h_,5), round(l_,5), round(c_,5)))

    df = pd.DataFrame(all_rows, columns=['time','open','high','low','close'])
    df = df.set_index('time')
    return df
