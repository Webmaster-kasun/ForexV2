# Fiber Scalp v2.1 — Settings Reference

## Core risk settings

| Setting | v2.0 value | Meaning |
|---|---:|---|
| `signal_threshold` | `4` | Minimum score required for execution |
| `score_risk_usd.4` | `30` | Risk amount for score 4/6 trades |
| `score_risk_usd.5` | `40` | Risk amount for score 5/6 trades |
| `score_risk_usd.6` | `50` | Risk amount for score 6/6 trades |
| `max_units` | `20000` | Hard cap on final requested units |
| `min_trade_units` | `1000` | Reject very small adjusted orders |
| `margin_safety_factor` | `0.6` | Uses only part of available margin |
| `auto_scale_on_margin_reject` | `true` | Auto-reduce units if broker margin rejects |

Legacy fields are still present for compatibility:

| Legacy setting | v2.0 fallback |
|---|---:|
| `position_partial_usd` | `30` |
| `position_full_usd` | `40` |

The bot prefers `score_risk_usd` when present.

## H1 score-aware filter

| Setting | v2.0 value | Meaning |
|---|---:|---|
| `h1_filter_enabled` | `true` | Enables H1 trend filter |
| `h1_filter_mode` | `score_aware` | Uses score-aware H1 gating |
| `h1_ema_period` | `21` | H1 EMA period used to classify trend |

Execution rules:

| Score | H1 aligned | H1 neutral / unknown / flat | H1 opposite |
|---:|---|---|---|
| 4/6 | Allow | Skip | Skip |
| 5/6 | Allow | Allow | Skip |
| 6/6 | Allow | Allow | Skip |

## SL / TP

| Setting | Value | Meaning |
|---|---:|---|
| `pair_sl_tp.EUR_USD.sl_pips` | `18` | Stop loss distance |
| `pair_sl_tp.EUR_USD.tp_pips` | `30` | Take profit distance |
| `min_rr_ratio` | `1.6` | Minimum allowed reward:risk |
| `be_trigger_pips` | `20` | Break-even trigger reference; break-even is currently disabled by default |

## Telegram alerts

| Setting | Value | Meaning |
|---|---:|---|
| `telegram_min_score_alert` | `4` | Suppress score 0–3 WATCHING alerts |
| `telegram_show_margin` | `true` | Notify when margin guard adjusts units |

Telegram should send actionable items only: score 4+ signals, H1 blocks, opened/closed trades, spread/news blocks, order failures, and scheduled reports.

## Recommended v2.0 JSON block

```json
{
  "signal_threshold": 4,
  "score_risk_usd": {
    "4": 30,
    "5": 40,
    "6": 50
  },
  "position_partial_usd": 30,
  "position_full_usd": 40,
  "max_units": 20000,
  "h1_filter_enabled": true,
  "h1_filter_mode": "score_aware",
  "h1_ema_period": 21,
  "pair_sl_tp": {
    "EUR_USD": {
      "sl_pips": 18,
      "tp_pips": 30,
      "pip_value_usd": 10.0,
      "be_trigger_pips": 20
    }
  },
  "telegram_min_score_alert": 4
}
```

## Why v2.0 changed H1 handling

Score 4 is the weakest allowed entry score, so it now requires H1 trend confirmation. Score 5/6 setups are stronger, so neutral H1 is allowed, but clear opposite H1 is blocked to avoid counter-trend trades.


## v2.1 Daily Safety Controls

| Control | v2.1 value | Purpose |
|---|---:|---|
| `max_losing_trades_day` | `3` | Stop new entries after 3 losing trades in the trading day. |
| `daily_risk_cap_usd` | `$120` | Stop new entries when realized + open P/L reaches `-$120` for the day. |

Telegram startup now shows: `Day reset: 08:00 SGT | Loss cap: 3/day | Risk cap: $120/day`.
