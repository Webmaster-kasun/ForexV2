"""
signals.py — Cable Scalp v2.0 (GBP/USD only)
==============================================

Adapted from Fiber Scalp v2.1 (EUR/USD) with GBP/USD-specific logic.

KEY DIFFERENCES vs Fiber Scalp (EUR/USD):
  1. EMA 13/34    (was 9/21)  — slower, filters GBP/USD whippy crossovers
  2. ORB 30 min   (was 15)    — GBP/USD needs longer to settle at session open
  3. ORB fresh 45 min (was 60) — GBP moves faster after ORB
  4. ORB aging 90 min (was 120)
  5. CPR bias only if price >10 pips from pivot (was always)
     — GBP/USD regularly straddles pivot on news → false +1
  6. Exhaustion at 2.5x ATR  (was 3.0x) — GBP overextends more
  7. Threshold 5/6  (was 4/6) — GBP needs stronger confirmation
  8. Score 4 = no trade       (was valid for EUR/USD)
  9. Dead zone ends 07:00 SGT (was 16:00) — GBP/USD active in Tokyo

SCORING (max 6):
  EMA crossover:  fresh cross = +3  |  aligned (no cross) = +1
  ORB breakout:   fresh (<45m) = +2  |  aging (45-90m) = +1  |  stale = +0
  CPR bias:       price >10p from pivot in direction = +1
  Exhaustion:     stretch > 2.5x ATR = -1 (penalty)

SL = 15 pips  |  TP = 25 pips  |  RR = 1.67
"""

import time
import logging
from datetime import datetime as _dt
import datetime as _dtmod
import pytz as _pytz
from config_loader import load_secrets, load_settings, DATA_DIR
from state_utils   import load_json, save_json
from oanda_trader  import make_oanda_session

log = logging.getLogger(__name__)

_CPR_CACHE_FILE = DATA_DIR / "cpr_cache_cable.json"
_ORB_CACHE_FILE = DATA_DIR / "orb_cache_cable.json"
_SGT = _pytz.timezone("Asia/Singapore")
_UTC = _pytz.utc

# ── GBP/USD specific defaults ─────────────────────────────────────────────────
EMA_FAST            = 13      # slower than EUR/USD (was 9)
EMA_SLOW            = 34      # slower than EUR/USD (was 21)
ORB_FORMATION_MIN   = 30      # longer than EUR/USD (was 15)
ORB_FRESH_MIN       = 45      # shorter than EUR/USD (was 60)
ORB_AGING_MIN       = 90      # shorter than EUR/USD (was 120)
CPR_MIN_DIST_PIPS   = 10      # GBP/USD only — skip CPR if too close to pivot
EXHAUSTION_ATR_MULT = 2.5     # tighter than EUR/USD (was 3.0)
MIN_TRADE_SCORE     = 5       # stricter than EUR/USD (was 4)


def score_to_position_usd(score: int, settings: dict | None = None) -> int:
    """Score 4 = no trade for GBP/USD (too many false signals at threshold 4)."""
    s = settings or {}
    score_risk = s.get("score_risk_usd", {})
    val = score_risk.get(str(score)) or score_risk.get(score)
    if val is not None:
        return max(int(val), 0)
    # fallbacks
    if score >= 6: return int(s.get("position_full_usd", 40))
    if score >= 5: return int(s.get("position_partial_usd", 30))
    return 0   # score 4 → no trade


def _ema_series(closes: list, period: int) -> list:
    if len(closes) < period:
        return []
    k   = 2.0 / (period + 1)
    ema = sum(closes[:period]) / period
    out = [ema]
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
        out.append(ema)
    return out


def _atr(highs, lows, closes, period=14):
    n = len(closes)
    if n < period + 2: return None
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]),
               abs(lows[i]-closes[i-1])) for i in range(1, n)]
    a = sum(trs[:period]) / period
    for tr in trs[period:]:
        a = (a*(period-1) + tr) / period
    return a


class SignalEngine:

    def __init__(self, demo: bool = True):
        secrets         = load_secrets()
        self.api_key    = secrets.get("OANDA_API_KEY",    "")
        self.account_id = secrets.get("OANDA_ACCOUNT_ID", "")
        self.base_url   = (
            "https://api-fxpractice.oanda.com" if demo
            else "https://api-fxtrade.oanda.com"
        )
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        self.session = make_oanda_session(allowed_methods=["GET"])

    # ── Main entry point ──────────────────────────────────────────────────────

    def analyze(self, instrument: str = "GBP_USD",
                settings: dict | None = None):
        """
        Run Cable Scalp scoring engine for GBP/USD.
        Returns: (score, direction, details, levels, position_usd)
        """
        if settings is None:
            settings = load_settings()

        pip_size = float(settings.get("pip_size", 0.0001))
        dp       = 5 if pip_size <= 0.0001 else 3

        # ── Step 1: CPR daily pivot levels ────────────────────────────────────
        levels = self._get_cpr(instrument, dp)
        if levels is None:
            return 0, "NONE", "CPR fetch failed", {}, 0

        pivot = levels["pivot"]

        # ── Step 2: M5 candles ───────────────────────────────────────────────
        fast_p = int(settings.get("ema_fast_period",  EMA_FAST))          # 13
        slow_p = int(settings.get("ema_slow_period",  EMA_SLOW))          # 34
        atr_p  = int(settings.get("atr_period",       14))
        m5_n   = int(settings.get("m5_candle_count",  60))

        m5_c, m5_h, m5_l = self._candles(instrument, "M5", m5_n)
        if len(m5_c) < slow_p + 3:
            return 0, "NONE", f"Not enough M5 data (need {slow_p+3})", levels, 0

        price   = m5_c[-1]
        atr_val = _atr(m5_h, m5_l, m5_c, atr_p)

        levels["current_price"] = round(price, dp)
        levels["atr"]           = round(atr_val, dp) if atr_val else None
        levels["pip_size"]      = pip_size

        # ── Step 3: EMA 13/34 on M5 ──────────────────────────────────────────
        fast_s = _ema_series(m5_c[:-1], fast_p)
        slow_s = _ema_series(m5_c[:-1], slow_p)
        if len(fast_s) < 2 or len(slow_s) < 2:
            return 0, "NONE", "Not enough EMA data", levels, 0

        ef_now  = fast_s[-1]; ef_prv = fast_s[-2]
        es_now  = slow_s[-1]; es_prv = slow_s[-2]
        spread  = abs(ef_now - es_now)

        levels[f"ema{fast_p}"] = round(ef_now, dp)
        levels[f"ema{slow_p}"] = round(es_now, dp)

        # ── Step 4: ORB ───────────────────────────────────────────────────────
        now_sgt  = _dt.now(_SGT)
        session  = self._session_name(now_sgt, settings)
        orb_h, orb_l, orb_ok, orb_age = self._get_orb(
            instrument, session, now_sgt, dp, settings)

        levels["orb_high"]    = round(orb_h,  dp) if orb_h  else None
        levels["orb_low"]     = round(orb_l,  dp) if orb_l  else None
        levels["orb_age_min"] = orb_age
        levels["orb_formed"]  = orb_ok
        levels["session"]     = session

        # ── Step 5: H1 trend filter ───────────────────────────────────────────
        h1_info = self._h1_trend(instrument,
                                  int(settings.get("h1_ema_period", 21)), dp)

        # ── Step 6: Score ─────────────────────────────────────────────────────
        score     = 0
        direction = "NONE"
        reasons   = []

        reasons.append(
            f"{instrument} | EMA{fast_p}={ef_now:.{dp}f} "
            f"EMA{slow_p}={es_now:.{dp}f} | "
            f"Price={price:.{dp}f} | Pivot={pivot:.{dp}f}"
        )

        # 6a. EMA crossover ────────────────────────────────────────────────────
        fresh_bull = ef_now > es_now and ef_prv <= es_prv and spread >= pip_size
        fresh_bear = ef_now < es_now and ef_prv >= es_prv and spread >= pip_size

        if fresh_bull:
            direction = "BUY";  score += 3
            reasons.append(f"✅ EMA{fast_p} fresh cross ABOVE EMA{slow_p} "
                           f"spread={spread/pip_size:.1f}p (+3)")
        elif fresh_bear:
            direction = "SELL"; score += 3
            reasons.append(f"✅ EMA{fast_p} fresh cross BELOW EMA{slow_p} "
                           f"spread={spread/pip_size:.1f}p (+3)")
        elif ef_now > es_now:
            direction = "BUY";  score += 1
            reasons.append(f"✅ EMA{fast_p} above EMA{slow_p} aligned bull (+1)")
        elif ef_now < es_now:
            direction = "SELL"; score += 1
            reasons.append(f"✅ EMA{fast_p} below EMA{slow_p} aligned bear (+1)")
        else:
            reasons.append("❌ EMAs flat — no direction")
            return 0, "NONE", " | ".join(reasons), levels, 0

        # 6b. ORB (time-decayed) ───────────────────────────────────────────────
        fresh_m = int(settings.get("orb_fresh_minutes", ORB_FRESH_MIN))   # 45
        aging_m = int(settings.get("orb_aging_minutes", ORB_AGING_MIN))   # 90

        if orb_ok and orb_h and orb_l:
            if   orb_age < fresh_m: orb_pts, orb_tag = 2, f"fresh <{fresh_m}m"
            elif orb_age < aging_m: orb_pts, orb_tag = 1, f"aging {fresh_m}-{aging_m}m"
            else:                   orb_pts, orb_tag = 0, f"stale >{aging_m}m"

            if direction == "BUY"  and price > orb_h:
                score += orb_pts
                reasons.append(f"✅ Price above ORB high {orb_h:.{dp}f} (+{orb_pts}) [{orb_tag}]")
            elif direction == "SELL" and price < orb_l:
                score += orb_pts
                reasons.append(f"✅ Price below ORB low {orb_l:.{dp}f} (+{orb_pts}) [{orb_tag}]")
            else:
                reasons.append(f"⏭ Price inside ORB [{orb_l:.{dp}f}-{orb_h:.{dp}f}] (+0)")
        else:
            reasons.append(f"⏭ ORB not yet formed for {session} (+0)")

        # 6c. CPR bias — GBP/USD: only if >10 pips from pivot ─────────────────
        cpr_min_dist = float(settings.get("cpr_min_distance_pips", CPR_MIN_DIST_PIPS))
        dist_price   = abs(price - pivot)
        dist_pips    = dist_price / pip_size

        if dist_pips >= cpr_min_dist:
            if direction == "BUY"  and price > pivot:
                score += 1
                reasons.append(f"✅ Price {dist_pips:.1f}p above pivot {pivot:.{dp}f} (+1)")
            elif direction == "SELL" and price < pivot:
                score += 1
                reasons.append(f"✅ Price {dist_pips:.1f}p below pivot {pivot:.{dp}f} (+1)")
            else:
                reasons.append(f"⏭ CPR bias against direction (+0)")
        else:
            reasons.append(
                f"⏭ Price only {dist_pips:.1f}p from pivot "
                f"(need >{cpr_min_dist:.0f}p) — GBP pivot risk, skipping CPR (+0)"
            )

        # 6d. Exhaustion penalty (2.5x ATR for GBP/USD) ───────────────────────
        ex_mult = float(settings.get("exhaustion_atr_mult", EXHAUSTION_ATR_MULT))
        orb_fired = orb_ok and (
            (direction == "BUY"  and orb_h and price > orb_h) or
            (direction == "SELL" and orb_l  and price < orb_l)
        )
        if atr_val and not orb_fired:
            ema_mid  = (ef_now + es_now) / 2
            stretch  = abs(price - ema_mid) / atr_val
            if stretch > ex_mult:
                score = max(score - 1, 0)
                reasons.append(
                    f"⚠️ Exhaustion: {stretch:.2f}x ATR > {ex_mult}x — score -1 → {score}/6"
                )
            else:
                reasons.append(f"✅ Stretch {stretch:.2f}x ATR (ok)")

        # ── Step 7: SL / TP ───────────────────────────────────────────────────
        pair_sl_tp = settings.get("pair_sl_tp", {})
        pair_cfg   = pair_sl_tp.get(instrument, {})
        sl_pips    = int(pair_cfg.get("sl_pips", 15))
        tp_pips    = int(pair_cfg.get("tp_pips", 25))
        rr         = round(tp_pips / sl_pips, 2)

        levels["sl_pips"]       = sl_pips
        levels["tp_pips"]       = tp_pips
        levels["rr_ratio"]      = rr
        levels["score"]         = score
        levels["setup"]         = "EMA+ORB+CPR"
        levels["entry"]         = round(price, dp)
        levels["position_usd"]  = score_to_position_usd(score, settings)

        # ── Step 8: H1 filter ─────────────────────────────────────────────────
        h1_trend    = h1_info.get("h1_trend", "UNKNOWN")
        h1_aligned  = (
            (h1_trend == "BULLISH" and direction == "BUY") or
            (h1_trend == "BEARISH" and direction == "SELL")
        )
        h1_neutral  = h1_trend in ("UNKNOWN", "FLAT", "DISABLED")
        h1_relation = "aligned" if h1_aligned else ("neutral" if h1_neutral else "opposite")

        levels["h1_trend"]    = h1_trend
        levels["h1_relation"] = h1_relation
        levels["h1_aligned"]  = h1_aligned

        # Score-aware H1 filter (same as Fiber Scalp):
        # score 5 → need H1 aligned or neutral
        # score 6 → need H1 aligned or neutral
        # opposite H1 always blocks
        h1_mode     = settings.get("h1_filter_mode", "score_aware")
        h1_enabled  = bool(settings.get("h1_filter_enabled", True))
        h1_blocked  = False
        if h1_enabled and h1_mode == "score_aware":
            if h1_relation == "opposite":
                h1_blocked = True
                reasons.append(f"🚫 H1 filter: H1={h1_trend} opposite to {direction} — blocked")
            else:
                reasons.append(f"✅ H1 filter: H1={h1_trend} ({h1_relation})")

        # ── Step 9: final ─────────────────────────────────────────────────────
        blockers   = []
        threshold  = int(settings.get("signal_threshold", MIN_TRADE_SCORE))  # 5
        min_rr     = float(settings.get("min_rr_ratio", 1.6))

        if h1_blocked:            blockers.append(f"H1 {h1_trend} opposite")
        if score < threshold:     blockers.append(f"score {score}/6 < {threshold}")
        if rr < min_rr:           blockers.append(f"RR {rr} < {min_rr}")

        levels["signal_blockers"] = blockers
        levels["mandatory_checks"] = {
            "score_ok": score >= threshold,
            "rr_ok":    rr >= min_rr,
            "h1_ok":    not h1_blocked,
        }

        position_usd = score_to_position_usd(score, settings) if not blockers else 0

        reasons.append(
            f"SL={sl_pips}p  TP={tp_pips}p  RR=1:{rr}  "
            f"Score={score}/6  Threshold={threshold}/6  "
            f"Position=${position_usd}"
        )
        if blockers:
            reasons.append("BLOCKED: " + " | ".join(blockers))

        details = " | ".join(reasons)

        if blockers:
            log.info("Signal BLOCKED | %s dir=%s score=%d/6 | %s",
                     instrument, direction, score, "; ".join(blockers))
        elif score < threshold:
            log.info("Signal | %s dir=%s score=%d/6 — below threshold %d",
                     instrument, direction, score, threshold)
        else:
            log.info("Signal FIRE | %s dir=%s score=%d/6 $%d | %s",
                     instrument, direction, score, position_usd, details)

        return score, direction, details, levels, position_usd

    # ── CPR ───────────────────────────────────────────────────────────────────

    def _get_cpr(self, instrument: str, dp: int = 5) -> dict | None:
        closes, highs, lows = self._candles(instrument, "D", 3)
        if len(closes) < 2:
            log.warning("CPR: not enough daily candles for %s", instrument)
            return None
        ph = highs[-2]; pl = lows[-2]; pc = closes[-2]
        pivot = (ph + pl + pc) / 3
        bc    = (ph + pl) / 2
        tc    = (pivot - bc) + pivot
        if tc < bc: tc, bc = bc, tc
        dr = ph - pl
        return {
            "pivot": round(pivot, dp), "tc": round(tc, dp),
            "bc":    round(bc, dp),    "r1": round((2*pivot)-pl, dp),
            "r2":    round(pivot+dr,  dp), "s1": round((2*pivot)-ph, dp),
            "s2":    round(pivot-dr,  dp), "pdh": round(ph, dp),
            "pdl":   round(pl, dp),
            "cpr_width_pct": round(abs(tc-bc)/pivot*100, 3),
        }

    # ── ORB ───────────────────────────────────────────────────────────────────

    def _session_name(self, now_sgt: _dt, settings: dict) -> str | None:
        h   = now_sgt.hour
        lon = int(settings.get("london_session_start_hour", 15))
        lon_e = int(settings.get("london_session_end_hour", 20))
        us  = int(settings.get("us_session_start_hour",    20))
        us_e= int(settings.get("us_session_end_hour",      23))
        tok = int(settings.get("tokyo_session_start_hour",  8))
        tok_e= int(settings.get("tokyo_session_end_hour",  14))
        if lon <= h < lon_e: return "London"
        if us  <= h < us_e:  return "US"
        if tok <= h < tok_e: return "Tokyo"
        return None

    def _get_orb(self, instrument: str, session: str | None,
                 now_sgt: _dt, dp: int, settings: dict):
        """Returns (orb_high, orb_low, formed, age_minutes)"""
        if not session:
            return None, None, False, 0

        sess_starts = {
            "London": int(settings.get("london_session_start_hour", 15)),
            "US":     int(settings.get("us_session_start_hour",     20)),
            "Tokyo":  int(settings.get("tokyo_session_start_hour",   8)),
        }
        if session not in sess_starts:
            return None, None, False, 0

        open_h   = sess_starts[session]
        open_sgt = now_sgt.replace(hour=open_h, minute=0, second=0, microsecond=0)
        if session == "US" and now_sgt.hour < 4:
            open_sgt -= _dtmod.timedelta(days=1)

        date_str  = open_sgt.strftime("%Y-%m-%d")
        cache_key = f"{instrument}_{date_str}_{session}"
        cache     = load_json(_ORB_CACHE_FILE, {})

        if cache.get(cache_key, {}).get("formed"):
            c = cache[cache_key]
            age = max(0, int((now_sgt - open_sgt).total_seconds() / 60))
            return c["high"], c["low"], True, age

        form_min = int(settings.get("orb_formation_minutes", ORB_FORMATION_MIN))  # 30
        age_now  = max(0, int((now_sgt - open_sgt).total_seconds() / 60))
        if age_now < form_min:
            log.debug("ORB not formed | %s %s (%dm < %dm)", instrument, session, age_now, form_min)
            return None, None, False, age_now

        open_utc = open_sgt.astimezone(_UTC)
        _, highs, lows, times = self._candles_timed(instrument, "M15", 12)
        for i, t in enumerate(times):
            try:
                ct = _dt.fromisoformat(t.replace("Z", "+00:00")).replace(tzinfo=_UTC)
            except Exception:
                continue
            if ct >= open_utc:
                cache[cache_key] = {"high": round(highs[i], dp),
                                    "low":  round(lows[i],  dp), "formed": True}
                save_json(_ORB_CACHE_FILE, cache)
                log.info("ORB formed | %s %s H=%.*f L=%.*f",
                         instrument, session, dp, highs[i], dp, lows[i])
                return highs[i], lows[i], True, age_now

        return None, None, False, age_now

    # ── H1 trend ──────────────────────────────────────────────────────────────

    def _h1_trend(self, instrument: str, period: int = 21, dp: int = 5) -> dict:
        try:
            closes, _, _ = self._candles(instrument, "H1", 40)
            if len(closes) < period + 2:
                return {"h1_trend": "UNKNOWN", "h1_ema_now": None}
            ema = _ema_series(closes[:-1], period)
            if len(ema) < 1:
                return {"h1_trend": "UNKNOWN", "h1_ema_now": None}
            e   = ema[-1]; p = closes[-1]
            trend = "BULLISH" if p > e else "BEARISH" if p < e else "FLAT"
            return {"h1_trend": trend, "h1_ema_now": round(e, dp)}
        except Exception as exc:
            log.warning("H1 trend error: %s", exc)
            return {"h1_trend": "UNKNOWN", "h1_ema_now": None}

    # ── Data fetchers ─────────────────────────────────────────────────────────

    def _candles(self, instrument: str, granularity: str, count: int = 60):
        url = f"{self.base_url}/v3/instruments/{instrument}/candles"
        prm = {"count": str(count), "granularity": granularity, "price": "M"}
        for _ in range(3):
            try:
                r = self.session.get(url, headers=self.headers, params=prm, timeout=15)
                if r.status_code == 200:
                    cc = [c for c in r.json().get("candles", []) if c.get("complete")]
                    return ([float(c["mid"]["c"]) for c in cc],
                            [float(c["mid"]["h"]) for c in cc],
                            [float(c["mid"]["l"]) for c in cc])
                log.warning("Candles %s %s HTTP %s", instrument, granularity, r.status_code)
            except Exception as e:
                log.warning("Candles error: %s", e)
            time.sleep(1)
        return [], [], []

    def _candles_timed(self, instrument: str, granularity: str, count: int = 12):
        url = f"{self.base_url}/v3/instruments/{instrument}/candles"
        prm = {"count": str(count), "granularity": granularity, "price": "M"}
        for _ in range(3):
            try:
                r = self.session.get(url, headers=self.headers, params=prm, timeout=15)
                if r.status_code == 200:
                    cc = [c for c in r.json().get("candles", []) if c.get("complete")]
                    return ([float(c["mid"]["c"]) for c in cc],
                            [float(c["mid"]["h"]) for c in cc],
                            [float(c["mid"]["l"]) for c in cc],
                            [c["time"] for c in cc])
            except Exception as e:
                log.warning("Candles timed error: %s", e)
            time.sleep(1)
        return [], [], [], []
