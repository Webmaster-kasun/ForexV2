# Cable Scalp v2.0 — GBP/USD M5 Scalping Bot

## Why different logic from EUR/USD (Fiber Scalp)

| Component        | EUR/USD (Fiber) | GBP/USD (Cable) | Reason |
|---|---|---|---|
| EMA periods      | 9 / 21          | **13 / 34**     | GBP/USD whippy — slower EMAs filter noise |
| ORB formation    | 15 min          | **30 min**      | GBP needs longer to settle at open |
| ORB fresh window | 60 min          | **45 min**      | GBP moves faster after ORB |
| ORB aging window | 120 min         | **90 min**      | GBP ORB goes stale faster |
| CPR bias         | Always          | **>10p from pivot** | GBP straddles pivot on news |
| Exhaustion       | 3.0x ATR        | **2.5x ATR**    | GBP overextends more often |
| Threshold        | 4/6             | **5/6**         | GBP needs stronger confirmation |
| Score 4          | Valid trade     | **No trade**    | Too many false signals at score 4 |
| Dead zone end    | 16:00 SGT       | **07:00 SGT**   | GBP/USD active in Tokyo session |
| SL               | 18 pips         | **15 pips**     | Per user specification |
| TP               | 30 pips         | **25 pips**     | Per user specification |

## Scoring (max 6)

| Component | Condition | Points |
|---|---|---|
| EMA cross | EMA13 fresh cross EMA34 | +3 |
| EMA align | EMA13 already above/below EMA34 | +1 |
| ORB fresh | Break ORB within 45 min | +2 |
| ORB aging | Break ORB 45–90 min | +1 |
| CPR bias  | Price >10p from pivot in direction | +1 |
| Exhaustion| Stretch >2.5x ATR (no ORB) | -1 |

**Minimum score to trade: 5/6**

## Sessions (SGT)

| Session | Hours | Active |
|---|---|---|
| Dead zone | 04:00–07:00 | ❌ No trading |
| Tokyo    | 08:00–14:00 | ✅ Threshold 5/6 |
| London   | 15:00–20:00 | ✅ Threshold 5/6 ← PRIMARY |
| US       | 20:00–23:00 | ✅ Threshold 5/6 |

## Risk

| Score | USD Risk | Units (approx) |
|---|---|---|
| 5/6 | $30 | ~15,000 |
| 6/6 | $40 | ~20,000 |
| 4/6 | $0  | No trade |
