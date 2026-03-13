"""
Railway Entry Point - OANDA Demo 2 Mean Reversion Bot
======================================================
Railway runs this 24/7 as a continuous process.
Runs bot every 5 minutes with IN-MEMORY state
(Railway filesystem is ephemeral - no file storage!)
"""

import time
import logging
import traceback
import json
from datetime import datetime, date
import pytz

from bot import run_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger(__name__)

INTERVAL_MINUTES = 5

# ── IN-MEMORY STATE (persists across 5-min runs, resets on restart) ──────────
# This replaces trades_YYYYMMDD.json file storage
STATE = {}

def get_today_key():
    sg_tz = pytz.timezone("Asia/Singapore")
    return datetime.now(sg_tz).strftime("%Y%m%d")

def main():
    sg_tz   = pytz.timezone("Asia/Singapore")
    global STATE

    log.info("=" * 50)
    log.info("🚀 Railway Bot Started - OANDA Demo 2")
    log.info("Strategy: Mean Reversion")
    log.info("Interval: Every " + str(INTERVAL_MINUTES) + " minutes")
    log.info("=" * 50)

    while True:
        now     = datetime.now(sg_tz)
        today   = now.strftime("%Y%m%d")
        log.info("⏰ " + now.strftime("%Y-%m-%d %H:%M SGT"))

        # Reset state at midnight SGT (new trading day)
        if STATE.get("date") != today:
            log.info("📅 New day! Resetting daily state...")
            STATE = {
                "date":         today,
                "trades":       0,
                "daily_pnl":    0.0,
                "stopped":      False,
                "wins":         0,
                "losses":       0,
                "consec_losses": 0,
                "cooldowns":    {},
                "open_times":   {},
            }

        try:
            run_bot(state=STATE)
        except Exception as e:
            log.error("❌ Bot error: " + str(e))
            log.error(traceback.format_exc())

        log.info("💤 Sleeping " + str(INTERVAL_MINUTES) + " mins...")
        time.sleep(INTERVAL_MINUTES * 60)

if __name__ == "__main__":
    main()
