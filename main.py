"""
main.py — Entry point for GBP/USD Triple EMA Momentum Bot (v3.1)
=================================================================

CHANGE v3.1: All time logic uses UTC. Daily state resets at 00:00 UTC.
Works on any server timezone — Railway, GitHub Actions, any VPS region.

Run modes:
  GitHub Actions — single shot per cron trigger (cron fires every 5 min)
  Railway        — polling loop every 5 minutes (set RAILWAY=true env var)
"""

import os
import time
import logging
import traceback
from datetime import datetime
import pytz

from bot             import run_bot
from oanda_trader    import OandaTrader
from telegram_alert  import TelegramAlert
from calendar_filter import EconomicCalendar

logging.basicConfig(
    level  = logging.INFO,
    format = '%(asctime)s | %(levelname)s | %(message)s',
)
log = logging.getLogger(__name__)

UTC              = pytz.utc
INTERVAL_MINUTES = 5
STATE            = {}
STATE_FILE       = 'bot_state.json'


def load_state() -> dict:
    import json
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                s = json.load(f)
                log.info(f"State loaded: {s.get('date')} | trades={s.get('trades', 0)}")
                return s
    except Exception as e:
        log.warning(f'State load failed: {e}')
    return {}


def save_state(state: dict):
    import json
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        log.warning(f'State save failed: {e}')


def fresh_day_state(today_str: str, balance: float) -> dict:
    return {
        'date':         today_str,
        'trades':       0,
        'start_balance': balance,
        'windows_used': {},
        'news_alerted': {},
    }


def check_env_vars() -> bool:
    api_key    = os.environ.get('OANDA_API_KEY', '')
    account_id = os.environ.get('OANDA_ACCOUNT_ID', '')

    if not api_key or not account_id:
        log.error('MISSING ENV VARS: OANDA_API_KEY or OANDA_ACCOUNT_ID not set')
        return False

    tg_token = os.environ.get('TELEGRAM_TOKEN', '')
    tg_chat  = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not tg_token or not tg_chat:
        log.warning('Telegram not configured — no alerts will be sent')

    log.info(f'Env OK | Key: {api_key[:8]}**** | Account: {account_id}')
    return True


def run_once(state: dict, calendar: EconomicCalendar) -> dict:
    global STATE

    now_utc = datetime.now(UTC)
    today   = now_utc.strftime('%Y-%m-%d')

    log.info(f'UTC: {now_utc.strftime("%Y-%m-%d %H:%M")}')

    alert = TelegramAlert()

    # Reset state at UTC midnight — send new day alert
    if state.get('date') != today:
        log.info('New UTC day — resetting state...')
        try:
            trader  = OandaTrader(demo=True)
            balance = trader.get_balance() if trader.login() else 0.0
        except Exception as e:
            log.warning(f'Balance fetch error: {e}')
            balance = 0.0
        state = fresh_day_state(today, balance)
        STATE = state
        log.info(f'New day: {today} | Balance: ${balance:.2f}')
        alert.send_new_day(balance, today)

    # News blackout filter
    is_news, news_reason = calendar.is_news_time('GBP_USD')
    if is_news:
        log.warning(f'NEWS BLACKOUT — skipping: {news_reason}')
        news_alerted = state.setdefault('news_alerted', {})
        nkey = f"news_{today}_{news_reason[:40]}"
        if not news_alerted.get(nkey):
            news_alerted[nkey] = True
            alert.send_news_blackout(news_reason)
        return state

    run_bot(state=state)
    return state


def main():
    global STATE

    log.info('=' * 55)
    log.info('GBP/USD Triple EMA Momentum Bot v3.1')
    log.info('Entry window: 06:00-08:00 UTC (London Open)')
    log.info('SL: 15 pips | TP: 30 pips | RR: 2:1')
    log.info('Max 1 trade/day | Triple EMA trend filter')
    log.info('Timezone: UTC (works on any server region)')
    log.info('=' * 55)

    if not check_env_vars():
        return

    calendar  = EconomicCalendar()
    is_railway = os.environ.get('RAILWAY', '').lower() in ('true', '1', 'yes')

    if is_railway:
        log.info('Railway mode — polling every 5 minutes')
        try:
            trader  = OandaTrader(demo=True)
            balance = trader.get_balance() if trader.login() else 0.0
        except Exception:
            balance = 0.0
        now_utc = datetime.now(UTC)
        TelegramAlert().send_startup(balance, now_utc.strftime('%Y-%m-%d'))
        STATE = load_state()
        while True:
            try:
                STATE = run_once(STATE, calendar)
                save_state(STATE)
            except Exception as e:
                log.error(f'Bot error: {e}')
                log.error(traceback.format_exc())
                time.sleep(30)
            log.info(f'Sleeping {INTERVAL_MINUTES} min...')
            time.sleep(INTERVAL_MINUTES * 60)

    else:
        log.info('GitHub Actions mode — single run')
        STATE = load_state()
        try:
            STATE = run_once(STATE, calendar)
            save_state(STATE)
        except Exception as e:
            log.error(f'Bot error: {e}')
            log.error(traceback.format_exc())


if __name__ == '__main__':
    main()
