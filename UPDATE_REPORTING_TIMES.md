# Reporting Schedule Update

Updated to match the provided screenshot:

| Item | Schedule | Status |
|---|---:|---|
| Daily report | Mon–Fri 07:50 SGT | Present |
| Weekly report | Monday 08:00 SGT | Present |
| Weekly export | Monday 08:05 SGT | Present |
| Weekly export file | trade_history.csv | Present |

## Code changes

- `settings.json` / `settings.json.example`
  - `daily_report_hour_sgt`: `7`
  - `daily_report_minute_sgt`: `50`
  - `weekly_report_hour_sgt`: `8`
  - `weekly_report_minute_sgt`: `0`
  - Added `weekly_export_hour_sgt`: `8`
  - Added `weekly_export_minute_sgt`: `5`

- `scheduler.py`
  - Daily report scheduled Mon–Fri at `07:50 SGT`.
  - Weekly report scheduled Monday at `08:00 SGT`.
  - Weekly export scheduled Monday at `08:05 SGT`.
  - Weekly export log now shows `trade_history.csv`.

- `reporting.py`
  - Weekly export now reads `/data/trade_history.json`.
  - Converts the JSON records to `/data/trade_history.csv`.
  - Sends `trade_history.csv` to Telegram instead of `trade_history.json`.
  - Nested fields such as `levels` are preserved as compact JSON text inside CSV cells.

- `.gitignore`
  - Added `trade_history.csv` as a runtime file.
