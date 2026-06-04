"""Telegram bot for logging allergy symptoms. Runs on the always-on Mac.

Symptoms are stored in local SQLite. Pollen is read from the CSV that GitHub
Actions commits (local file, or its raw GitHub URL via POLLEN_CSV_URL).

Commands:
  /start /help  - intro + your chat id
  /today        - today's pollen and the symptoms you logged today
  /week         - last 7 days: symptom counts vs grass/birch peaks
  /analyze      - 30-day correlation between symptoms and pollen levels

Run with:  python bot.py
"""
import logging
import re
from datetime import date as date_type, datetime, timedelta
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
        "/analyze - 30-day symptom/pollen correlation\n"
        "/log YYYY-MM-DD [HH:MM] <text> - log a historical symptom\n"
        "/delete YYYY-MM-DD - remove all logged symptoms for that date\n"
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


async def log_historical(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Usage: /log YYYY-MM-DD [HH:MM] <symptom text>"""
    if not _authorized(update):
        return
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Usage: /log YYYY-MM-DD [HH:MM] <symptom text>\n"
            "Example: /log 2026-06-01 10:30 sneezing and itchy eyes 3/5"
        )
        return

    try:
        target_date = datetime.strptime(args[0], "%Y-%m-%d").date()
    except ValueError:
        await update.message.reply_text("Date must be YYYY-MM-DD. Example: /log 2026-06-01 sneezing")
        return

    rest = args[1:]
    hour, minute = 12, 0
    if rest and re.match(r"^\d{1,2}:\d{2}$", rest[0]):
        try:
            hour, minute = (int(x) for x in rest[0].split(":"))
            rest = rest[1:]
        except ValueError:
            pass

    if not rest:
        await update.message.reply_text("Please include a symptom description after the date.")
        return

    notes = " ".join(rest)
    severity = parse_severity(notes)
    ts = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=TZ)
    db.insert_symptom(ts.isoformat(), severity, notes, str(update.effective_chat.id), notes)
    sev_str = f" (severity {severity}/5)" if severity is not None else ""
    await update.message.reply_text(f"Logged for {ts:%Y-%m-%d %H:%M}{sev_str}: {notes}")


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _authorized(update):
        return
    arg = " ".join(context.args).strip().lower() if context.args else ""
    now = datetime.now(TZ)
    if not arg or arg == "today":
        target = now.date()
    else:
        try:
            target = datetime.strptime(arg, "%Y-%m-%d").date()
        except ValueError:
            await update.message.reply_text(
                "Usage: /delete YYYY-MM-DD  or  /delete today"
            )
            return

    day_start = datetime(target.year, target.month, target.day, tzinfo=TZ)
    syms = db.symptoms_between(day_start.isoformat(), (day_start + timedelta(days=1)).isoformat())
    if not syms:
        await update.message.reply_text(f"No symptoms logged on {target}.")
        return

    count = db.delete_symptoms_for_date(
        day_start.isoformat(), (day_start + timedelta(days=1)).isoformat()
    )
    lines = [f"Deleted {count} entry(s) from {target}:"]
    for s in syms:
        t = datetime.fromisoformat(s["ts"]).strftime("%H:%M")
        sev = f" [{s['severity']}/5]" if s["severity"] else ""
        lines.append(f"  {t}{sev} - {s['notes']}")
    await update.message.reply_text("\n".join(lines))


async def analyze(update: Update, _context: ContextTypes.DEFAULT_TYPE):
    """Full-history overview of symptom/pollen correlation."""
    if not _authorized(update):
        return

    now = datetime.now(TZ)

    # Fetch all pollen data first to determine the earliest date available
    all_pollen_rows = pollen_store.read_rows()
    pollen_by_date: dict[str, dict[str, float]] = {}
    for row in all_pollen_rows:
        d = row["date"]
        pollen_by_date.setdefault(d, {})[row["species"]] = row["max_value"] or 0.0

    # Fetch all symptoms (no lower bound)
    all_syms = db.symptoms_between("0000-01-01", now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat())
    syms_by_date: dict[str, list] = {}
    for s in all_syms:
        d = datetime.fromisoformat(s["ts"]).date().isoformat()
        syms_by_date.setdefault(d, []).append(s)

    # Determine window from earliest data point across both sources
    all_dates = sorted({*pollen_by_date.keys(), *syms_by_date.keys()})
    if not all_dates:
        await update.message.reply_text("No data recorded yet.")
        return
    start_date = all_dates[0]
    end_date = now.date().isoformat()

    # Build per-day records for the full window
    cursor = date_type.fromisoformat(start_date)
    end = date_type.fromisoformat(end_date)
    days = []
    while cursor <= end:
        day = cursor.isoformat()
        syms = syms_by_date.get(day, [])
        days.append(
            {
                "date": day,
                "has_symptoms": bool(syms),
                "symptom_count": len(syms),
                "severities": [s["severity"] for s in syms if s["severity"] is not None],
                "pollen": pollen_by_date.get(day, {}),
                "has_pollen": day in pollen_by_date,
            }
        )
        cursor += timedelta(days=1)

    window_days = len(days)

    # Correlation analysis requires pollen data — use only the overlap
    overlap_days = [d for d in days if d["has_pollen"]]

    symptom_days = [d for d in days if d["has_symptoms"]]
    clear_days = [d for d in days if not d["has_symptoms"]]

    def avg(vals):
        return sum(vals) / len(vals) if vals else 0.0

    def avg_pollen(day_list, species):
        return avg([d["pollen"].get(species, 0.0) for d in day_list])

    species_present = sorted(
        {sp for d in overlap_days for sp in d["pollen"] if d["pollen"][sp] > 0}
    )

    total_entries = sum(d["symptom_count"] for d in days)
    pct_symptom = round(100 * len(symptom_days) / len(days))
    start_label = datetime.strptime(start_date, "%Y-%m-%d").strftime("%d %b %Y")
    end_label = now.strftime("%d %b %Y")

    lines = [
        f"*Allergy Analysis* ({start_label} – {end_label})",
        "",
        f"Days with symptoms logged: {len(symptom_days)}/{window_days} ({pct_symptom}%)",
        f"Total symptom entries: {total_entries}",
        f"Days with pollen data: {len(overlap_days)}",
    ]

    if not overlap_days:
        lines.append("\nNot enough pollen data yet for correlation analysis.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # Correlation: restrict to days that have pollen data
    overlap_symptom = [d for d in overlap_days if d["has_symptoms"]]
    overlap_clear = [d for d in overlap_days if not d["has_symptoms"]]

    triggers: list[tuple] = []

    if overlap_symptom and overlap_clear:
        # Score each species: ratio + absolute lift on symptom days vs clear days
        scores = []
        for sp in species_present:
            on = avg_pollen(overlap_symptom, sp)
            off = avg_pollen(overlap_clear, sp)
            diff = on - off
            ratio = on / off if off > 0 else (999.0 if on > 0 else 1.0)
            scores.append((sp, on, off, diff, ratio))
        scores.sort(key=lambda x: x[4], reverse=True)

        triggers = [
            (sp, on, off, diff, ratio)
            for sp, on, off, diff, ratio in scores
            if ratio >= 1.3 and diff >= 5
        ]

        if triggers:
            lines += ["", "*Likely triggers*"]
            for sp, on, off, diff, ratio in triggers:
                name = sp.replace("_pollen", "").capitalize()
                label = "Strong" if ratio >= 1.8 and diff >= 10 else "Possible"
                lines.append(f"  {label}: {name} ({ratio:.1f}× higher on symptom days)")

        lines += ["", "*Species ranked by symptom correlation*"]
        for sp, on, off, diff, ratio in scores:
            name = sp.replace("_pollen", "").capitalize()
            arrow = "↑" if diff > 5 else ("↓" if diff < -5 else "≈")
            lines.append(f"  {name}: {on:.0f} vs {off:.0f} g/m³  {arrow}")

    # For top trigger species: show symptom hit rate above vs below median pollen
    for sp, on, off, diff, ratio in triggers[:2]:
        vals = sorted(d["pollen"].get(sp, 0.0) for d in overlap_days)
        n = len(vals)
        med = (vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2) if vals else 0.0
        above = [d for d in overlap_days if d["pollen"].get(sp, 0.0) > med]
        below = [d for d in overlap_days if d["pollen"].get(sp, 0.0) <= med]
        if above and below:
            name = sp.replace("_pollen", "").capitalize()
            above_pct = round(100 * sum(1 for d in above if d["has_symptoms"]) / len(above))
            below_pct = round(100 * sum(1 for d in below if d["has_symptoms"]) / len(below))
            lines += [
                "",
                f"*{name}: above vs below median ({med:.0f} g/m³)*",
                f"  High days: symptoms on {above_pct}% of days",
                f"  Low days:  symptoms on {below_pct}% of days",
            ]

    # Severity vs pollen — focus on trigger species if available
    all_severities = [sv for d in overlap_days for sv in d["severities"]]
    if len(all_severities) >= 3:
        low_days = [d for d in overlap_days if d["severities"] and max(d["severities"]) <= 2]
        high_days = [d for d in overlap_days if d["severities"] and max(d["severities"]) >= 4]
        if low_days and high_days:
            check_species = [sp for sp, *_ in triggers] if triggers else species_present
            lines += ["", "*Severity vs pollen (mild ≤2 vs severe ≥4)*"]
            for sp in check_species:
                name = sp.replace("_pollen", "").capitalize()
                lo = avg_pollen(low_days, sp)
                hi = avg_pollen(high_days, sp)
                lines.append(f"  {name}: mild {lo:.0f} vs severe {hi:.0f} g/m³")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


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
    app.add_handler(CommandHandler("analyze", analyze))
    app.add_handler(CommandHandler("log", log_historical))
    app.add_handler(CommandHandler("delete", delete))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_symptom))

    log.info("Bot started. Long-polling for messages...")
    app.run_polling()


if __name__ == "__main__":
    main()
