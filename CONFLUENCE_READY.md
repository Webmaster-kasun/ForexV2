# Fiber Scalp v2.1 — Technical Specification & Operations Wiki

**Bot:** Fiber Scalp v2.1  
**Pair:** EUR/USD  
**Broker:** OANDA  
**Mode:** Demo by default  
**Primary release goal:** add score-aware H1 filtering while retaining the v1.9 controlled-risk model.

## 1. Executive Summary

Fiber Scalp v2.1 keeps the existing M5 EMA + ORB + CPR signal engine and the EUR/USD 18-pip SL / 30-pip TP model. The main improvement is score-aware H1 gating: score 4 trades now require H1 alignment, while score 5/6 trades may pass with neutral H1 but are blocked when H1 is clearly opposite.

## 2. Architecture

```text
Railway Scheduler
  └── every 5 minutes
      └── bot.run_cycle()
          ├── load settings
          ├── fetch OANDA candles/prices
          ├── calculate EMA / ORB / CPR score
          ├── calculate H1 EMA trend relationship
          ├── apply session, spread, news, open-trade and cooldown guards
          ├── apply v2.0 score-aware H1 filter
          ├── calculate score-based risk
          ├── apply margin guard + max_units cap
          ├── place OANDA order when all checks pass
          └── send Telegram + persist DB state
```

## 3. Strategy Settings

| Item | Value |
|---|---:|
| Timeframe | M5 |
| Minimum execution score | 4/6 |
| H1 filter mode | `score_aware` |
| Stop loss | 18 pips |
| Take profit | 30 pips |
| Reward:risk | 1.67 |
| Telegram watching alert minimum | 4/6 |

## 4. v2.0 H1 Score-Aware Filter

| Score | H1 aligned | H1 neutral / unknown / flat | H1 opposite |
|---:|---|---|---|
| 4/6 | Allow trade | Skip trade | Skip trade |
| 5/6 | Allow trade | Allow trade | Skip trade |
| 6/6 | Allow trade | Allow trade | Skip trade |

Rationale:

- Score 4 is valid but weaker, so H1 confirmation is required.
- Score 5/6 setups are stronger, so neutral H1 is acceptable.
- Opposite H1 is blocked for all tradeable scores to reduce counter-trend entries.

## 5. Risk Model

| Score | Risk amount | Approx units with 18-pip SL | Notes |
|---:|---:|---:|---|
| 4/6 | $30 | ~16,667 | Requires H1 alignment |
| 5/6 | $40 | capped by `max_units` | Neutral H1 allowed |
| 6/6 | $50 | capped by `max_units` | Best setup only |

Hard cap:

```json
"max_units": 20000
```

## 6. Telegram Alert Policy

Telegram alerts are intentionally filtered:

| Event | Telegram? |
|---|---|
| Score 0–3 watching setup | No |
| Score 4+ signal | Yes |
| H1 score-aware block | Yes |
| Trade opened | Yes |
| Trade closed | Yes |
| News block / spread block | Yes |
| Margin adjustment | Yes, if enabled |
| Startup / daily / weekly / monthly reports | Yes |

Startup template displays:

```text
Risk: $30 (score 4) | $40 (score 5) | $50 (score 6)
H1 filter: SCORE-AWARE
  • Score 4: H1 aligned required
  • Score 5/6: neutral allowed, opposite blocked
```

Signal cards display H1 relation as `aligned`, `neutral`, or `counter-trend`.

## 7. Operational Notes

- Keep `demo_mode = true` until at least 50–100 closed trades are reviewed.
- Review score 4 vs score 5/6 performance separately.
- Watch H1 blocked signals to confirm the filter is reducing weak score 4 entries.
- Do not increase risk until margin-adjustment alerts become rare and profit factor remains stable.
- Keep `telegram_min_score_alert = 4` to avoid low-score alert noise.

## 8. Version History

| Version | Date | Change |
|---|---|---|
| v2.0 | May 02 2026 | Added score-aware H1 filter and updated Telegram/docs. |
| v1.9 | May 02 2026 | Added score-based risk sizing, `max_units=20000`, and updated Telegram/docs. |
| v1.7 | May 02 2026 | Suppressed Telegram WATCHING alerts below score 4. |
| v1.6 | Apr 2026 | Fixed-pip SL/TP and margin guard release. |


## v2.1 Daily Safety Controls

| Control | v2.1 value | Purpose |
|---|---:|---|
| `max_losing_trades_day` | `3` | Stop new entries after 3 losing trades in the trading day. |
| `daily_risk_cap_usd` | `$120` | Stop new entries when realized + open P/L reaches `-$120` for the day. |

Telegram startup now shows: `Day reset: 08:00 SGT | Loss cap: 3/day | Risk cap: $120/day`.
