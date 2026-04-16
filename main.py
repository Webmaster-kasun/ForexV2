"""
main.py — Entry point for GBP/USD scalp bot (Railway + GitHub Actions)

Sessions (SGT):
  06:00 – 08:00  Asian Pre-London
  07:00 – 13:00  London Open
  15:00 – 19:00  NY Overlap
  19:00 – 23:00  Late NY

FIX-01: GitHub Actions mode — runs once and exits (Actions re-fires every 5 min via cron).
FIX-02: Railway mode — polls every 5 minutes in a loop (set ENV var RAILWAY=true).
FIX-03: News filter wired in — pauses 30 min before/after high-impact USD/GBP events.
FIX-04: pandas added to requirements so candle DataFrames work.
"""

import os
import time
import logging
import traceback
from datetime import datetime
import pytz

from bot            import run_bot, ASSETS, is_in_session
from oanda_trader   import OandaTrader
from telegram_alert import TelegramAlert
from calendar_filter import EconomicCalendar

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

INTERVAL_MINUTES = 5
sg_tz            = pytz.timezone("Asia/Singapore")
STATE            = {}

SESSION_ALERTS = [
    {"start": 6,  "label": "Asian Pre-London", "desc": "06:00–08:00 SGT"},
    {"start": 7,  "label": "London Open",      "desc": "07:00–13:00 SGT"},
    {"start": 15, "label": "NY Overlap",       "desc": "15:00–19:00 SGT"},
    {"start": 19, "label": "Late NY",          "desc": "19:00–23:00 SGT"},
]

# State file path — persists across GitHub Actions runs via artifact OR env var injection
STATE_FILE = "bot_state.json"


def load_state():
    """Load persisted state from file if it exists."""
    import json
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                s = json.load(f)
                log.info(f"State loaded: {s.get('date')} | trades={s.get('trades',0)}")
                return s
    except Exception as e:
        log.warning(f"State load failed: {e}")
    return {}


def save_state(state):
    """Persist state so next GitHub Actions run knows trades already taken."""
    import json
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
        log.info(f"State saved: {state.get('date')} | trades={state.get('trades',0)}")
    except Exception as e:
        log.warning(f"State save failed: {e}")


def fresh_day_state(today_str, balance):
    return {
        "date":            today_str,
        "trades":          0,
        "start_balance":   balance,
        "daily_pnl":       0.0,
        "stopped":         False,
        "wins":            0,
        "losses":          0,
        "consec_losses":   0,
        "cooldowns":       {},
        "open_times":      {},
        "news_alerted":    {},
        "windows_used":    {},
        "session_alerted": {},
    }


def check_env_vars():
    api_key    = os.environ.get("OANDA_API_KEY", "")
    account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
    tg_token   = os.environ.get("TELEGRAM_TOKEN", "")
    tg_chat    = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not api_key or not account_id:
        log.error("=" * 50)
        log.error("❌ MISSING OANDA ENV VARS!")
        log.error("   OANDA_API_KEY    : " + ("SET ✅" if api_key    else "MISSING ❌"))
        log.error("   OANDA_ACCOUNT_ID : " + ("SET ✅" if account_id else "MISSING ❌"))
        log.error("=" * 50)
        return False

    log.info("Env vars OK | Key: " + api_key[:8] + "**** | Account: " + account_id)

    if not tg_token or not tg_chat:
        log.warning("Telegram not configured — no alerts will be sent")

    return True


def check_session_open_alerts(alert, state):
    now   = datetime.now(sg_tz)
    hour  = now.hour
    today = now.strftime("%Y%m%d")

    session_alerted = state.setdefault("session_alerted", {})

    for w in SESSION_ALERTS:
        if hour != w["start"]:
            continue
        akey = f"session_open_{today}_{w['label']}"
        if session_alerted.get(akey):
            continue

        session_alerted[akey] = True
        balance = state.get("start_balance", 0.0)
        alert.send(
            f"🔔 {w['label']} Window Open!\n"
            f"⏰ {now.strftime('%H:%M SGT')} ({w['desc']})\n"
            f"Balance: ${round(balance, 2)}\n"
            f"Scanning GBP/USD..."
        )


def run_once(state, calendar):
    """One polling cycle — called by GitHub Actions (run once) or Railway loop."""
    global STATE

    now   = datetime.now(sg_tz)
    today = now.strftime("%Y%m%d")
    log.info("⏰ " + now.strftime("%Y-%m-%d %H:%M SGT"))

    # Reset state at start of each new day
    if state.get("date") != today:
        log.info("📅 New day — fetching balance...")
        try:
            trader  = OandaTrader(demo=True)
            balance = trader.get_balance() if trader.login() else 0.0
        except Exception as e:
            log.warning("Balance fetch error: " + str(e))
            balance = 0.0
        log.info(f"📅 New day! Balance: ${round(balance, 2)}")
        state = fresh_day_state(today, balance)
        STATE = state

    alert = TelegramAlert()
    check_session_open_alerts(alert, state)

    # News filter — skip if blackout window
    is_news, news_reason = calendar.is_news_time("GBP_USD")
    if is_news:
        log.warning(f"📰 NEWS BLACKOUT — skipping: {news_reason}")
        news_alerted = state.setdefault("news_alerted", {})
        nkey = f"news_{today}_{news_reason[:40]}"
        if not news_alerted.get(nkey):
            news_alerted[nkey] = True
            alert.send(f"📰 News Blackout!\n{news_reason}\nBot paused 30 min.")
        return state

    run_bot(state=state)
    return state


def main():
    global STATE

    log.info("=" * 50)
    log.info("🚀 GBP/USD Scalp Bot — Fixed Build")
    log.info("Session 1: 06:00–08:00 SGT  Asian Pre-London")
    log.info("Session 2: 07:00–13:00 SGT  London Open")
    log.info("Session 3: 15:00–19:00 SGT  NY Overlap")
    log.info("Session 4: 19:00–23:00 SGT  Late NY")
    log.info("GBP/USD | SL=13pip | TP=26pip | Max 4 trades/day")
    log.info("=" * 50)

    if not check_env_vars():
        log.error("Missing env vars — exiting")
        return

    calendar = EconomicCalendar()

    # Detect run mode:
    # - RAILWAY=true  → loop forever (Railway worker)
    # - Default       → run once and exit (GitHub Actions fires every 5 min via cron)
    is_railway = os.environ.get("RAILWAY", "").lower() in ("true", "1", "yes")

    if is_railway:
        log.info("🚂 Railway mode — polling loop active")
        alert = TelegramAlert()
        alert.send(
            "🚀 Bot Started (Railway)!\n"
            "Pair: GBP/USD\n"
            "SL: 13 pip | TP: 26 pip\n"
            "Sessions: 06–08 / 07–13 / 15–19 / 19–23 SGT\n"
            "Max 4 trades/day | News filter ON"
        )
        STATE = load_state()
        while True:
            try:
                STATE = run_once(STATE, calendar)
                save_state(STATE)
            except Exception as e:
                log.error("❌ Bot error: " + str(e))
                log.error(traceback.format_exc())
                time.sleep(30)
            log.info(f"💤 Sleeping {INTERVAL_MINUTES} mins...")
            time.sleep(INTERVAL_MINUTES * 60)

    else:
        # GitHub Actions mode — single shot
        log.info("⚡ GitHub Actions mode — single run")
        STATE = load_state()
        try:
            STATE = run_once(STATE, calendar)
            save_state(STATE)
        except Exception as e:
            log.error("❌ Bot error: " + str(e))
            log.error(traceback.format_exc())


if __name__ == "__main__":
    main()
