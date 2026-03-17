"""
Signal Engine - Demo Account 2
================================
TWO STRATEGIES:

1. MEAN REVERSION (AUD/USD, EUR/GBP)
   - BB touch + RSI extreme + Stochastic
   - Trade AGAINST short move, expect bounce
   - Need 4/5 score to trade

2. TREND FOLLOWING (EUR/USD)
   - H1 trend direction + M15 EMA pullback + MACD
   - Trade WITH the trend
   - Need 4/5 score to trade
"""

import os
import requests
import logging
import math
from datetime import datetime
import pytz

log = logging.getLogger(__name__)

class SafeFilter(logging.Filter):
    def __init__(self):
        self.api_key = os.environ.get("OANDA_API_KEY", "")
    def filter(self, record):
        if self.api_key and self.api_key in str(record.getMessage()):
            record.msg = record.msg.replace(self.api_key, "***API_KEY***")
        return True

safe_filter = SafeFilter()
log.addFilter(safe_filter)

class SignalEngine:
    def __init__(self):
        self.sg_tz      = pytz.timezone("Asia/Singapore")
        self.asset      = "EURUSD"
        self.api_key    = os.environ.get("OANDA_API_KEY", "")
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        self.base_url   = "https://api-fxpractice.oanda.com"
        self.headers    = {"Authorization": "Bearer " + self.api_key}

    OANDA_MAP = {
        "EURUSD": "EUR_USD",
        "AUDUSD": "AUD_USD",
        "EURGBP": "EUR_GBP",
    }

    def _fetch_candles(self, instrument, granularity, count=100):
        url    = self.base_url + "/v3/instruments/" + instrument + "/candles"
        params = {"count": str(count), "granularity": granularity, "price": "M"}
        for attempt in range(3):
            try:
                r = requests.get(url, headers=self.headers, params=params, timeout=10)
                if r.status_code == 200:
                    candles = r.json()["candles"]
                    c       = [x for x in candles if x["complete"]]
                    closes  = [float(x["mid"]["c"]) for x in c]
                    highs   = [float(x["mid"]["h"]) for x in c]
                    lows    = [float(x["mid"]["l"]) for x in c]
                    opens   = [float(x["mid"]["o"]) for x in c]
                    return closes, highs, lows, opens
                log.warning("Candle fetch attempt " + str(attempt+1) + " failed: " + str(r.status_code))
            except Exception as e:
                log.warning("Candle fetch error: " + str(e))
        return [], [], [], []

    def analyze(self, asset="EURUSD"):
        self.asset = asset
        if asset == "EURUSD":
            return self._analyze_trend_following()
        return self._analyze_mean_reversion()

    # ══════════════════════════════════════════════════════════════════
    # STRATEGY 1: MEAN REVERSION (AUD/USD, EUR/GBP)
    # ══════════════════════════════════════════════════════════════════
    def _analyze_mean_reversion(self):
        instrument = self.OANDA_MAP.get(self.asset, "EUR_GBP")
        reasons    = []
        bull       = 0
        bear       = 0

        # ── H1 TREND GUARD ───────────────────────────────────────────
        h1_closes, h1_highs, h1_lows, h1_opens = self._fetch_candles(instrument, "H1", 60)
        if len(h1_closes) < 25:
            return 0, "NONE", "Not enough H1 data"

        h1_ema20  = self._ema(h1_closes, 20)[-1]
        h1_ema50  = self._ema(h1_closes, min(50, len(h1_closes)))[-1]
        _, _, _, bb_width_h1 = self._bollinger_bands(h1_closes, 20, 2)
        bb_mid_h1 = sum(h1_closes[-20:]) / 20
        bb_pct_h1 = bb_width_h1 / bb_mid_h1

        # Strong trend = skip mean reversion entirely
        if bb_pct_h1 > 0.008:
            return 0, "NONE", "H1 strong trend (BB wide=" + str(round(bb_pct_h1*100, 2)) + "%) - skip MR"

        trending_up   = h1_ema20 > h1_ema50 * 1.0003
        trending_down = h1_ema20 < h1_ema50 * 0.9997
        ranging       = not trending_up and not trending_down

        # ── M15 BOLLINGER BAND TOUCH ─────────────────────────────────
        m15_closes, m15_highs, m15_lows, m15_opens = self._fetch_candles(instrument, "M15", 100)
        if len(m15_closes) < 25:
            return 0, "NONE", "Not enough M15 data"

        bb_upper, bb_mid, bb_lower, bb_width = self._bollinger_bands(m15_closes, 20, 2)
        current = m15_closes[-1]
        bb_pct  = bb_width / bb_mid

        if bb_pct > 0.006:
            return 0, "NONE", "M15 trending - BB width=" + str(round(bb_pct*100, 2)) + "%"

        at_lower_bb = current <= bb_lower
        at_upper_bb = current >= bb_upper
        near_lower  = current <= bb_lower * 1.0005
        near_upper  = current >= bb_upper * 0.9995

        if at_lower_bb:
            bull += 2
            reasons.append("✅ AT Lower BB")
        elif near_lower:
            bull += 1
            reasons.append("Near Lower BB")

        if at_upper_bb:
            bear += 2
            reasons.append("✅ AT Upper BB")
        elif near_upper:
            bear += 1
            reasons.append("Near Upper BB")

        # ── M15 RSI EXTREME ──────────────────────────────────────────
        rsi = self._rsi(m15_closes, 14)
        if rsi <= 28:
            bull += 2
            reasons.append("✅ RSI very oversold=" + str(round(rsi, 0)))
        elif rsi <= 35:
            bull += 1
            reasons.append("RSI oversold=" + str(round(rsi, 0)))

        if rsi >= 72:
            bear += 2
            reasons.append("✅ RSI very overbought=" + str(round(rsi, 0)))
        elif rsi >= 65:
            bear += 1
            reasons.append("RSI overbought=" + str(round(rsi, 0)))

        # ── M15 STOCHASTIC ───────────────────────────────────────────
        stoch = self._stochastic(m15_closes, m15_highs, m15_lows, 14)
        if stoch <= 15:
            bull += 1
            reasons.append("✅ Stoch deep oversold=" + str(round(stoch, 0)))
        elif stoch <= 25:
            bull += 1
            reasons.append("Stoch oversold=" + str(round(stoch, 0)))

        if stoch >= 85:
            bear += 1
            reasons.append("✅ Stoch deep overbought=" + str(round(stoch, 0)))
        elif stoch >= 75:
            bear += 1
            reasons.append("Stoch overbought=" + str(round(stoch, 0)))

        # ── M5 CANDLE REVERSAL ───────────────────────────────────────
        m5_closes, m5_highs, m5_lows, m5_opens = self._fetch_candles(instrument, "M5", 20)
        if len(m5_closes) >= 3:
            last_green = m5_closes[-1] > m5_opens[-1]
            prev_red   = m5_closes[-2] < m5_opens[-2]
            last_red   = m5_closes[-1] < m5_opens[-1]
            prev_green = m5_closes[-2] > m5_opens[-2]
            if bull > bear and last_green and prev_red:
                bull += 1
                reasons.append("✅ M5 bullish reversal candle")
            if bear > bull and last_red and prev_green:
                bear += 1
                reasons.append("✅ M5 bearish reversal candle")

        # ── TREND GUARD PENALTY ──────────────────────────────────────
        if trending_up and bear > bull:
            bear -= 2
            reasons.append("⚠️ H1 uptrend - SELL blocked")
        if trending_down and bull > bear:
            bull -= 2
            reasons.append("⚠️ H1 downtrend - BUY blocked")

        # ── RANGING BONUS ────────────────────────────────────────────
        if ranging:
            if bull > bear:
                bull += 1
                reasons.append("✅ H1 ranging - ideal for MR!")
            elif bear > bull:
                bear += 1
                reasons.append("✅ H1 ranging - ideal for MR!")

        bull = max(bull, 0)
        bear = max(bear, 0)

        reason_str = " | ".join(reasons) if reasons else "No signals"
        if bull >= 4 and bull > bear:
            return min(bull, 5), "BUY", reason_str
        elif bear >= 4 and bear > bull:
            return min(bear, 5), "SELL", reason_str
        return max(bull, bear), "NONE", reason_str

    # ══════════════════════════════════════════════════════════════════
    # STRATEGY 2: TREND FOLLOWING (EUR/USD)
    # Logic: Trade WITH the H1 trend on M15 pullback to EMA
    # ══════════════════════════════════════════════════════════════════
    def _analyze_trend_following(self):
        instrument = "EUR_USD"
        reasons    = []
        bull       = 0
        bear       = 0

        # ── LAYER 1: H1 TREND DIRECTION (must have clear trend) ──────
        h1_closes, h1_highs, h1_lows, _ = self._fetch_candles(instrument, "H1", 60)
        if len(h1_closes) < 50:
            return 0, "NONE", "Not enough H1 data"

        h1_ema20 = self._ema(h1_closes, 20)[-1]
        h1_ema50 = self._ema(h1_closes, 50)[-1]
        _, _, _, bb_width_h1 = self._bollinger_bands(h1_closes, 20, 2)
        bb_mid_h1 = sum(h1_closes[-20:]) / 20
        bb_pct_h1 = bb_width_h1 / bb_mid_h1

        trending_up   = h1_ema20 > h1_ema50 * 1.0003
        trending_down = h1_ema20 < h1_ema50 * 0.9997

        # Need a CLEAR trend — opposite of mean reversion!
        if not trending_up and not trending_down:
            return 0, "NONE", "EUR/USD ranging — no trend to follow"

        # Trend too weak (BB too narrow = consolidating)
        if bb_pct_h1 < 0.002:
            return 0, "NONE", "EUR/USD H1 BB too narrow — consolidating"

        if trending_up:
            bull += 2
            reasons.append("✅ H1 uptrend (EMA20>EMA50)")
        elif trending_down:
            bear += 2
            reasons.append("✅ H1 downtrend (EMA20<EMA50)")

        # ── LAYER 2: M15 PULLBACK TO EMA21 ──────────────────────────
        # Best trend entry = price pulls back to EMA, then bounces
        m15_closes, m15_highs, m15_lows, _ = self._fetch_candles(instrument, "M15", 60)
        if len(m15_closes) < 25:
            return 0, "NONE", "Not enough M15 data"

        m15_ema21  = self._ema(m15_closes, 21)[-1]
        current    = m15_closes[-1]
        prev       = m15_closes[-2]

        # Uptrend: price pulled back near EMA21 and bouncing up
        near_ema_bull = (current >= m15_ema21 * 0.9995 and
                         current <= m15_ema21 * 1.002 and
                         current > prev)
        # Downtrend: price pulled back near EMA21 and rejecting down
        near_ema_bear = (current <= m15_ema21 * 1.0005 and
                         current >= m15_ema21 * 0.998 and
                         current < prev)

        if trending_up and near_ema_bull:
            bull += 2
            reasons.append("✅ M15 pullback to EMA21 + bounce")
        elif trending_up and current > m15_ema21:
            bull += 1
            reasons.append("M15 above EMA21 (uptrend intact)")

        if trending_down and near_ema_bear:
            bear += 2
            reasons.append("✅ M15 pullback to EMA21 + rejection")
        elif trending_down and current < m15_ema21:
            bear += 1
            reasons.append("M15 below EMA21 (downtrend intact)")

        # ── LAYER 3: MACD MOMENTUM CONFIRM ──────────────────────────
        macd_line, signal_line = self._macd(m15_closes)
        macd_hist = macd_line - signal_line

        if macd_hist > 0 and macd_line > 0:
            bull += 1
            reasons.append("✅ MACD bullish momentum")
        elif macd_hist > 0:
            bull += 1
            reasons.append("MACD crossing up")

        if macd_hist < 0 and macd_line < 0:
            bear += 1
            reasons.append("✅ MACD bearish momentum")
        elif macd_hist < 0:
            bear += 1
            reasons.append("MACD crossing down")

        # ── LAYER 4: M15 RSI TREND CONFIRM ───────────────────────────
        # For trend: RSI 50-70 = bullish momentum, 30-50 = bearish
        rsi = self._rsi(m15_closes, 14)
        if trending_up and 45 <= rsi <= 70:
            bull += 1
            reasons.append("✅ RSI bullish zone=" + str(round(rsi, 0)))
        elif trending_up and rsi > 70:
            bull += 0  # Overbought = skip, wait for pullback
            reasons.append("⚠️ RSI overbought=" + str(round(rsi, 0)) + " wait")

        if trending_down and 30 <= rsi <= 55:
            bear += 1
            reasons.append("✅ RSI bearish zone=" + str(round(rsi, 0)))
        elif trending_down and rsi < 30:
            bear += 0  # Oversold = skip, wait for bounce
            reasons.append("⚠️ RSI oversold=" + str(round(rsi, 0)) + " wait")

        # ── LAYER 5: M5 ENTRY CANDLE ────────────────────────────────
        m5_closes, _, _, m5_opens = self._fetch_candles(instrument, "M5", 15)
        if len(m5_closes) >= 3:
            last_green = m5_closes[-1] > m5_opens[-1]
            last_red   = m5_closes[-1] < m5_opens[-1]
            if trending_up and last_green:
                bull += 1
                reasons.append("✅ M5 bullish entry candle")
            if trending_down and last_red:
                bear += 1
                reasons.append("✅ M5 bearish entry candle")

        bull = max(bull, 0)
        bear = max(bear, 0)

        log.info("EURUSD Trend: bull=" + str(bull) + " bear=" + str(bear))
        reason_str = " | ".join(reasons) if reasons else "No signals"

        if bull >= 4 and bull > bear:
            return min(bull, 5), "BUY", reason_str
        elif bear >= 4 and bear > bull:
            return min(bear, 5), "SELL", reason_str
        return max(bull, bear), "NONE", reason_str

    # ══════════════════════════════════════════════
    # MATH HELPERS
    # ══════════════════════════════════════════════
    def _bollinger_bands(self, closes, period=20, std_dev=2):
        if len(closes) < period:
            avg = sum(closes) / len(closes)
            return avg, avg, avg, 0
        recent   = closes[-period:]
        middle   = sum(recent) / period
        variance = sum((x - middle) ** 2 for x in recent) / period
        std      = math.sqrt(variance)
        upper    = middle + std_dev * std
        lower    = middle - std_dev * std
        return upper, middle, lower, upper - lower

    def _rsi(self, closes, period=14):
        gains, losses = [], []
        for i in range(1, len(closes)):
            d = closes[i] - closes[i-1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        if len(gains) < period:
            return 50
        ag = sum(gains[-period:]) / period
        al = sum(losses[-period:]) / period
        if al == 0:
            return 100
        return 100 - (100 / (1 + ag / al))

    def _ema(self, data, period):
        if not data:
            return [0.0]
        if len(data) < period:
            avg = sum(data) / len(data)
            return [avg] * len(data)
        seed = sum(data[:period]) / period
        emas = [seed] * period
        mult = 2 / (period + 1)
        for p in data[period:]:
            emas.append((p - emas[-1]) * mult + emas[-1])
        return emas

    def _macd(self, closes, fast=12, slow=26, signal=9):
        if len(closes) < slow + signal:
            return 0, 0
        ema_fast   = self._ema(closes, fast)
        ema_slow   = self._ema(closes, slow)
        min_len    = min(len(ema_fast), len(ema_slow))
        macd_line  = [ema_fast[-(min_len-i)] - ema_slow[-(min_len-i)] for i in range(min_len)]
        signal_line = self._ema(macd_line, signal)
        return macd_line[-1], signal_line[-1]

    def _stochastic(self, closes, highs, lows, period=14):
        if len(closes) < period:
            return 50
        h = max(highs[-period:])
        l = min(lows[-period:])
        if h == l:
            return 50
        return ((closes[-1] - l) / (h - l)) * 100

    def _atr(self, highs, lows, closes, period=14):
        if len(closes) < period + 1:
            return 0.001
        trs = []
        for i in range(1, len(closes)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            trs.append(tr)
        return sum(trs[-period:]) / period
