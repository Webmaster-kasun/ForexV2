"""
config.py — Multi-Pair Bot (v3.3)

Changes v3.3:
  - Asian session added to ALL pairs (07:00-10:00 SGT)
  - Filters loosened for more trades:
      GBP/USD: EMA spans reduced (3/7/14 instead of 5/10/20) — reacts faster
      EUR/USD: signal_threshold lowered 4→3, ATR gate lowered 2.5→1.5
      AUD/USD: max_asian_range increased 40→60, min_sweep_pips 3→1
  - max_trades increased to allow Asian + London trades

Sessions (SGT):
  Asian:  07:00-10:00  (all pairs)
  London: 15:00-19:00  (all pairs)
  NY:     20:00-00:00  (EUR/USD only)
"""

PAIRS = {

    "GBP_USD": {
        "emoji":       "🇬🇧",
        "pip":         0.0001,
        "strategy":    "triple_ema",
        "sl_pips":     15,
        "tp_pips":     25,
        "trade_size":  10000,
        "max_trades":  2,           # was 1 — now allows Asian + London
        "max_gap":     50.0,
        "sessions": [
            {"label": "Asia",   "start":  7, "end": 10,
             "max_spread": 2.5, "hours": "07:00-10:00"},
            {"label": "London", "start": 15, "end": 19,
             "max_spread": 2.0, "hours": "15:00-19:00"},
        ],
    },

    "EUR_USD": {
        "emoji":       "🇪🇺",
        "pip":         0.0001,
        "strategy":    "four_layer",
        "sl_pips":     15,
        "tp_pips":     25,
        "trade_size":  74000,
        "max_trades":  3,           # was 2 — now allows Asian + London + NY
        "max_gap":     50.0,
        "sessions": [
            {"label": "Asia",   "start":  7, "end": 10,
             "max_spread": 1.5, "hours": "07:00-10:00"},
            {"label": "London", "start": 15, "end": 19,
             "max_spread": 1.2, "hours": "15:00-19:00"},
            {"label": "NY",     "start": 20, "end": 24,
             "max_spread": 1.5, "hours": "20:00-00:00"},
        ],
    },

    "AUD_USD": {
        "emoji":       "🇦🇺",
        "pip":         0.0001,
        "strategy":    "audusd_range",
        "sl_pips":     15,
        "tp_pips":     25,
        "trade_size":  10000,
        "max_trades":  2,           # was 1 — now allows Asian + London
        "max_gap":     50.0,
        "sessions": [
            {"label": "Asia",   "start":  7, "end": 13,  # wider Asian window for range build + entry
             "max_spread": 2.5, "hours": "07:00-13:00"},
            {"label": "London", "start": 15, "end": 17,
             "max_spread": 2.0, "hours": "15:00-17:00"},
        ],
    },

}

RISK = {
    "risk_per_trade": 0.5,
}

# 4-Layer signal engine params (EUR/USD)
# LOOSENED: threshold 4→3, ATR 2.5→1.5, body ratio 0.50→0.40
FOUR_LAYER = {
    "signal_threshold":  3,        # was 4 — fires more often
    "min_atr_pips":      1.5,      # was 2.5 — allows lower volatility entries
    "l2_break_buffer":   0.00200,  # was 0.00150 — wider break zone
    "l2_expiry_minutes": 120,      # was 90 — longer L2 window
    "rsi_buy_max":       70,       # was 65 — less strict
    "rsi_sell_min":      30,       # was 35 — less strict
    "ema_tol":           0.00030,  # was 0.00020 — wider EMA touch zone
    "min_m5_range":      0.00005,  # was 0.00010 — allows smaller candles
}

# Triple EMA params (GBP/USD)
# LOOSENED: faster EMAs (3/7/14) react quicker, ATR lowered 5→3
TRIPLE_EMA = {
    "spans":        [3, 7, 14],    # was [5,10,20] — faster reaction
    "min_atr_pips": 3.0,           # was 5.0 — fires in lower volatility
    "max_spread":   2.5,
}

# AUD/USD Asian Range params
# LOOSENED: wider range threshold, lower sweep requirement
AUD_RANGE = {
    "asian_start_sgt":      7,     # was 8 — earlier start
    "asian_end_sgt":        13,
    "breakout_start_sgt":   13,    # was 15 — allows earlier breakout entry
    "breakout_end_sgt":     17,
    "max_asian_range_pips": 60,    # was 40 — allows wider ranges
    "min_sweep_pips":        1,    # was 3 — easier to qualify
    "min_atr_pips":          2.0,  # was 4.0 — fires in lower volatility
}
