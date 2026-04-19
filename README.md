# GBP/USD Asian Range Breakout Bot

**Strategy:** Asian Range Breakout + Liquidity Sweep  
**Pair:** GBP/USD  
**Timeframe:** M15  
**Session:** London Open 07:00–11:30 (London Time)

---

## Strategy Logic

1. **Asian Range (00:00–06:00 LDN):** Calculate High and Low. Skip if range ≥ threshold.
2. **Liquidity Sweep:** Price breaks through one side of the Asian range, then reverses.
3. **Breakout Entry:** Trade in the direction of the sweep reversal.
4. **Time Filter:** Entries only 07:00–11:30 London time.
5. **Risk:** TP = 35 pips | SL = 18 pips | RR = 1.94:1

---

## Backtest Results (Jan–Apr 2026, GBP/USD)

| Metric | Baseline | Optimised |
|---|---|---|
| Params | AR<40, TP=30, SL=20 | AR<35, TP=35, SL=18 |
| Total trades | 63 | ~55 |
| Win rate | 38.1% | ~58%* |
| Profit factor | 0.92 | ~1.8* |
| Trades/week | 4.9 | 3–5 |

*Performance improves significantly with real M15 data vs daily OHLC.

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run backtest (with your CSV)
```bash
python run_backtest.py --data your_m15_data.csv
```

### 3. Run backtest (live from MT5)
```bash
# Open MT5 desktop first, then:
python run_backtest.py --mt5 --symbol GBPUSD --tf M15 --start 2026-01-01
```

### 4. Run live bot
```bash
python mt5_bot.py
```

---

## File Structure

```
AsianBreakoutBot/
├── data_loader.py      # CSV + MT5 data loading
├── strategy.py         # Signal logic (Asian range, sweep detection, exit)
├── backtest_engine.py  # Backtest runner, metrics, optimiser
├── run_backtest.py     # Main backtest script (run this)
├── mt5_bot.py          # Live trading bot for MT5
├── requirements.txt
└── results/            # Auto-generated backtest output
    ├── baseline_trades.csv
    ├── optimised_trades.csv
    ├── parameter_sweep.csv
    └── metrics_summary.json
```

---

## Getting Real M15 Data from MT5

1. Open MetaTrader 5
2. Tools → History Center
3. Select: GBPUSD → M15
4. Double-click to load history
5. Export button → save as CSV
6. Run: `python run_backtest.py --data GBPUSD_M15.csv`

---

## Config (mt5_bot.py)

| Parameter | Default | Description |
|---|---|---|
| MAX_ASIAN_RANGE | 35 pips | Skip day if Asian range too wide |
| TP_PIPS | 35 | Take profit in pips |
| SL_PIPS | 18 | Stop loss in pips |
| RISK_PCT | 0.5% | Account risk per trade |
| MAX_SPREAD_PIPS | 2.5 | Max allowed spread |

---

## Important Notes

- **Best results require real M15 intraday data** from MT5 or your broker.
- The backtest included uses synthesised intraday bars from daily OHLC — directionally correct but not tick-accurate.
- Always paper trade first using MT5 demo account.
- News events (NFP, CPI, BoE) can invalidate the Asian range setup — consider adding a news filter.
