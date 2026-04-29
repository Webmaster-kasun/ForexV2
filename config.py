"""
config.py — Multi-Pair Bot Configuration
=========================================

Pairs:
  GBP/USD — Triple EMA Momentum | London Open 15:00–19:00 SGT
  EUR/USD — 4-Layer Signal Engine | London 15:00–19:00 + NY 20:00–00:00 SGT
  AUD/USD — Triple EMA Momentum | Asia Open 07:00–10:00 + London 15:00–19:00 SGT

Account: SGD
"""

PAIRS = {

    "GBP_USD": {
        "emoji":       "🇬🇧",
        "pip":         0.0001,
        "strategy":    "triple_ema",       # Triple EMA Momentum
        "sl_pips":     15,
        "tp_pips":     20,
        "trade_size":  10000,              # units
        "max_trades":  1,                  # per day
        "sessions": [
            {"label": "London", "start": 15, "end": 19,
             "max_spread": 2.0, "hours": "15:00–19:00"},
        ],
    },

    "EUR_USD": {
        "emoji":       "🇪🇺",
        "pip":         0.0001,
        "strategy":    "four_layer",       # 4-Layer Signal Engine
        "sl_pips":     15,
        "tp_pips":     20,
        "trade_size":  74000,              # units
        "max_trades":  2,                  # per day (London + NY)
        "sessions": [
            {"label": "London", "start": 15, "end": 19,
             "max_spread": 1.2, "hours": "15:00–19:00"},
            {"label": "NY",     "start": 20, "end": 24,
             "max_spread": 1.5, "hours": "20:00–00:00"},
        ],
    },

    "AUD_USD": {
        "emoji":       "🇦🇺",
        "pip":         0.0001,
        "strategy":    "triple_ema",       # Triple EMA Momentum
        "sl_pips":     15,
        "tp_pips":     20,
        "trade_size":  10000,              # units
        "max_trades":  1,                  # per day
        "sessions": [
            {"label": "Asia",   "start":  7, "end": 10,
             "max_spread": 2.0, "hours": "07:00–10:00"},
            {"label": "London", "start": 15, "end": 19,
             "max_spread": 2.0, "hours": "15:00–19:00"},
        ],
    },

}

RISK = {
    "risk_per_trade": 0.5,     # % of account balance per trade
}

# 4-Layer signal engine params (EUR/USD)
FOUR_LAYER = {
    "signal_threshold":  4,
    "min_atr_pips":      2.5,
    "l2_break_buffer":   0.00150,   # 15 pips
    "l2_expiry_minutes": 90,
    "rsi_buy_max":       65,
    "rsi_sell_min":      35,
    "ema_tol":           0.00020,   # 2 pips
    "min_m5_range":      0.00010,
}

# Triple EMA params (GBP/USD, AUD/USD)
TRIPLE_EMA = {
    "spans":        [5, 10, 20],
    "min_atr_pips": 5.0,
    "max_spread":   2.5,
}
