"""
Signal Engine — M1 Ultra-Scalp
================================
Supports: EUR/USD, GBP/USD
Score 4/4 required:
  L0: M15 EMA8 vs EMA21 — direction must match M15 momentum (no counter-trend scalps)
  L1: M5  EMA8 vs EMA21 bias
  L2: M5  RSI(9) <=35 BUY / >=65 SELL + delta>=1.0 + EMA50 + proper candle confirmation
  L3: M1  trigger candle — engulf or pin-bar
  L4: H1  EMA200 hard block — price must be above EMA200 for BUY, below for SELL
       (L4 is a veto/block, not a score point — direction="NONE" if violated)
"""

import os, requests, logging

log = logging.getLogger(__name__)

class SafeFilter(logging.Filter):
    def __init__(self):
        self.api_key = os.environ.get("OANDA_API_KEY","")
    def filter(self, record):
        if self.api_key and self.api_key in str(record.getMessage()):
            record.msg = record.msg.replace(self.api_key,"***")
        return True
log.addFilter(SafeFilter())

class SignalEngine:
    def __init__(self):
        self.api_key    = os.environ.get("OANDA_API_KEY","")
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID","")
        self.base_url   = "https://api-fxpractice.oanda.com"
        self.headers    = {"Authorization":"Bearer "+self.api_key}

    INSTR_MAP = {
        "EURUSD": "EUR_USD",
        "GBPUSD": "GBP_USD",
    }

    def _fetch_candles(self, instrument, granularity, count=60):
        url    = self.base_url+"/v3/instruments/"+instrument+"/candles"
        params = {"count":str(count),"granularity":granularity,"price":"M"}
        for attempt in range(3):
            try:
                r = requests.get(url, headers=self.headers, params=params, timeout=10)
                if r.status_code == 200:
                    c = [x for x in r.json()["candles"] if x["complete"]]
                    return (
                        [float(x["mid"]["c"]) for x in c],
                        [float(x["mid"]["h"]) for x in c],
                        [float(x["mid"]["l"]) for x in c],
                        [float(x["mid"]["o"]) for x in c],
                    )
                log.warning("Candle "+granularity+" attempt "+str(attempt+1)+" failed: "+str(r.status_code))
            except Exception as e:
                log.warning("Candle error: "+str(e))
        return [], [], [], []

    def analyze(self, asset="EURUSD"):
        instr = self.INSTR_MAP.get(asset)
        if not instr:
            instr = asset[:3]+"_"+asset[3:]
        return self._scalp_m1(instr, asset)

    def _scalp_m1(self, instrument, asset):
        reasons = []
        bull = bear = 0

        # ── L0: M15 EMA8 vs EMA21 — momentum direction gate ──────────
        # If M15 trend disagrees with M5, skip — no counter-trend scalps
        m15_c, _, _, _ = self._fetch_candles(instrument, "M15", 40)
        if len(m15_c) < 22:
            return 0, "NONE", "Not enough M15 data ("+str(len(m15_c))+")"

        m15_ema8  = self._ema(m15_c, 8)[-1]
        m15_ema21 = self._ema(m15_c, 21)[-1]

        m15_bull = m15_ema8 > m15_ema21 * 1.00002
        m15_bear = m15_ema8 < m15_ema21 * 0.99998

        if m15_bull:
            bull += 1
            reasons.append("✅ M15 bullish")
        elif m15_bear:
            bear += 1
            reasons.append("✅ M15 bearish")
        else:
            return 0, "NONE", "M15 EMA flat — no momentum"

        # ── L1: M5 EMA8 vs EMA21 ─────────────────────────────────────
        m5_c, _, _, _ = self._fetch_candles(instrument, "M5", 60)
        if len(m5_c) < 22:
            return 0, "NONE", "Not enough M5 data ("+str(len(m5_c))+")"

        ema8  = self._ema(m5_c, 8)[-1]
        ema21 = self._ema(m5_c, 21)[-1]

        bull_bias = ema8 > ema21 * 1.00003
        bear_bias = ema8 < ema21 * 0.99997

        # L0 and L1 must agree — if M15 is bull but M5 is bear, skip
        if m15_bull and bull_bias:
            bull += 1
            reasons.append("✅ M5 EMA bullish")
        elif m15_bear and bear_bias:
            bear += 1
            reasons.append("✅ M5 EMA bearish")
        else:
            reasons.append("M5 EMA disagrees with M15 — skip")
            return max(bull,bear), "NONE", " | ".join(reasons)

        # ── L2: M5 RSI(9) — relaxed zone + momentum + EMA50 + candle ─
        # BUY:  RSI(9) <= 35 (relaxed — RSI rarely hits 30 in strong uptrends)
        #       AND rising strongly (delta >= 1.0 pt — confirms momentum turn)
        #       AND price above M5 EMA50 (pullback in uptrend, not free-fall)
        #       AND close > open (real bullish body)
        #       AND close in upper 60% of M5 candle range (buyers in control)
        # SELL: RSI(9) >= 65, delta <= -1.0, below EMA50, bear body, close in lower 60%
        RSI_MOMENTUM_THRESHOLD = 1.0

        rsi_vals  = self._rsi_series(m5_c, 9)
        rsi       = rsi_vals[-1]
        rsi_prev  = rsi_vals[-2] if len(rsi_vals) >= 2 else rsi
        rsi_delta = rsi - rsi_prev

        ema50     = self._ema(m5_c, 50)[-1]
        price_now = m5_c[-1]

        # Proper candle check requires open/high/low — fetch M5 OHLC
        m5_co, m5_hi, m5_lo, m5_op = self._fetch_candles(instrument, "M5", 5)
        if len(m5_co) < 2 or len(m5_hi) < 2 or len(m5_lo) < 2 or len(m5_op) < 2:
            reasons.append("Not enough M5 OHLC data for candle check")
            return max(bull,bear), "NONE", " | ".join(reasons)

        c_close = m5_co[-1]; c_open = m5_op[-1]
        c_high  = m5_hi[-1]; c_low  = m5_lo[-1]
        c_range = max(c_high - c_low, 0.00001)

        # Bullish: close > open AND close in upper 60% of range
        bull_candle = (c_close > c_open) and ((c_close - c_low) / c_range >= 0.60)
        # Bearish: close < open AND close in lower 60% of range
        bear_candle = (c_close < c_open) and ((c_high - c_close) / c_range >= 0.60)

        price_above_ema50 = price_now > ema50
        price_below_ema50 = price_now < ema50

        if (bull_bias
                and rsi <= 35
                and rsi_delta >= RSI_MOMENTUM_THRESHOLD
                and price_above_ema50
                and bull_candle):
            bull += 1
            reasons.append(
                "✅ RSI="+str(round(rsi,1))
                +" Δ+"+str(round(rsi_delta,1))
                +" above EMA50 bull-body close@"+str(round((c_close-c_low)/c_range*100))+"% range"
            )
        elif (bear_bias
                and rsi >= 65
                and rsi_delta <= -RSI_MOMENTUM_THRESHOLD
                and price_below_ema50
                and bear_candle):
            bear += 1
            reasons.append(
                "✅ RSI="+str(round(rsi,1))
                +" Δ"+str(round(rsi_delta,1))
                +" below EMA50 bear-body close@"+str(round((c_high-c_close)/c_range*100))+"% range"
            )
        else:
            reasons.append(
                "RSI="+str(round(rsi,1))
                +" Δ="+str(round(rsi_delta,2))
                +" EMA50="+str(round(ema50,5))
                +" bull_candle="+str(bull_candle)
                +" bear_candle="+str(bear_candle)
                +" — L2 fail"
            )
            return max(bull,bear), "NONE", " | ".join(reasons)

        # ── L3: M1 trigger candle ─────────────────────────────────────
        m1_c, m1_h, m1_l, m1_o = self._fetch_candles(instrument, "M1", 10)
        if len(m1_c) < 3:
            return max(bull,bear), "NONE", " | ".join(reasons)+" | Not enough M1 data"

        c1 = m1_c[-1]; c2 = m1_c[-2]
        o1 = m1_o[-1]; o2 = m1_o[-2]
        h1 = m1_h[-1]; l1 = m1_l[-1]

        body1 = abs(c1 - o1)
        rng1  = max(h1 - l1, 0.00001)

        bull_engulf = (c1 > o1) and (c2 < o2) and (c1 >= o2) and (o1 <= c2)
        lower_wick  = min(o1,c1) - l1
        bull_pin    = (c1 >= o1) and (lower_wick/rng1 > 0.55) and (body1/rng1 < 0.40)

        bear_engulf = (c1 < o1) and (c2 > o2) and (c1 <= o2) and (o1 >= c2)
        upper_wick  = h1 - max(o1,c1)
        bear_pin    = (c1 <= o1) and (upper_wick/rng1 > 0.55) and (body1/rng1 < 0.40)

        if bull_bias and (bull_engulf or bull_pin):
            bull += 1
            reasons.append("✅ M1 bullish "+("engulf" if bull_engulf else "pin-bar"))
        elif bear_bias and (bear_engulf or bear_pin):
            bear += 1
            reasons.append("✅ M1 bearish "+("engulf" if bear_engulf else "pin-bar"))
        else:
            reasons.append("No M1 trigger")
            return max(bull,bear), "NONE", " | ".join(reasons)

        # Score 4/4 reached — now apply L4 H1 EMA200 hard block
        if bull >= 4:
            raw_dir = "BUY"
        elif bear >= 4:
            raw_dir = "SELL"
        else:
            return max(bull,bear), "NONE", " | ".join(reasons)

        # ── L4: H1 EMA200 hard block ─────────────────────────────────
        # Fetch 210 H1 candles to calculate EMA200
        h1_c, _, _, _ = self._fetch_candles(instrument, "H1", 210)
        if len(h1_c) < 200:
            # Not enough H1 data — allow trade but log warning
            log.warning(instrument+": Not enough H1 data for EMA200 ("+str(len(h1_c))+") — skipping H1 filter")
            reasons.append("⚠️ H1 EMA200 unavailable")
            return max(bull,bear), raw_dir, " | ".join(reasons)

        h1_ema200   = self._ema(h1_c, 200)[-1]
        current_price = m5_c[-1]

        if raw_dir == "BUY" and current_price < h1_ema200:
            reasons.append("🚫 H1 EMA200 block: price below EMA200 — no BUY")
            return max(bull,bear), "NONE", " | ".join(reasons)
        elif raw_dir == "SELL" and current_price > h1_ema200:
            reasons.append("🚫 H1 EMA200 block: price above EMA200 — no SELL")
            return max(bull,bear), "NONE", " | ".join(reasons)
        else:
            reasons.append("✅ H1 EMA200="+str(round(h1_ema200,5))+" confirms "+raw_dir)

        return max(bull,bear), raw_dir, " | ".join(reasons)

    def _rsi_series(self, closes, period=9):
        """Returns list of RSI values (same length as closes) for momentum check."""
        if len(closes) < period + 2:
            return [50.0, 50.0]
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        # Seed with simple average
        ag = sum(gains[:period]) / period
        al = sum(losses[:period]) / period
        rsi_list = []
        for i in range(period, len(gains)+1):
            if i == period:
                pass  # already seeded above
            else:
                ag = (ag * (period-1) + gains[i-1]) / period
                al = (al * (period-1) + losses[i-1]) / period
            rsi_list.append(100 - (100 / (1 + ag/al)) if al != 0 else 100.0)
        return rsi_list if len(rsi_list) >= 2 else [50.0, 50.0]

    def _rsi(self, closes, period=14):
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i]-closes[i-1]
            gains.append(max(d,0)); losses.append(max(-d,0))
        if len(gains) < period: return 50
        ag = sum(gains[-period:])/period
        al = sum(losses[-period:])/period
        if al == 0: return 100
        return 100-(100/(1+ag/al))

    def _ema(self, data, period):
        if not data: return [0.0]
        if len(data) < period: return [sum(data)/len(data)]*len(data)
        seed = sum(data[:period])/period
        emas = [seed]*period
        mult = 2/(period+1)
        for p in data[period:]:
            emas.append((p-emas[-1])*mult+emas[-1])
        return emas
