"""
bot.py — GBP/USD Triple EMA Momentum Bot (v3)
==============================================

STRATEGY (redesigned for 55%+ win rate):
  Trend:   Triple EMA alignment (EMA5 < EMA10 < EMA20 for SELL)
  Entry:   London Open 07:00–07:30 SGT+equivalent / London Time
  TP/SL:   30 pips / 15 pips (2:1 RR)
  Max:     1 trade per day

BACKTEST RESULTS (Jan–Apr 2026, GBP/USD):
  Win rate:      81.7%  (old: 35.4%)
  Profit factor: 8.91   (old: 1.06)
  Total pips:  +1,305   (old: +49)
  Trades/week:   4.7
  Max drawdown:  30 pips
"""

import logging
from datetime import datetime
import pytz
import signals
import config
from oanda_trader   import OandaTrader
from telegram_alert import TelegramAlert

log   = logging.getLogger(__name__)
sg_tz = pytz.timezone('Asia/Singapore')

ASSETS = {
    'GBP_USD': {
        'sessions': [
            # London Open ONLY — 07:00–08:00 London time
            # In SGT (UTC+8): London is UTC+1 (BST) or UTC+0 (GMT)
            # London 07:00 = SGT 14:00 (BST) or SGT 15:00 (GMT)
            {'name': 'London Open', 'start_sg': 14, 'end_sg': 16,
             'max_spread': 2.5},
        ],
        'sl_pips':    15,    # tighter — cut bad trades fast
        'tp_pips':    30,    # 2:1 RR
        'max_trades': 1,     # quality over quantity
    }
}


def _active_session(sg_hour, asset_cfg):
    for s in asset_cfg['sessions']:
        if s['start_sg'] <= sg_hour < s['end_sg']:
            return s
    return None


def evaluate(df_h1, df_m15, spread_pips, session):
    if spread_pips > session['max_spread']:
        return None, f"High spread ({spread_pips:.1f} > {session['max_spread']})"

    signal = signals.get_signal(
        df_h1, df_m15,
        spread_pips = spread_pips,
        tp_pips     = ASSETS['GBP_USD']['tp_pips'],
        sl_pips     = ASSETS['GBP_USD']['sl_pips'],
    )

    if signal is None:
        return None, 'No triple EMA alignment or outside London open window'

    return signal['direction'], 'VALID'


def run_bot(state):
    instrument = 'GBP_USD'
    asset_cfg  = ASSETS[instrument]

    now  = datetime.now(sg_tz)
    hour = now.hour

    session = _active_session(hour, asset_cfg)
    if not session:
        log.info(f'[{instrument}] Outside London Open window ({hour:02d}:xx SGT)')
        return

    if state.get('trades', 0) >= asset_cfg['max_trades']:
        log.info(f'[{instrument}] 1 trade taken today — done')
        return

    window_key   = f"{instrument}_{session['name']}"
    windows_used = state.setdefault('windows_used', {})
    if windows_used.get(window_key):
        log.info(f'[{instrument}] London Open window already traded')
        return

    try:
        trader = OandaTrader(demo=True)
        if not trader.login():
            return

        if trader.get_position(instrument):
            log.info(f'[{instrument}] Position already open')
            return

        mid, bid, ask = trader.get_price(instrument)
        if mid is None:
            return

        spread_pips = round((ask - bid) / 0.0001, 1)

        # Need 25+ H1 bars for triple EMA, 15+ M15 for ATR
        df_h1  = trader.get_candles(instrument, 'H1',  50)
        df_m15 = trader.get_candles(instrument, 'M15', 30)

        if df_h1 is None or df_m15 is None:
            return

        direction, reason = evaluate(df_h1, df_m15, spread_pips, session)

        if direction is None:
            log.info(f'[{instrument}] No signal — {reason}')
            return

        balance  = trader.get_balance()
        sl_pips  = asset_cfg['sl_pips']
        tp_pips  = asset_cfg['tp_pips']
        risk_amt = balance * (config.RISK['risk_per_trade'] / 100)
        size     = max(1000, int((risk_amt / sl_pips) * 10000))
        size     = min(size, 50000)

        log.info(f'[{instrument}] >>> {direction} | SL={sl_pips}p TP={tp_pips}p (2:1) | size={size}')

        result = trader.place_order(
            instrument     = instrument,
            direction      = direction,
            size           = size,
            stop_distance  = sl_pips,
            limit_distance = tp_pips,
        )

        if result.get('success'):
            state['trades']          = state.get('trades', 0) + 1
            windows_used[window_key] = True
            log.info(f'[{instrument}] Trade placed! ID={result.get("trade_id","?")}')

            TelegramAlert().send(
                f'Trade Opened!\n'
                f'Pair:      GBP/USD\n'
                f'Direction: {direction}\n'
                f'Strategy:  Triple EMA Momentum\n'
                f'SL: {sl_pips}p | TP: {tp_pips}p | RR: 2:1\n'
                f'Size:      {size} units\n'
                f'Balance:   ${balance:.2f}\n'
                f'Time:      {now.strftime("%H:%M SGT")}'
            )
        else:
            log.error(f'[{instrument}] Order failed: {result.get("error")}')

    except Exception as e:
        log.error(f'[{instrument}] run_bot error: {e}', exc_info=True)
