"""
bot.py — GBP/USD Triple EMA Momentum Bot (v3.1)
================================================

CHANGE v3.1: Removed SGT hardcoded session window.
All time logic now uses UTC — runs correctly on any server
(Railway, GitHub Actions, VPS in any region).

Entry window: 06:00-08:00 UTC (London Open, both GMT + BST seasons).
Max 1 trade per day. Resets at 00:00 UTC daily.
"""

import logging
from datetime import datetime
import pytz
import signals
import config
from oanda_trader   import OandaTrader
from telegram_alert import TelegramAlert

log = logging.getLogger(__name__)
UTC = pytz.utc

ASSETS = {
    'GBP_USD': {
        'sl_pips':    15,
        'tp_pips':    30,
        'max_trades': 1,
        'max_spread': 2.5,
    }
}


def run_bot(state):
    instrument = 'GBP_USD'
    asset_cfg  = ASSETS[instrument]
    alert      = TelegramAlert()

    now_utc = datetime.now(UTC)

    # Max 1 trade per day
    if state.get('trades', 0) >= asset_cfg['max_trades']:
        log.info(f'[{instrument}] 1 trade already taken today — done')
        return

    # One trade per session per day
    window_key   = f"{instrument}_london"
    windows_used = state.setdefault('windows_used', {})
    if windows_used.get(window_key):
        log.info(f'[{instrument}] Window already traded today')
        return

    try:
        trader = OandaTrader(demo=True)
        if not trader.login():
            log.warning(f'[{instrument}] OANDA login failed')
            return

        if trader.get_position(instrument):
            log.info(f'[{instrument}] Position already open — skipping')
            return

        mid, bid, ask = trader.get_price(instrument)
        if mid is None:
            log.warning(f'[{instrument}] Could not fetch price')
            return

        spread_pips = round((ask - bid) / 0.0001, 1)
        log.info(f'[{instrument}] Price={mid:.5f} Spread={spread_pips}p')

        df_h1  = trader.get_candles(instrument, 'H1',  50)
        df_m15 = trader.get_candles(instrument, 'M15', 30)

        if df_h1 is None or df_m15 is None:
            log.warning(f'[{instrument}] Candle fetch failed')
            return

        # Compute EMAs for alert
        c     = df_h1['close']
        ema5  = round(c.ewm(span=5,  adjust=False).mean().iloc[-1], 5)
        ema10 = round(c.ewm(span=10, adjust=False).mean().iloc[-1], 5)
        ema20 = round(c.ewm(span=20, adjust=False).mean().iloc[-1], 5)

        signal = signals.get_signal(
            df_h1, df_m15,
            spread_pips = spread_pips,
            tp_pips     = asset_cfg['tp_pips'],
            sl_pips     = asset_cfg['sl_pips'],
        )

        if signal is None:
            reason = 'Triple EMA not aligned — no clear trend'
            log.info(f'[{instrument}] No signal — {reason}')
            # Send scan result to Telegram every run so you can see bot is alive
            alert.send_scan_result(mid, spread_pips, ema5, ema10, ema20,
                                   signal=None, reason=reason)
            return

        direction = signal['direction']
        sl_pips   = asset_cfg['sl_pips']
        tp_pips   = asset_cfg['tp_pips']

        # Send scan result with signal
        alert.send_scan_result(mid, spread_pips, ema5, ema10, ema20,
                               signal=direction, reason='')

        balance  = trader.get_balance()
        risk_amt = balance * (config.RISK['risk_per_trade'] / 100)
        size     = max(1000, int((risk_amt / sl_pips) * 10000))
        size     = min(size, 50000)

        log.info(
            f'[{instrument}] >>> {direction}'
            f' | SL={sl_pips}p TP={tp_pips}p (2:1 RR) | size={size}'
        )

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
            log.info(f'[{instrument}] Trade placed! ID={result.get("trade_id", "?")}')

            alert.send_trade_open(
                direction   = direction,
                entry       = signal['entry_price'],
                sl          = signal['stop_loss'],
                tp          = signal['take_profit'],
                sl_pips     = sl_pips,
                tp_pips     = tp_pips,
                size        = size,
                balance_usd = balance,
            )
        else:
            log.error(f'[{instrument}] Order failed: {result.get("error")}')
            alert.send(f'❌ <b>Order Failed</b>\nGBP/USD {direction}\nError: {result.get("error")}')

    except Exception as e:
        log.error(f'[{instrument}] run_bot error: {e}', exc_info=True)
