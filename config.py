"""
config.py — Central config for GBP/USD scalp bot

Sessions (SGT):
  Asian Pre-London : 06:00 – 08:00
  London Open      : 07:00 – 13:00
  NY Overlap       : 15:00 – 19:00
  Late NY          : 19:00 – 23:00

Max 4 trades/day, 1 per session window.
"""

SYMBOL = "GBP_USD"

SESSIONS = [
    {"name": "Asian Pre-London", "start": 6,  "end": 8,  "max_spread": 1.8},
    {"name": "London Open",      "start": 7,  "end": 13, "max_spread": 2.0},
    {"name": "NY Overlap",       "start": 15, "end": 19, "max_spread": 2.2},
    {"name": "Late NY",          "start": 19, "end": 23, "max_spread": 2.5},
]

RISK = {
    "risk_per_trade":    0.5,   # % of account balance per trade
    "max_trades_per_day": 4,
}

FILTERS = {
    "min_atr": 0.0003,
}
