"""
backtest_engine.py
==================
Full backtest engine for the Asian Range Breakout + Liquidity Sweep strategy.

Supports both:
  - Real intraday M15 data (recommended)
  - Daily OHLC data with synthesised intraday structure (fallback)

Usage:
    from backtest_engine import run_backtest, optimise, compute_metrics

    trades, metrics = run_backtest(m15_df, max_asian_range=40, tp=30, sl=20)
    sweep_df        = optimise(m15_df)
"""

import pandas as pd
import numpy as np
from strategy import compute_asian_range, scan_for_signal, simulate_exit, check_trend_filter

PIP = 0.0001


# ─────────────────────────────────────────────────────────────────────────────
# MAIN BACKTEST
# ─────────────────────────────────────────────────────────────────────────────

def run_backtest(df: pd.DataFrame,
                 max_asian_range: float = 40,
                 tp_pips: float = 30,
                 sl_pips: float = 20,
                 use_trend_filter: bool = False) -> tuple[list, dict]:
    """
    Run full backtest over the provided price data.

    Args:
        df:                M15 (or M5) OHLC DataFrame, index = DatetimeIndex
        max_asian_range:   Max allowed Asian session range in pips (default 40)
        tp_pips:           Take profit in pips (default 30)
        sl_pips:           Stop loss in pips  (default 20)
        use_trend_filter:  Apply H1 EMA20/50 trend filter (default False)

    Returns:
        (trades_list, metrics_dict)
    """
    trades = []
    dates  = df.index.normalize().unique()

    # Build H1 bars if trend filter is requested
    h1_df = None
    if use_trend_filter:
        h1_df = df.resample('1h').agg(
            {'open':'first','high':'max','low':'min','close':'last'}
        ).dropna()

    for date in dates:
        day_bars = df[df.index.normalize() == date]
        if len(day_bars) < 20:
            continue

        # Step 1: Asian Range
        ah, al, ar = compute_asian_range(day_bars)
        if ah is None:
            continue
        if ar >= max_asian_range:
            continue

        # Step 2: Optional trend filter
        trend = None
        if use_trend_filter and h1_df is not None:
            h1_to_now = h1_df[h1_df.index.normalize() <= date]
            trend     = check_trend_filter(h1_to_now)

        # Step 3: Scan for signal
        signal = scan_for_signal(day_bars, ah, al,
                                 tp_pips=tp_pips, sl_pips=sl_pips,
                                 trend_bias=trend)
        if signal is None:
            continue

        # Step 4: Simulate exit
        bars_after = day_bars[day_bars.index > signal['entry_time']]
        if len(bars_after) == 0:
            continue
        trade = simulate_exit(signal, bars_after)
        trades.append(trade)

    metrics = compute_metrics(trades)
    return trades, metrics


# ─────────────────────────────────────────────────────────────────────────────
# METRICS
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(trades: list) -> dict:
    """Compute full performance metrics from a list of trade dicts."""
    if not trades:
        return {'error': 'No trades generated'}

    df  = pd.DataFrame(trades)
    n   = len(df)
    w   = int((df['result'] == 'WIN').sum())
    l   = n - w
    wr  = round(w / n * 100, 1)

    gp  = float(df[df['result'] == 'WIN']['pips'].sum())  if w else 0.0
    gl  = float(abs(df[df['result'] == 'LOSS']['pips'].sum())) if l else 0.0
    pips = float(df['pips'].sum())
    pf   = round(gp / gl, 2) if gl > 0 else float('inf')

    eq  = df['pips'].cumsum().values
    dd  = float((np.maximum.accumulate(eq) - eq).max())

    aw  = float(df[df['result'] == 'WIN']['pips'].mean())  if w else 0.0
    al_ = float(df[df['result'] == 'LOSS']['pips'].mean()) if l else 0.0
    exp = round((wr / 100 * aw) + ((1 - wr / 100) * al_), 2)

    t0  = pd.to_datetime(df['entry_time'].min())
    t1  = pd.to_datetime(df['entry_time'].max())
    wks = max((t1 - t0).days / 7, 1)

    return {
        'total_trades':       n,
        'wins':               w,
        'losses':             l,
        'win_rate_pct':       wr,
        'total_pips':         round(pips, 1),
        'gross_profit_pips':  round(gp, 1),
        'gross_loss_pips':    round(gl, 1),
        'profit_factor':      pf,
        'max_drawdown_pips':  round(dd, 1),
        'avg_win_pips':       round(aw, 1),
        'avg_loss_pips':      round(al_, 1),
        'expectancy_pips':    exp,
        'trades_per_week':    round(n / wks, 1),
    }


# ─────────────────────────────────────────────────────────────────────────────
# OPTIMISER
# ─────────────────────────────────────────────────────────────────────────────

def optimise(df: pd.DataFrame,
             ar_values:  list = None,
             tp_values:  list = None,
             sl_values:  list = None,
             min_trades: int = 10) -> pd.DataFrame:
    """
    Grid search over (asian_range_threshold, tp, sl) combinations.
    Sorts results by profit_factor descending.

    Args:
        df:          M15 price DataFrame
        ar_values:   Asian range thresholds to test (default [25,30,35,40,45])
        tp_values:   TP values in pips to test (default [20,25,30,35,40])
        sl_values:   SL values in pips to test (default [12,15,18,20,25])
        min_trades:  Minimum trades required for a result to be included

    Returns:
        DataFrame sorted by profit_factor (best first)
    """
    if ar_values is None: ar_values = [25, 30, 35, 40, 45]
    if tp_values is None: tp_values = [20, 25, 30, 35, 40]
    if sl_values is None: sl_values = [12, 15, 18, 20, 25]

    rows = []
    total = len(ar_values) * len(tp_values) * len(sl_values)
    done  = 0

    for ar in ar_values:
        for tp in tp_values:
            for sl in sl_values:
                done += 1
                if tp <= sl:
                    continue
                _, m = run_backtest(df, max_asian_range=ar, tp_pips=tp, sl_pips=sl)
                if 'error' in m or m['total_trades'] < min_trades:
                    continue
                rows.append({
                    'asian_range_thresh': ar,
                    'tp_pips':            tp,
                    'sl_pips':            sl,
                    'rr':                 round(tp / sl, 2),
                    **m,
                })

    if not rows:
        return pd.DataFrame()

    result = pd.DataFrame(rows).sort_values('profit_factor', ascending=False)
    return result.reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# TRADE LOG EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def trades_to_dataframe(trades: list) -> pd.DataFrame:
    """Convert trade list to a clean DataFrame for export."""
    if not trades:
        return pd.DataFrame()

    cols = ['entry_time', 'entry_price', 'direction', 'stop_loss', 'take_profit',
            'exit_time', 'exit_price', 'result', 'pips',
            'asian_high', 'asian_low', 'asian_range']

    rows = []
    for t in trades:
        row = {c: t.get(c, '') for c in cols}
        # Format timestamps
        for tc in ['entry_time', 'exit_time']:
            if isinstance(row[tc], pd.Timestamp):
                row[tc] = row[tc].strftime('%Y-%m-%d %H:%M')
        rows.append(row)

    return pd.DataFrame(rows, columns=cols)
