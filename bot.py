"""Telegram bot for logging allergy symptoms. Runs on the always-on Mac.

Symptoms are stored in local SQLite. Pollen is read from the CSV that GitHub
Actions commits (local file, or its raw GitHub URL via POLLEN_CSV_URL).

Commands:
  /start /help  - intro + your chat id
  /today        - today's pollen and the symptoms you logged today
  /week         - last 7 days: symptom counts vs grass/birch peaks

Run with:  python bot.py
"""
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
import db
import pollen_store

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO
)
log = logging.getLogger("allergy-bot")

TZ = ZoneInfo(config.TIMEZONE)

_SEVERITY_PATTERNS = [
    re.compile(r"(\d)\s*/\s*5"),
    re.compile(r"severity\s*[:=]?\s*(\d)", re.IGNORECASE),
    re.compile(r"\b([1-5])\b"),
]


def parse_severity(text):
    for pattern in _SEVERITY_PATTERNS:
        match = pattern.search(text)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 5:
                return value
    return None


def _authorized(update: Update) -> bool:
    if config.ALLOWED_CHAT_ID is None:
        return True
    return str(update.effective_chat.id) == str(config.ALLOWED_CHAT_ID)


def _format_pollen(rows):
    active = [r for r in rows if (r["max_value"] or 0) > 0]
    if not active:
        return "No pollen recorded yet for today (the daily collector may not have run)."
    lines = []
    for r in active:
        name = r["species"].replace("_pollen", "").capitalize()
        lines.append(
            f"  {name}: peak {r['max_value']:.0f}, mean {r['mean_value']:.0f} grains/m3"
        )
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        "Hi! I'm your allergy tracker.\n\n"
        "Whenever symptoms hit, just message me what's going on and I'll log it "
        "with a timestamp. Add a 1-5 rating (e.g. '3/5') and I'll store the "
        "severity too.\n\n"
        "Commands:\n"
        "/today - today's pollen + your logged symptoms\n"
        "/week - last 7 days summary\n"
        "/help - show this again\n\n"
        f"Your chat id is {chat_id}. Put it in ALLOWED_CHAT_ID to keep the bot private."
    )


async def log_symptom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    text = update.message.text.strip()
    severity = parse_severity(text)
    now = datetime.now(TZ)
    db.insert_symptom(
        now.isoformat(), severity, text, str(update.effective_chat.id), text
    )
    suffix = f" (severity {severity}/5)" if severity is not None else ""
    await update.message.reply_text(f"Logged at {now:%H:%M}{suffix}. Hope you feel better.")


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    now = datetime.now(TZ)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    pollen = pollen_store.pollen_for_date(now.date().isoformat())
    syms = db.symptoms_between(
        day_start.isoformat(), (day_start + timedelta(days=1)).isoformat()
    )

    msg = [f"*{now:%A %d %b}*", "", "Pollen:", _format_pollen(pollen), ""]
    if syms:
        msg.append(f"Symptoms logged today ({len(syms)}):")
        for s in syms:
            t = datetime.fromisoformat(s["ts"]).strftime("%H:%M")
            sev = f" [{s['severity']}/5]" if s["severity"] else ""
            msg.append(f"  {t}{sev} - {s['notes']}")
    else:
        msg.append("No symptoms logged today.")
    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


async def week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    now = datetime.now(TZ)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    lines = ["*Last 7 days*", ""]
    for i in range(6, -1, -1):
        day = today0 - timedelta(days=i)
        pollen = {p["species"]: p["max_value"] for p in pollen_store.pollen_for_date(day.date().isoformat())}
        syms = db.symptoms_between(
            day.isoformat(), (day + timedelta(days=1)).isoformat()
        )
        grass = pollen.get("grass_pollen") or 0
        birch = pollen.get("birch_pollen") or 0
        lines.append(
            f"{day:%a %d}: {len(syms)} symptom(s) | grass {grass:.0f}, birch {birch:.0f}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def main():
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in your .env (get it from @BotFather).")
    db.init_db()

    app = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("week", week))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_symptom))

    log.info("Bot started. Long-polling for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
