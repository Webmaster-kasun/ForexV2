"""
mt5_bot.py
==========
Live GBP/USD Asian Range Breakout + Liquidity Sweep trading bot.
Compatible with MetaTrader 5 Python API.

USAGE:
    python mt5_bot.py

REQUIREMENTS:
    pip install MetaTrader5 pandas numpy schedule

SETUP:
    1. Open MetaTrader 5 desktop application
    2. Log in to your broker account
    3. Enable "Allow Algo Trading" in MT5 settings
    4. Set your config values in config.py or environment variables
    5. Run: python mt5_bot.py

SESSIONS (London Time):
    Asian range calculation: 00:00 – 06:00
    Signal window:          07:00 – 11:30
"""

import time
import logging
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np

from strategy import compute_asian_range, scan_for_signal

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
SYMBOL           = 'GBPUSD'
TIMEFRAME_STR    = 'M15'
MAX_ASIAN_RANGE  = 35      # pips — only trade on tight Asian sessions
TP_PIPS          = 35      # take profit (optimised)
SL_PIPS          = 18      # stop loss (optimised)
RISK_PCT         = 0.5     # % of account balance to risk per trade
MAX_SPREAD_PIPS  = 2.5     # skip if spread > this
MAGIC_NUMBER     = 20260101
STATE_FILE       = 'bot_state.json'
POLL_SECONDS     = 60      # check every 60 seconds


# ── MT5 helpers ───────────────────────────────────────────────────────────────

def mt5_init():
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            log.error(f'MT5 initialize failed: {mt5.last_error()}')
            return None, None
        info = mt5.account_info()
        log.info(f'MT5 connected | Account: {info.login} | Balance: ${info.balance:.2f}')
        return mt5, info.balance
    except ImportError:
        log.error('MetaTrader5 not installed. Run: pip install MetaTrader5')
        return None, None


def get_bars(mt5, symbol: str, timeframe_str: str, count: int) -> pd.DataFrame | None:
    tf_map = {
        'M5': 5, 'M15': 15, 'M30': 18442240,
        'H1': 16385, 'H4': 16388, 'D1': 16408,
    }
    # Use MT5 timeframe constants
    tf_const_map = {
        'M5':  mt5.TIMEFRAME_M5,
        'M15': mt5.TIMEFRAME_M15,
        'M30': mt5.TIMEFRAME_M30,
        'H1':  mt5.TIMEFRAME_H1,
        'H4':  mt5.TIMEFRAME_H4,
        'D1':  mt5.TIMEFRAME_D1,
    }
    tf = tf_const_map.get(timeframe_str, mt5.TIMEFRAME_M15)
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df.set_index('time')[['open','high','low','close']]
    return df


def get_spread_pips(mt5, symbol: str) -> float:
    info = mt5.symbol_info_tick(symbol)
    if info is None:
        return 99.0
    return round((info.ask - info.bid) / 0.0001, 1)


def place_order(mt5, symbol, direction, lot_size, sl_price, tp_price):
    tick    = mt5.symbol_info_tick(symbol)
    price   = tick.ask if direction == 'BUY' else tick.bid
    action  = mt5.ORDER_TYPE_BUY if direction == 'BUY' else mt5.ORDER_TYPE_SELL

    request = {
        'action':    mt5.TRADE_ACTION_DEAL,
        'symbol':    symbol,
        'volume':    lot_size,
        'type':      action,
        'price':     price,
        'sl':        sl_price,
        'tp':        tp_price,
        'deviation': 10,
        'magic':     MAGIC_NUMBER,
        'comment':   'AsianBreakout',
        'type_time': mt5.ORDER_TIME_GTC,
        'type_filling': mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    return result


def calc_lot_size(balance: float, sl_pips: float,
                  risk_pct: float = RISK_PCT) -> float:
    """
    Calculate lot size based on % risk.
    GBP/USD: 1 pip = $10 per standard lot (1.0).
    lot = (balance * risk_pct/100) / (sl_pips * pip_value_per_lot)
    """
    pip_value  = 10.0     # USD per pip per standard lot for GBP/USD
    risk_usd   = balance * (risk_pct / 100)
    lot        = risk_usd / (sl_pips * pip_value)
    lot        = round(max(0.01, min(lot, 10.0)), 2)   # clamp 0.01–10.0
    return lot


def has_open_position(mt5, symbol: str) -> bool:
    positions = mt5.positions_get(symbol=symbol)
    return positions is not None and len(positions) > 0


# ── State management ──────────────────────────────────────────────────────────

def load_state() -> dict:
    if Path(STATE_FILE).exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def reset_daily_state(today: str, balance: float) -> dict:
    return {
        'date':    today,
        'traded':  False,
        'balance': balance,
    }


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    log.info('=' * 60)
    log.info('Asian Range Breakout Bot — GBP/USD')
    log.info(f'Config: AR<{MAX_ASIAN_RANGE}p | TP={TP_PIPS}p | SL={SL_PIPS}p | Risk={RISK_PCT}%')
    log.info('Sessions: Asian 00:00-06:00 | Signal 07:00-11:30 (LDN)')
    log.info('=' * 60)

    mt5, balance = mt5_init()
    if mt5 is None:
        return

    state = load_state()

    while True:
        try:
            now      = datetime.now(timezone.utc)
            ldn_hour = (now.hour + 0) % 24     # UTC = London (adjust for BST: +1 in summer)
            ldn_min  = now.minute
            today    = now.strftime('%Y-%m-%d')

            # Daily reset
            if state.get('date') != today:
                acct    = mt5.account_info()
                balance = acct.balance if acct else balance
                state   = reset_daily_state(today, balance)
                save_state(state)
                log.info(f'New day: {today} | Balance: ${balance:.2f}')

            # Only scan during London window (07:00–11:30)
            in_window = 7 <= ldn_hour < 11 or (ldn_hour == 11 and ldn_min <= 30)
            if not in_window:
                time.sleep(POLL_SECONDS)
                continue

            # Skip if already traded today
            if state.get('traded'):
                time.sleep(POLL_SECONDS)
                continue

            # Skip if position already open
            if has_open_position(mt5, SYMBOL):
                log.info('Position already open — skipping')
                time.sleep(POLL_SECONDS)
                continue

            # Spread check
            spread = get_spread_pips(mt5, SYMBOL)
            if spread > MAX_SPREAD_PIPS:
                log.info(f'Spread too wide: {spread} pips > {MAX_SPREAD_PIPS}')
                time.sleep(POLL_SECONDS)
                continue

            # Fetch M15 bars (need ~60 bars to cover the Asian session + London)
            bars = get_bars(mt5, SYMBOL, TIMEFRAME_STR, 100)
            if bars is None or len(bars) < 30:
                log.warning('Not enough bars')
                time.sleep(POLL_SECONDS)
                continue

            # Get today's bars only (from midnight)
            day_start = pd.Timestamp(today)
            day_bars  = bars[bars.index.normalize() >= day_start]

            # Compute Asian range
            ah, al, ar = compute_asian_range(day_bars)
            if ah is None:
                log.info('Asian range not yet calculable (pre-06:00)')
                time.sleep(POLL_SECONDS)
                continue

            if ar >= MAX_ASIAN_RANGE:
                log.info(f'Asian range too wide: {ar:.1f}p >= {MAX_ASIAN_RANGE}p — skip day')
                state['traded'] = True    # don't trade today
                save_state(state)
                time.sleep(POLL_SECONDS)
                continue

            log.info(f'Asian range: {ar:.1f}p | AH={ah} | AL={al} | Spread={spread}p')

            # Scan for signal
            signal = scan_for_signal(day_bars, ah, al,
                                     tp_pips=TP_PIPS, sl_pips=SL_PIPS)
            if signal is None:
                log.info(f'No signal yet ({ldn_hour:02d}:{ldn_min:02d} LDN)')
                time.sleep(POLL_SECONDS)
                continue

            # ── PLACE ORDER ───────────────────────────────────────────────
            acct     = mt5.account_info()
            balance  = acct.balance
            lot_size = calc_lot_size(balance, SL_PIPS)

            log.info(f'SIGNAL: {signal["direction"]} | EP≈{signal["entry_price"]} '
                     f'SL={signal["stop_loss"]} TP={signal["take_profit"]} '
                     f'Lots={lot_size}')

            result = place_order(
                mt5, SYMBOL, signal['direction'], lot_size,
                signal['stop_loss'], signal['take_profit']
            )

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log.info(f'✅ Order placed! Ticket={result.order} '
                         f'| {signal["direction"]} {lot_size} lots')
                state['traded']       = True
                state['last_signal']  = signal['direction']
                state['last_entry']   = str(signal['entry_price'])
                save_state(state)
            else:
                err = result.comment if result else 'Unknown error'
                log.error(f'❌ Order failed: {err}')

        except Exception as e:
            log.error(f'Bot error: {e}', exc_info=True)

        time.sleep(POLL_SECONDS)


if __name__ == '__main__':
    run()
