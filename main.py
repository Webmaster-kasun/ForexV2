"""
main.py — Railway entry point for OANDA GBP/USD scalp bot

Sessions (SGT):
  06:00 – 08:00  Asian Pre-London
  07:00 – 13:00  London Open
  15:00 – 19:00  NY Overlap
  19:00 – 23:00  Late NY

Max 4 trades/day, 1 per session window.
Polls every 5 minutes.
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger(__name__)

INTERVAL_MINUTES = 5
sg_tz            = pytz.timezone("Asia/Singapore")
STATE            = {}

# Session open-alert definitions — must mirror ASSETS sessions in bot.py
SESSION_ALERTS = [
    {"start": 6,  "label": "Asian Pre-London", "desc": "06:00–08:00 SGT"},
    {"start": 7,  "label": "London Open",      "desc": "07:00–13:00 SGT"},
    {"start": 15, "label": "NY Overlap",       "desc": "15:00–19:00 SGT"},
    {"start": 19, "label": "Late NY",          "desc": "19:00–23:00 SGT"},
]


def fresh_day_state(today_str, balance):
    return {
        "date":               today_str,
        "trades":             0,
        "start_balance":      balance,
        "daily_pnl":          0.0,
        "stopped":            False,
        "wins":               0,
        "losses":             0,
        "consec_losses":      0,
        "cooldowns":          {},
        "open_times":         {},
        "news_alerted":       {},
        "windows_used":       {},
        "session_alerted":    {},
        "login_fail_alerted": {},
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


def check_session_open_alerts(alert):
    """Send one Telegram alert at the opening of each session window, once per day."""
    now   = datetime.now(sg_tz)
    hour  = now.hour
    today = now.strftime("%Y%m%d")

    session_alerted = STATE.setdefault("session_alerted", {})

    for w in SESSION_ALERTS:
        if hour != w["start"]:
            continue
        akey = f"session_open_{today}_{w['label']}"
        if session_alerted.get(akey):
            continue

        session_alerted[akey] = True
        balance = STATE.get("start_balance", 0.0)
        alert.send(
            f"🔔 {w['label']} Window Open!\n"
            f"⏰ {now.strftime('%H:%M SGT')} ({w['desc']})\n"
            f"Balance: ${round(balance, 2)}\n"
            f"Scanning GBP/USD..."
        )


def main():
    global STATE

    log.info("=" * 50)
    log.info("🚀 GBP/USD Scalp Bot — OANDA / Railway")
    log.info("Session 1: 06:00–08:00 SGT  Asian Pre-London")
    log.info("Session 2: 07:00–13:00 SGT  London Open")
    log.info("Session 3: 15:00–19:00 SGT  NY Overlap")
    log.info("Session 4: 19:00–23:00 SGT  Late NY")
    log.info("GBP/USD | SL=13pip | TP=26pip | Max 4 trades/day")
    log.info("=" * 50)

    if not check_env_vars():
        log.error("Missing env vars — sleeping 60s then exiting")
        time.sleep(60)
        return

    alert = TelegramAlert()
    alert.send(
        "🚀 Bot Started!\n"
        "Pair: GBP/USD\n"
        "SL: 13 pip | TP: 26 pip\n"
        "Session 1: 06:00–08:00 SGT (Asian Pre-London)\n"
        "Session 2: 07:00–13:00 SGT (London Open)\n"
        "Session 3: 15:00–19:00 SGT (NY Overlap)\n"
        "Session 4: 19:00–23:00 SGT (Late NY)\n"
        "Max 4 trades/day | 1 per session"
    )

    while True:
        try:
            now   = datetime.now(sg_tz)
            today = now.strftime("%Y%m%d")
            log.info("⏰ " + now.strftime("%Y-%m-%d %H:%M SGT"))

            # Reset state at start of each new day
            if STATE.get("date") != today:
                log.info("📅 New day — fetching balance...")
                try:
                    trader  = OandaTrader(demo=True)
                    balance = trader.get_balance() if trader.login() else 0.0
                except Exception as e:
                    log.warning("Balance fetch error: " + str(e))
                    balance = 0.0
                log.info(f"📅 New day! Balance: ${round(balance, 2)}")
                STATE = fresh_day_state(today, balance)

            check_session_open_alerts(alert)

            run_bot(state=STATE)

        except Exception as e:
            log.error("❌ Bot error: " + str(e))
            log.error(traceback.format_exc())
            time.sleep(30)   # crash-loop protection

        log.info(f"💤 Sleeping {INTERVAL_MINUTES} mins...")
        time.sleep(INTERVAL_MINUTES * 60)


if __name__ == "__main__":
    main()
