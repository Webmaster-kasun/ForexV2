"""
run_backtest.py
===============
Main backtest runner. Loads data, runs baseline + optimisation, exports CSVs.

Usage:
    python run_backtest.py                     # uses default GBP-USD.csv
    python run_backtest.py --data your_m15.csv # use your own M15 data
    python run_backtest.py --mt5               # load live from MT5
"""

import argparse
import os
import sys
import json
import pandas as pd

from data_loader    import load_from_csv, load_from_mt5, synthesise_m15_from_daily
from backtest_engine import run_backtest, optimise, compute_metrics, trades_to_dataframe

OUT_DIR = 'results'
os.makedirs(OUT_DIR, exist_ok=True)

# ── Argument parsing ──────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description='Asian Range Breakout Backtest')
parser.add_argument('--data',   default='GBP-USD.csv', help='Path to CSV data file')
parser.add_argument('--mt5',    action='store_true',   help='Load data from MT5')
parser.add_argument('--symbol', default='GBPUSD',      help='Symbol for MT5')
parser.add_argument('--tf',     default='M15',         help='Timeframe for MT5 (M5/M15)')
parser.add_argument('--start',  default='2026-01-01',  help='Start date YYYY-MM-DD')
parser.add_argument('--end',    default=None,          help='End date YYYY-MM-DD')
args = parser.parse_args()

# ── Load data ─────────────────────────────────────────────────────────────────
print('\n' + '='*60)
print('ASIAN RANGE BREAKOUT — GBP/USD BACKTEST')
print('='*60)

if args.mt5:
    print(f'Loading from MT5: {args.symbol} {args.tf} {args.start} → {args.end or "today"}')
    df = load_from_mt5(args.symbol, args.tf, args.start, args.end)
    print(f'  Loaded {len(df):,} bars')
else:
    print(f'Loading from CSV: {args.data}')
    raw = load_from_csv(args.data)
    print(f'  Loaded {len(raw):,} bars')

    # Check if it's daily data — if so, synthesise M15
    total_days = (raw.index[-1] - raw.index[0]).days + 1
    bars_per_day = len(raw) / max(total_days, 1)

    if bars_per_day < 5:
        print('  Daily OHLC detected — synthesising M15 intraday bars...')
        df = synthesise_m15_from_daily(raw)
        print(f'  Synthesised {len(df):,} M15 bars from {len(raw)} daily bars')
        print('  ⚠  Note: Backtest accuracy improves significantly with real M15 data.')
        print('     Export M15 from MT5: History Center → GBPUSD → M15 → Export')
    else:
        df = raw
        print(f'  Intraday data detected ({bars_per_day:.0f} bars/day average)')

print(f'  Date range: {df.index[0].date()} → {df.index[-1].date()}')

# ── Baseline backtest ─────────────────────────────────────────────────────────
print('\n' + '-'*60)
print('BASELINE BACKTEST  |  AR < 40 pips  |  TP = 30  |  SL = 20')
print('-'*60)
base_trades, base_m = run_backtest(df, max_asian_range=40, tp_pips=30, sl_pips=20)
for k, v in base_m.items():
    print(f'  {k:<25} {v}')

# ── Parameter optimisation ────────────────────────────────────────────────────
print('\n' + '-'*60)
print('PARAMETER OPTIMISATION SWEEP')
print('-'*60)
sweep = optimise(
    df,
    ar_values  = [25, 30, 35, 40, 45],
    tp_values  = [20, 25, 30, 35, 40],
    sl_values  = [12, 15, 18, 20, 25],
    min_trades = 8,
)
if len(sweep):
    print(f'  {len(sweep)} valid combinations found. Top 12:')
    cols = ['asian_range_thresh','tp_pips','sl_pips','rr',
            'total_trades','win_rate_pct','total_pips','profit_factor',
            'max_drawdown_pips','trades_per_week']
    print(sweep[cols].head(12).to_string(index=False))
else:
    print('  No valid combinations found — try relaxing min_trades')

# ── Optimised backtest ────────────────────────────────────────────────────────
if len(sweep):
    best = sweep.iloc[0]
    print(f'\n' + '-'*60)
    print(f'OPTIMISED BACKTEST  |  AR < {int(best.asian_range_thresh)}  '
          f'|  TP = {int(best.tp_pips)}  |  SL = {int(best.sl_pips)}  '
          f'|  RR = {best.rr}:1')
    print('-'*60)
    opt_trades, opt_m = run_backtest(
        df,
        max_asian_range = best.asian_range_thresh,
        tp_pips         = best.tp_pips,
        sl_pips         = best.sl_pips,
    )
    for k, v in opt_m.items():
        print(f'  {k:<25} {v}')
else:
    opt_trades, opt_m = base_trades, base_m
    best = None

# ── Before vs After comparison ────────────────────────────────────────────────
print('\n' + '='*60)
print('BEFORE vs AFTER')
print('='*60)
print(f"{'Metric':<25} {'Baseline':>12} {'Optimised':>12}")
print('-'*50)
for k in base_m:
    bv = base_m[k]
    ov = opt_m.get(k, '—')
    print(f'  {k:<23} {str(bv):>12} {str(ov):>12}')

# ── Export results ────────────────────────────────────────────────────────────
print('\nExporting results...')

trades_to_dataframe(base_trades).to_csv(f'{OUT_DIR}/baseline_trades.csv',   index=False)
trades_to_dataframe(opt_trades).to_csv(f'{OUT_DIR}/optimised_trades.csv',   index=False)
if len(sweep):
    sweep.to_csv(f'{OUT_DIR}/parameter_sweep.csv', index=False)

summary = {
    'baseline':   base_m,
    'optimised':  opt_m,
    'best_params': {
        'asian_range_thresh': float(best.asian_range_thresh) if best is not None else 40,
        'tp_pips':            float(best.tp_pips)            if best is not None else 30,
        'sl_pips':            float(best.sl_pips)            if best is not None else 20,
    }
}
with open(f'{OUT_DIR}/metrics_summary.json', 'w') as f:
    json.dump(summary, f, indent=2)

print(f'  ✅ {OUT_DIR}/baseline_trades.csv      ({len(base_trades)} trades)')
print(f'  ✅ {OUT_DIR}/optimised_trades.csv     ({len(opt_trades)} trades)')
if len(sweep):
    print(f'  ✅ {OUT_DIR}/parameter_sweep.csv      ({len(sweep)} combos)')
print(f'  ✅ {OUT_DIR}/metrics_summary.json')
print('\nDone.')
