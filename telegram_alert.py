"""
telegram_alert.py — Multi-Pair Telegram Alerts (SGD account)
"""
import os
import requests
import logging
from datetime import datetime
import pytz

log   = logging.getLogger(__name__)
sg_tz = pytz.timezone("Asia/Singapore")


class TelegramAlert:
    def __init__(self):
        self.token   = os.environ.get("TELEGRAM_TOKEN", "")
        self.chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    def send(self, message: str) -> bool:
        if not self.token or not self.chat_id:
            log.warning("Telegram not configured")
            return False
        try:
            now  = datetime.now(sg_tz).strftime("%H:%M SGT")
            text = f"🤖 Multi-Pair Bot  |  {now}\n{'━'*26}\n{message}"
            url  = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML"}
            r    = requests.post(url, data=data, timeout=10)
            if r.status_code == 200:
                log.info("Telegram sent!")
                return True
            # Retry plain text
            plain = text.replace("<b>","").replace("</b>","").replace("<i>","").replace("</i>","")
            data.update({"text": plain})
            data.pop("parse_mode", None)
            requests.post(url, data=data, timeout=10)
            return False
        except Exception as e:
            log.error("Telegram error: %s", e)
            return False

    def send_startup(self, balance: float, mode: str = "DEMO"):
        mode_emoji = "🟡" if mode == "DEMO" else "🔴"
        self.send(
            f"{mode_emoji} <b>Multi-Pair Bot Started — {mode}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance:    <b>SGD {balance:,.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🇬🇧 GBP/USD   Triple EMA  SL=15p TP=30p\n"
            f"   Session:  15:00–19:00 SGT (London)\n"
            f"🇪🇺 EUR/USD   4-Layer     SL=13p TP=26p\n"
            f"   Sessions: 15:00–19:00 + 20:00–00:00 SGT\n"
            f"🇦🇺 AUD/USD   Triple EMA  SL=15p TP=30p\n"
            f"   Sessions: 07:00–10:00 + 15:00–19:00 SGT\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Scanning all pairs every 5 min"
        )

    def send_new_day(self, balance: float, date: str):
        self.send(
            f"🌅 <b>New Trading Day — {date}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance:  <b>SGD {balance:,.2f}</b>\n"
            f"🇬🇧 GBP/USD  🇪🇺 EUR/USD  🇦🇺 AUD/USD\n"
            f"🔍 All pairs armed and scanning..."
        )

    def send_session_open(self, pair: str, emoji: str, session_label: str,
                          session_hours: str, balance: float,
                          trades_today: int, wins: int, losses: int):
        session_flag = "🇬🇧" if session_label == "London" else \
                       "🇺🇸" if session_label == "NY" else "🌏"
        wr = f"{round(wins/(wins+losses)*100)}%" if (wins+losses) > 0 else "—"
        self.send(
            f"{session_flag} <b>{session_label} Session OPEN</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} Pair:      {pair.replace('_','/')}\n"
            f"⏰ Window:   {session_hours} SGT\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance:  SGD {balance:,.2f}\n"
            f"📊 Today:    {trades_today} trade(s)\n"
            f"🏆 W/L:      {wins}W / {losses}L  ({wr})\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 Scanning every 5 min..."
        )

    def send_trade_open(self, pair: str, emoji: str, direction: str,
                        entry_price: float, sl_pips: int, tp_pips: int,
                        size: int, spread: float, score: int,
                        session_label: str, layer_breakdown: dict,
                        balance: float, trades_today: int):
        icon = "🟢" if direction == "BUY" else "🔴"
        rr   = round(tp_pips / sl_pips, 1)

        layers_str = ""
        if layer_breakdown:
            layers_str = "\n━━━━━━━━━━━━━━━━━━━━━\n"
            for layer, status in layer_breakdown.items():
                layers_str += f"  {layer}: {status}\n"

        self.send(
            f"{icon} <b>Trade Opened — {direction}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} Pair:      {pair.replace('_','/')}\n"
            f"📌 Direction: <b>{direction}</b>\n"
            f"🎯 Entry:     {entry_price:.5f}\n"
            f"🛡 SL:        -{sl_pips} pips\n"
            f"✅ TP:        +{tp_pips} pips\n"
            f"⚖️ RR:         1 : {rr}\n"
            f"📡 Spread:    {spread:.1f} pips\n"
            f"📦 Size:      {size:,} units\n"
            f"🔢 Session:   {session_label}"
            f"{layers_str}"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance:   SGD {balance:,.2f}\n"
            f"📊 Trade #{trades_today} today"
        )

    def send_tp_hit(self, pair: str, emoji: str, pnl: float, balance: float,
                    wins: int, losses: int, open_px: float, close_px: float):
        wr = f"{round(wins/(wins+losses)*100)}%" if (wins+losses) > 0 else "—"
        self.send(
            f"✅ <b>Take Profit Hit!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} Pair:      {pair.replace('_','/')}\n"
            f"📌 Entry:     {open_px:.5f}\n"
            f"🏁 Exit:      {close_px:.5f}\n"
            f"💵 P/L:       <b>+SGD {pnl:,.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance:   SGD {balance:,.2f}\n"
            f"🏆 W/L:       {wins}W / {losses}L  ({wr})"
        )

    def send_sl_hit(self, pair: str, emoji: str, pnl: float, balance: float,
                    wins: int, losses: int, open_px: float, close_px: float):
        wr = f"{round(wins/(wins+losses)*100)}%" if (wins+losses) > 0 else "—"
        self.send(
            f"❌ <b>Stop Loss Hit</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} Pair:      {pair.replace('_','/')}\n"
            f"📌 Entry:     {open_px:.5f}\n"
            f"🏁 Exit:      {close_px:.5f}\n"
            f"💵 P/L:       <b>SGD {pnl:,.2f}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance:   SGD {balance:,.2f}\n"
            f"🏆 W/L:       {wins}W / {losses}L  ({wr})\n"
            f"⏸ 30min cooldown active"
        )

    def send_news_block(self, pair: str, emoji: str, reason: str):
        self.send(
            f"📰 <b>News Block</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{emoji} {pair.replace('_','/')} paused\n"
            f"⚠️ {reason}\n"
            f"⏸ Trading paused 30 min"
        )

    def send_daily_summary(self, balance: float, start_balance: float,
                           trades: int, wins: int, losses: int, pnl: float):
        pnl_sign = "+" if pnl >= 0 else ""
        wr = f"{round(wins/(wins+losses)*100)}%" if (wins+losses) > 0 else "—"
        self.send(
            f"📊 <b>Daily Summary</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Balance:   <b>SGD {balance:,.2f}</b>\n"
            f"📈 Day P/L:   {pnl_sign}SGD {pnl:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Trades:    {trades}\n"
            f"🏆 W/L:       {wins}W / {losses}L  ({wr})\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🌙 Bot resting until next session"
        )
