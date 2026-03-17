"""
OANDA Trading Bot - Demo Account 2
=====================================
Strategy 1: Mean Reversion  → AUD/USD (Asian), EUR/GBP (London)
Strategy 2: Trend Following → EUR/USD (London + NY)

Session Rules (SGT):
  AUD/USD  active: 6am  - 11am  (Asian)
  EUR/GBP  active: 2pm  - 7pm   (London)
  EUR/USD  active: 2pm  - 11pm  (London + NY)

Bot sleeps silently outside active hours.
Score 4/5 minimum to trade.
"""

import os
import json
import time
import logging
import requests
from datetime import datetime
import pytz

from signals       import SignalEngine
from oanda_trader  import OandaTrader
from telegram_alert import TelegramAlert
from calendar_filter import CalendarFilter

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger(__name__)

sg_tz   = pytz.timezone("Asia/Singapore")
signals = SignalEngine()

# ── ASSET CONFIG ─────────────────────────────────────────────────────────────
ASSETS = {
    "AUD_USD": {
        "instrument": "AUD_USD",
        "asset":      "AUDUSD",
        "emoji":      "🦘",
        "strategy":   "mean_reversion",
        "pip":        0.0001,
        "precision":  5,
        "stop_pips":  8,    # $8 max loss
        "tp_pips":    12,   # $12 max profit — R:R 1:1.5
        "session_start": 6,
        "session_end":   11,
    },
    "EUR_GBP": {
        "instrument": "EUR_GBP",
        "asset":      "EURGBP",
        "emoji":      "🇪🇺",
        "strategy":   "mean_reversion",
        "pip":        0.0001,
        "precision":  5,
        "stop_pips":  6,    # $6 max loss
        "tp_pips":    9,    # $9 max profit — R:R 1:1.5
        "session_start": 14,
        "session_end":   19,
    },
    "EUR_USD": {
        "instrument": "EUR_USD",
        "asset":      "EURUSD",
        "emoji":      "🇪🇺💵",
        "strategy":   "trend_following",
        "pip":        0.0001,
        "precision":  5,
        "stop_pips":  15,   # Wider SL for trend trades
        "tp_pips":    30,   # 1:2 RR — trend trades need bigger TP
        "session_start": 14,
        "session_end":   23,
    },
}

# ── DEFAULTS ─────────────────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "signal_threshold": 4,
    "demo_mode":        True,
    "max_spread_pips":  2,
}

def load_settings():
    try:
        with open("settings.json") as f:
            saved = json.load(f)
        DEFAULT_SETTINGS.update(saved)
    except FileNotFoundError:
        with open("settings.json", "w") as f:
            json.dump(DEFAULT_SETTINGS, f, indent=2)
    return DEFAULT_SETTINGS

def is_in_session(hour, config):
    """Check if current hour is within pair's active session"""
    start = config["session_start"]
    end   = config["session_end"]
    return start <= hour < end

def set_cooldown(today, name):
    if "cooldowns" not in today:
        today["cooldowns"] = {}
    now = datetime.now(sg_tz)
    today["cooldowns"][name] = now.isoformat()
    log.info(name + " cooldown set for 30 mins")

def in_cooldown(today, name):
    cd = today.get("cooldowns", {}).get(name)
    if not cd:
        return False
    try:
        cd_time  = datetime.fromisoformat(cd).replace(tzinfo=sg_tz)
        elapsed  = (datetime.now(sg_tz) - cd_time).total_seconds() / 60
        return elapsed < 30
    except:
        return False

def run_bot():
    settings = load_settings()
    now      = datetime.now(sg_tz)
    hour     = now.hour
    calendar = CalendarFilter()
    alert    = TelegramAlert()

    log.info("Bot scan at " + now.strftime("%H:%M SGT"))

    # ── WEEKEND CHECK — silent ────────────────────────────────────────
    if now.weekday() == 5:
        log.info("Saturday - markets closed, sleeping silently")
        return
    if now.weekday() == 6 and hour < 5:
        log.info("Sunday early - sleeping silently")
        return

    # ── CHECK IF ANY PAIR IS IN SESSION ──────────────────────────────
    active_pairs = [name for name, cfg in ASSETS.items() if is_in_session(hour, cfg)]
    if not active_pairs:
        log.info("No active sessions at " + str(hour) + ":00 SGT — sleeping silently")
        return

    # ── CONNECT TO OANDA ─────────────────────────────────────────────
    trader = OandaTrader(demo=settings["demo_mode"])
    if not trader.login():
        alert.send("DEMO 2 Login FAILED! Check OANDA_API_KEY and OANDA_ACCOUNT_ID")
        return

    current_balance = trader.get_balance()
    mode            = "DEMO2"

    # ── LOAD TODAY LOG ───────────────────────────────────────────────
    trade_log = "trades_" + now.strftime("%Y%m%d") + ".json"
    try:
        with open(trade_log) as f:
            today = json.load(f)
    except FileNotFoundError:
        today = {
            "trades":        0,
            "start_balance": current_balance,
            "daily_pnl":     0.0,
            "wins":          0,
            "losses":        0,
            "consec_losses": 0,
            "cooldowns":     {},
            "open_times":    {},
        }
        with open(trade_log, "w") as f:
            json.dump(today, f, indent=2)
        log.info("New day! Start balance: $" + str(round(current_balance, 2)))

    start_balance = today.get("start_balance", current_balance)

    # ── PNL TRACKING ─────────────────────────────────────────────────
    open_pnl     = 0.0
    realized_pnl = 0.0
    try:
        realized_pnl = round(current_balance - start_balance, 2)
        for name in ASSETS:
            pos = trader.get_position(name)
            if pos:
                open_pnl += trader.check_pnl(pos)
        open_pnl  = round(open_pnl, 2)
    except Exception as e:
        log.warning("PnL error: " + str(e))

    total_pnl  = round(realized_pnl + open_pnl, 2)
    pnl_emoji  = "✅" if realized_pnl >= 0 else "🔴"
    usd_to_sgd = 1.35
    pl_sgd     = round(realized_pnl * usd_to_sgd, 2)

    # ── EOD HARD CLOSE at 10:55pm SGT ────────────────────────────────
    if hour == 22 and now.minute >= 55:
        closed = []
        for name in ASSETS:
            pos = trader.get_position(name)
            if pos:
                trader.close_position(name)
                closed.append(name)
        if closed:
            alert.send(
                "🔔 DEMO 2 EOD Close\n"
                "Closed: " + ", ".join(closed) + "\n"
                "Realized: $" + str(realized_pnl) + " USD\n"
                "= $" + str(pl_sgd) + " SGD"
            )
        return

    # ── CHECK OPEN TRADES — 1HR MAX DURATION ─────────────────────────
    for name in ASSETS:
        pos = trader.get_position(name)
        if not pos:
            continue
        try:
            trade_id = pos.get("id") or pos.get("tradeID")
            t_url    = trader.base_url + "/v3/accounts/" + trader.account_id + "/trades/" + str(trade_id)
            t_resp   = requests.get(t_url, headers=trader.headers, timeout=10)
            open_str = t_resp.json()["trade"]["openTime"]
            open_utc = datetime.fromisoformat(open_str.replace("Z", "+00:00"))
            now_utc  = datetime.now(pytz.utc)
            hours_open = (now_utc - open_utc).total_seconds() / 3600
            if hours_open >= 1.0:
                pnl    = trader.check_pnl(pos)
                emoji  = "✅" if pnl >= 0 else "🔴"
                trader.close_position(name)
                alert.send(
                    "⏰ DEMO 2 1HR LIMIT\n"
                    + ASSETS[name]["emoji"] + " " + name + "\n"
                    "Closed after " + str(round(hours_open, 1)) + "h\n"
                    "PnL: $" + str(round(pnl, 2)) + " " + emoji
                )
                log.info(name + " closed — 1hr limit reached")
        except Exception as e:
            log.warning("Duration check error " + name + ": " + str(e))

    # ── SCAN ACTIVE PAIRS ────────────────────────────────────────────
    scan_results = []

    for name, config in ASSETS.items():

        # Session check — skip silently if outside hours
        if not is_in_session(hour, config):
            continue

        # Already in trade
        pos = trader.get_position(name)
        if pos:
            pnl       = trader.check_pnl(pos)
            direction = "BUY" if int(float(pos.get("long", {}).get("units", 0))) > 0 else "SELL"
            strategy  = "MR" if config["strategy"] == "mean_reversion" else "TF"
            scan_results.append(
                config["emoji"] + " " + name + " [" + strategy + "]: " +
                direction + " open 📉 $" + str(round(pnl, 2))
            )
            continue

        # Cooldown check
        if in_cooldown(today, name):
            scan_results.append(config["emoji"] + " " + name + ": cooldown (30min)")
            continue

        # Spread check
        price, bid, ask = trader.get_price(name)
        if price is None:
            scan_results.append(config["emoji"] + " " + name + ": price error")
            continue
        spread_val = (ask - bid) / config["pip"]
        if spread_val > settings["max_spread_pips"]:
            scan_results.append(config["emoji"] + " " + name + ": spread too wide (" + str(round(spread_val, 1)) + " pips)")
            continue

        # News check
        news_active, news_reason = calendar.is_news_time(name)
        if news_active:
            scan_results.append(config["emoji"] + " " + name + ": PAUSED - " + news_reason)
            continue

        # ── GET SIGNAL ───────────────────────────────────────────────
        score, direction, details = signals.analyze(asset=config["asset"])
        strategy_label = "MR" if config["strategy"] == "mean_reversion" else "TF"
        log.info(name + " [" + strategy_label + "]: score=" + str(score) + " dir=" + direction)

        if score < settings["signal_threshold"] or direction == "NONE":
            scan_results.append(
                config["emoji"] + " " + name + " [" + strategy_label + "]: " +
                str(score) + "/5 no setup"
            )
            continue

        # ── PLACE TRADE ──────────────────────────────────────────────
        tp_pips    = config["tp_pips"]
        stop_pips  = config["stop_pips"]
        size       = 10000  # Fixed 0.10 lots
        max_loss   = round(size * stop_pips * config["pip"], 2)
        max_profit = round(size * tp_pips   * config["pip"], 2)

        result = trader.place_order(
            instrument     = name,
            direction      = direction,
            size           = size,
            stop_distance  = stop_pips,
            limit_distance = tp_pips
        )

        if result["success"]:
            today["trades"] = today.get("trades", 0) + 1
            today["consec_losses"] = 0
            if "open_times" not in today: today["open_times"] = {}
            today["open_times"][name] = now.isoformat()
            with open(trade_log, "w") as f:
                json.dump(today, f, indent=2)

            price, _, _ = trader.get_price(name)
            alert.send(
                "🔄 DEMO 2 NEW TRADE!\n"
                + config["emoji"] + " " + name + "\n"
                "Strategy:  " + ("Mean Reversion" if config["strategy"] == "mean_reversion" else "Trend Following") + "\n"
                "Direction: " + direction + "\n"
                "Score:     " + str(score) + "/5\n"
                "Size:      0.10 lots\n"
                "Entry:     " + str(round(price, config["precision"])) + "\n"
                "Stop Loss: " + str(stop_pips) + " pips = $" + str(max_loss) + "\n"
                "Take Prof: " + str(tp_pips) + " pips = $" + str(max_profit) + "\n"
                "Spread:    " + str(round(spread_val, 1)) + " pips\n"
                "Signals:   " + details
            )
            scan_results.append(
                config["emoji"] + " " + name + " [" + strategy_label + "]: " +
                direction + " PLACED! " + str(score) + "/5 ✅"
            )
        else:
            set_cooldown(today, name)
            with open(trade_log, "w") as f:
                json.dump(today, f, indent=2)
            scan_results.append(config["emoji"] + " " + name + ": order failed")

    # ── SCAN SUMMARY ─────────────────────────────────────────────────
    if realized_pnl >= 15:
        target_msg = "🎯 TARGET HIT! $" + str(round(pl_sgd, 0)) + " SGD today!"
    elif realized_pnl > 0:
        target_msg = "Profit $" + str(round(pl_sgd, 0)) + " SGD"
    elif realized_pnl < 0:
        target_msg = "Loss $" + str(abs(round(pl_sgd, 0))) + " SGD"
    else:
        target_msg = "Waiting for closed trades..."

    wins   = today.get("wins", 0)
    losses = today.get("losses", 0)
    consec = today.get("consec_losses", 0)

    # Session label
    if 6 <= hour < 11:
        session = "Asian 🇯🇵"
    elif 14 <= hour < 19:
        session = "London 🇬🇧"
    elif 19 <= hour < 23:
        session = "NY 🇺🇸"
    else:
        session = "Off-hours"

    summary = "\n".join(scan_results) if scan_results else "No active pairs this scan"

    alert.send(
        "🔄 DEMO 2 Scan | " + mode + "\n"
        "Time:     " + now.strftime("%H:%M SGT") + " | " + session + "\n"
        "Balance:  $" + str(round(current_balance, 2)) + "\n"
        "Realized: $" + str(round(realized_pnl, 2)) + " USD " + pnl_emoji + "\n"
        "= $" + str(round(pl_sgd, 2)) + " SGD\n"
        "Open PnL: $" + str(round(open_pnl, 2)) + " USD\n"
        + target_msg + "\n"
        "Trades: " + str(today.get("trades", 0)) + "\n"
        "W/L: " + str(wins) + "/" + str(losses) + " | Consec loss: " + str(consec) + "\n"
        "─────────────────────────\n"
        + summary
    )

# ── RAILWAY MAIN LOOP ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    log.info("🚀 DEMO 2 Bot starting on Railway...")
    log.info("Pairs: AUD/USD (MR Asian) | EUR/GBP (MR London) | EUR/USD (TF London+NY)")
    while True:
        try:
            run_bot()
        except Exception as e:
            log.error("Bot error: " + str(e))
        log.info("Sleeping 5 minutes...")
        time.sleep(300)
