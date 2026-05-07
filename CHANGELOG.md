# Changelog

## v2.1.0 — 2026-05-02

### Added
- Added score-aware H1 filter mode: `h1_filter_mode = "score_aware"`.
- Added H1 relation classification in signals: `aligned`, `neutral`, or `opposite`.
- Added score-aware H1 blocks before order placement:
  - Score 4 requires H1 alignment.
  - Score 5/6 allows neutral H1.
  - Score 5/6 blocks opposite H1.
- Updated Telegram signal cards to show H1 relation and score-aware mode.
- Updated Telegram startup template to explain the H1 policy.
- Updated README, SETTINGS, and Confluence-ready documentation.

### Unchanged
- Risk ladder remains score 4/5/6 = $30/$40/$50.
- `max_units` remains `20000`.
- EUR/USD SL/TP remains 18 pips / 30 pips.
- Minimum execution score remains 4/6.
- Telegram WATCHING alert threshold remains score ≥4.

## v1.9.0 — 2026-05-02

### Changed
- Added score-based risk sizing using `score_risk_usd`:
  - Score 4 → $30 risk
  - Score 5 → $40 risk
  - Score 6 → $50 risk
- Added hard `max_units = 20000` cap in the margin guard.
- Updated startup Telegram template to show the new risk ladder.
- Updated README, SETTINGS, and Confluence-ready documentation.

### Unchanged
- EUR/USD SL/TP remains 18 pips / 30 pips.
- Minimum execution score remains 4/6.
- Telegram WATCHING alert threshold remains score ≥4.

## v1.7.0 — 2026-05-02

### Changed
- Telegram WATCHING alerts now require `telegram_min_score_alert >= 4` by default.
- Updated `settings.json`, `settings.json.example`, `bot.py`, `config_loader.py`, and `scheduler.py` fallback defaults from `3` to `4`.
- Score `3/6` setups remain available in logs/database but no longer create Telegram noise by default.

# Fiber Scalp — Changelog
---

## v1.7.0 — 2026-04-26

### Fix — Weekly/monthly report crash: `KeyError: 'wins'`

**Problem:**
`send_weekly_report` crashed every Monday with `KeyError: 'wins'`.
`_session_breakdown()` and `_setup_breakdown()` in `reporting.py` returned dicts
with only `count`, `win_rate`, `net_pnl` — missing `wins` and `losses` keys.
`msg_weekly_report()` in `telegram_templates.py` accessed `s['wins']` directly,
crashing the entire report silently.

**Fix:**
`_session_breakdown()` and `_setup_breakdown()` in `reporting.py` now include
`wins` and `losses` in every bucket dict, consistent with `_stats()` format.

**Files changed:** `reporting.py`

---

### Fix — ORB age wrong for US continuation window 01–03 SGT

**Problem:**
ORB age calculation in `signals.py` had:
```python
if now_sgt.hour == 0 and session_name == "US":
    open_sgt = open_sgt - timedelta(days=1)
```
This only corrected for midnight (00:xx). At 01:00–03:59 SGT (US continuation
window), `open_sgt` was set to today's 21:00 SGT (in the future), making
`_orb_age_min = max(0, negative) = 0`. Any ORB break at these hours would be
scored as *fresh* (+2 pts) when it was actually 4–7 hours old (+0 stale).

Same bug existed in `_get_orb()` cache key calculation.

**Fix:**
Both occurrences changed to:
```python
if session_name == "US" and now_sgt.hour < 4:
```
Covers the full US continuation window (00:00–03:59 SGT).

**Files changed:** `signals.py` (2 occurrences)

---

### Fix — Wrong pip_size fallback in `_get_pip_value_usd()` (dormant)

**Problem:**
`_pip_size = float(pair_cfg.get("pip_size", 0.01))` defaulted to the JPY pip
size (0.01). If `pip_value_usd` was ever removed from `pair_sl_tp.EUR_USD`,
the dynamic fallback would calculate ~$850/pip instead of ~$10/pip, producing
catastrophically oversized positions. Currently dormant (static override set).

**Fix:**
Default changed to `0.0001` (EUR/USD pip). Fallback return value also corrected
from `6.67` (JPY ~150 estimate) to `10.0` (EUR/USD standard). Docstring updated
to describe EUR/USD behaviour, not JPY.

**Files changed:** `signals.py`

---

### Improvement — EMA fresh cross requires ≥1 pip minimum spread

**Why:**
Several trades (246, 271, 296) fired as "EMA Fresh Cross" with EMA separation
of 0.3–0.4 pips (< 1 pip). A cross where EMA9 and EMA21 are essentially flat
is indistinguishable in the log from a high-conviction directional cross, yet
both scored +3. Near-zero spread crosses have lower predictive value.

**Change:**
Fresh cross (+3) now requires `abs(ema_fast - ema_slow) >= pip_size` (1 pip)
at the time of the cross. Below this threshold, the cross is treated as aligned
(+1) instead and logged as "EMA Weak Cross Up/Down". The EMA spread in pips
is now included in all signal detail lines for visibility.

**Impact:**
Score ceiling for a sub-pip cross falls from 6 to 4 (aligned +1, ORB +2,
CPR +1). These setups can still trade at threshold=4 if ORB and CPR align,
but the EMA component no longer artificially inflates confidence.

**Files changed:** `signals.py`



## v1.0.0 — 2026-04-16

Initial release of **Fiber Scalp v1.5** — EUR/USD (Fiber) London-primary M5 scalping bot.
Built from Ninja Scalp v1.2 / Cable Scalp v1.4 architecture. All previous bot references removed.

### Instrument
EUR/USD only. "Fiber" is the standard informal trading nickname for EUR/USD.

### Strategy
EMA 9/21 crossover + Opening Range Breakout (ORB, time-decayed) + CPR daily pivot bias.
Score 0–6/6. Threshold: ≥4/6 for London and US sessions.

### Session schedule

| Window | SGT | Threshold |
|---|---|---|
| Dead zone | 04:00–07:59 | No trading |
| Tokyo | 08:00–15:59 | **Disabled** (threshold 99) |
| London | 16:00–20:59 | ≥ 4/6 ← PRIMARY |
| US | 21:00–23:59 | ≥ 4/6 ← SECONDARY |
| US cont | 00:00–03:59 | ≥ 4/6 ← SECONDARY |

Tokyo disabled — EUR/USD barely moves during Asian hours. London is where
EUR/USD makes its daily range. The London open ORB is the primary signal.

### Position sizing — $2.00/pip target

| Score | Position | Units | Per pip |
|---|---|---|---|
| 4 | $30 partial | ~10,000 | $1.00/pip |
| 5–6 | $60 full | ~20,000 | $2.00/pip |

EUR/USD pip_value_usd is static $10.00 (USD-quoted pair — no dynamic calculation needed).

### SL / TP

| Pair | SL | TP | RR | Break-even WR |
|---|---|---|---|---|
| EUR/USD | 18p | 30p | 1.67× | 37.5% |

### Spread limits
London: 2p · US: 3p · Tokyo: 2p
EUR/USD London spreads are typically 0.5–1p — spread guard rarely fires.

### Architecture
Full parity with Cable Scalp v1.4 and Ninja Scalp v1.2:
- Health server at `__main__` entry point
- Health handler always returns 200
- Reporting day total fix (pd_trades window)
- Session sentinel guards (99 handling)
- ORB sentinel guards
- No legacy sl_pct/rr_ratio checks
- All 14 guards active

### Key differences from Ninja Scalp v1.2
- Instrument: USD_JPY → EUR_USD
- pip_size: 0.01 → 0.0001
- pip_value_usd: dynamic → static $10.00
- SL: 20p → 18p · TP: 34p → 30p · RR: 1.70× → 1.67×
- BE trigger: 22p → 20p
- position_full_usd: $48 → $60
- Tokyo: disabled (threshold 99) ← EUR/USD specific
- US sessions: enabled (London primary, US secondary)

---

## v1.1.0 — 2026-04-16

### Fix — Session open card firing for disabled Tokyo session

**Problem:**
On startup at 15:23 SGT (inside Tokyo hours), the bot sent a
`EUR_USD Tokyo Window Open` Telegram card even though Tokyo is disabled
(`session_thresholds.Tokyo: 99`). Cosmetic but confusing.

**Fix:**
`_guard_phase()` now checks the session threshold before sending the
session open alert. If `threshold >= 99` the card is suppressed entirely.
Tokyo open card will never fire for Fiber Scalp while Tokyo is disabled.

**File changed:** `bot.py` — `_guard_phase()` session open block

---

## v1.2.0 — 2026-04-16

### Extended dead zone to cover Tokyo hours (04:00–15:59 SGT)

**Why:**
Tokyo was already disabled via `session_thresholds.Tokyo: 99` (score impossible
to reach). But the bot still ran a full cycle every 5 minutes during Tokyo hours
— fetching prices, calculating EMAs, querying OANDA — just to immediately
conclude no trade. Wasteful and produced misleading log lines
(`Session: Tokyo Window`).

**Fix:**
`dead_zone_end_hour` extended from `7` to `15` in settings.json.
The dead zone now covers 04:00–15:59 SGT — the full pre-London inactive period.
Bot exits immediately with zero API calls during these hours.
Wakes up at 16:00 SGT for the London open.

**Startup card:**
Tokyo line removed entirely — dead zone `04:00–15:59` communicates everything.
No redundant "Tokyo disabled" label needed.

**Settings changed:**
- `dead_zone_end_hour`: `7` → `15`

**Files changed:** `settings.json`, `settings.json.example`, `bot.py` (defaults),
`telegram_templates.py` (startup card), all docs.

---

## v1.3.0 — 2026-04-16

### Fix — max_total_open_trades corrected to 1

Fiber Scalp trades a single pair (EUR/USD) with max_concurrent_trades: 1.
The global cap was set to 2 which was misleading — startup card showed
"Global cap: 2 open trades" but the per-pair limit of 1 always bound first.

Changed `max_total_open_trades: 2 → 1` to match reality.
Startup card now correctly shows "Global cap: 1 open trade".

---

## v1.4.0 — 2026-04-16

### H1 filter split added to weekly and monthly reports

**Why:**
The H1 aligned vs counter-trend split was only available by downloading
`trade_history.json` and analysing manually. Now it appears automatically
in every weekly and monthly Telegram report.

**Weekly report — new H1 Filter section:**
```
H1 Filter [soft]
  Aligned    ██████████  75.0%  6W/2L  $+156.00
  Counter ⚠️  ████░░░░░░  33.3%  1W/2L  $-18.00
  → Counter-trend 41.7pts lower — consider strict mode
```

**Recommendation line logic:**
- < 5 counter-trend trades → "need more data"
- Difference ≥ 20pts → "consider strict mode"
- Difference ≥ 10pts → "monitor closely"
- Difference < 10pts → "soft mode justified"

**Graceful fallback:** If no h1_aligned data exists (old trades without
the field), the H1 section is omitted entirely — no errors.

**Files changed:** `reporting.py` (helper + calls), `telegram_templates.py`
(helper + weekly + monthly functions)

---

## v1.5.0 — 2026-04-16

### Position sizing — $2.00/$1.50 per pip target (aligned with Cable Scalp v1.5)

| | v1.4 | v1.5 | $/pip |
|---|---|---|---|
| Full (score 5–6) | $60 → 20,000 units | $60 → 20,000 units ✅ | **$2.00/pip** |
| Partial (score 4) | $30 → 10,000 units | **$45 → 15,000 units** | **$1.50/pip** |

Only the partial position changed — full was already correct at $2.00/pip.
Sizing now consistent across Cable Scalp v1.5 and Fiber Scalp v1.5.

**Files changed:** `settings.json`, `settings.json.example`, `bot.py` (default),
`telegram_templates.py` (default param), all docs.
