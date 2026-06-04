# Allergy & Pollen Tracker (Edinburgh)

Split across two always-on places, meeting in the repo — no database server needed.

```
GitHub Actions (daily)            Mac Mini (always on)
  collect_pollen.py                 bot.py  ──► allergy.db   (your symptoms)
        │ writes                       │ reads
        ▼                              ▼
  data/pollen.csv  ◄──── committed ───► raw.githubusercontent.com/.../pollen.csv
        ▲                              │
        └──────── analyze.py ──────────┘  (joins both on date)
```

- **Actions** runs the collector once a day, writes `data/pollen.csv`, and commits it back. Open-Meteo is keyless, so **the workflow needs no secrets**.
- **The Mac** runs the bot, stores symptoms in local SQLite, and reads pollen from the committed CSV via its raw GitHub URL — always fresh, no `git pull` needed.
- Only Actions writes the CSV and only the Mac writes the DB, so there are no write conflicts.

Requires Python 3.10+.

## Files

| File | Runs where | Purpose |
|------|-----------|---------|
| `collect_pollen.py` | Actions | fetch + aggregate pollen, upsert `data/pollen.csv` |
| `pollen_store.py` | both | CSV read/upsert (reads local path or raw URL) |
| `bot.py` | Mac | Telegram bot; symptoms → SQLite |
| `db.py` | Mac | SQLite store for symptoms |
| `analyze.py` | anywhere | join pollen + symptoms, correlations, optional plot |
| `.github/workflows/collect-pollen.yml` | Actions | daily schedule + commit step |

## Setup — GitHub side (collector)

1. Push this repo to GitHub.
2. The workflow is already at `.github/workflows/collect-pollen.yml`. It runs daily and on the **Run workflow** button (Actions tab). Trigger it once manually to confirm `data/pollen.csv` gets populated and committed.
3. Notes on Actions scheduling: cron is **UTC** and timing is best-effort (runs can be delayed 10–30 min — fine for a daily pull). Scheduled workflows **auto-disable after 60 days of no repo activity**; an occasional commit or a keepalive action prevents that.

That's it — no secrets to configure.

## Setup — Mac side (bot)

```bash
git clone <your-repo> && cd allergy-tracker
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:
- `TELEGRAM_BOT_TOKEN` — from **@BotFather** (`/newbot`).
- `POLLEN_CSV_URL` — `https://raw.githubusercontent.com/<you>/<repo>/main/data/pollen.csv`
- `ALLOWED_CHAT_ID` — optional; send `/start`, the bot replies with your id, paste it in, restart.

Run it:

```bash
python bot.py
```

### Keep it running on the Mac (launchd)

Save as `~/Library/LaunchAgents/com.you.allergybot.plist`, then
`launchctl load ~/Library/LaunchAgents/com.you.allergybot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.you.allergybot</string>
  <key>ProgramArguments</key>
  <array>
    <string>/full/path/allergy-tracker/.venv/bin/python</string>
    <string>/full/path/allergy-tracker/bot.py</string>
  </array>
  <key>WorkingDirectory</key><string>/full/path/allergy-tracker</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>/full/path/allergy-tracker/bot.err.log</string>
  <key>StandardOutPath</key><string>/full/path/allergy-tracker/bot.out.log</string>
</dict>
</plist>
```

`launchd` restarts it on crash and on login, which suits an always-on Mac Mini.

### Using the bot

- Send any text → logged with a timestamp. Add `3/5` or `severity 3` to record severity.
- `/today` — today's pollen + symptoms logged today.
- `/week` — last 7 days: symptom counts next to grass/birch peaks.

## Compare symptoms vs pollen

```bash
python analyze.py          # daily table + same-day and 1-day-lag correlations
python analyze.py --plot   # also writes symptoms_vs_pollen.png
```

Or load it yourself — pollen is a plain CSV you can read from anywhere:

```python
import pandas as pd, sqlite3
pollen = pd.read_csv("https://raw.githubusercontent.com/<you>/<repo>/main/data/pollen.csv")
symptoms = pd.read_sql("SELECT * FROM symptoms", sqlite3.connect("allergy.db"))
```

## Notes on the data

- Pollen is from the **CAMS European** model via Open-Meteo (~11 km, Europe only — Edinburgh covered), in grains/m³. It's a short forecast, not deep history, which is why the daily job builds your own record over time. Run the workflow soon so history starts accumulating.
- Species: alder, birch, grass, mugwort, olive, ragweed. For Scotland, **grass and birch (and alder in early spring)** matter; olive/ragweed are usually ~0.

_Not medical advice — a personal tracking tool._
