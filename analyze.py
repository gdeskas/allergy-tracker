"""Join pollen (CSV from Actions) and symptoms (local SQLite) for comparison.

    python analyze.py            # daily table + same-day and 1-day-lag correlations
    python analyze.py --plot     # also save symptoms_vs_pollen.png

Set POLLEN_CSV_URL to analyse from the committed CSV on GitHub without a local
checkout; otherwise it reads the local data/pollen.csv.
"""
import argparse
import sqlite3

import pandas as pd

import config
import pollen_store


def load():
    pollen = pd.DataFrame(pollen_store.read_rows(config.POLLEN_SOURCE))
    conn = sqlite3.connect(config.DB_PATH)
    try:
        symptoms = pd.read_sql_query("SELECT * FROM symptoms", conn)
    except pd.errors.DatabaseError:
        symptoms = pd.DataFrame(columns=["id", "ts", "severity"])
    finally:
        conn.close()
    return pollen, symptoms


def build_daily(pollen, symptoms):
    if pollen.empty:
        return pd.DataFrame()

    pol = pollen.pivot_table(index="date", columns="species", values="max_value")
    pol.columns = [c.replace("_pollen", "") for c in pol.columns]
    pol.index = pd.to_datetime(pol.index)

    if not symptoms.empty:
        ts = pd.to_datetime(symptoms["ts"], utc=True, errors="coerce")
        day = ts.dt.tz_convert(config.TIMEZONE).dt.normalize().dt.tz_localize(None)
        symptoms = symptoms.assign(day=day)
        daily = symptoms.groupby("day").agg(
            symptom_count=("id", "count"),
            avg_severity=("severity", "mean"),
        )
    else:
        daily = pd.DataFrame(columns=["symptom_count", "avg_severity"])

    df = pol.join(daily, how="left")
    df["symptom_count"] = df["symptom_count"].fillna(0)
    df.index.name = "date"
    return df.sort_index()


def report(df):
    if df.empty:
        print("No pollen data yet - let the Actions collector run for a few days first.")
        return
    pollen_cols = [c for c in df.columns if c not in ("symptom_count", "avg_severity")]
    active = [c for c in pollen_cols if df[c].fillna(0).sum() > 0]

    print("\n=== Daily table ===")
    with pd.option_context("display.width", 120):
        print(df[active + ["symptom_count", "avg_severity"]].round(1))

    if df["symptom_count"].sum() == 0:
        print("\nNo symptoms logged yet - message the bot, then re-run.")
        return

    print("\n=== Correlation with symptom_count (same day) ===")
    print(df[active].corrwith(df["symptom_count"]).round(3).sort_values(ascending=False))

    print("\n=== Correlation with symptom_count (pollen leads by 1 day) ===")
    print(df[active].shift(1).corrwith(df["symptom_count"]).round(3).sort_values(ascending=False))


def plot(df):
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed; skipping plot.")
        return
    if df.empty:
        return
    lead = "grass" if "grass" in df.columns else next(
        (c for c in df.columns if c not in ("symptom_count", "avg_severity")), None
    )
    fig, ax1 = plt.subplots(figsize=(11, 5))
    ax1.bar(df.index, df["symptom_count"], alpha=0.4, label="symptom count")
    ax1.set_ylabel("symptom count")
    if lead:
        ax2 = ax1.twinx()
        ax2.plot(df.index, df[lead], color="green", label=f"{lead} pollen (peak)")
        ax2.set_ylabel(f"{lead} pollen grains/m3")
    fig.autofmt_xdate()
    plt.title("Symptoms vs pollen")
    fig.tight_layout()
    fig.savefig("symptoms_vs_pollen.png", dpi=120)
    print("Saved symptoms_vs_pollen.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plot", action="store_true", help="save a chart")
    args = parser.parse_args()

    pollen, symptoms = load()
    df = build_daily(pollen, symptoms)
    report(df)
    if args.plot:
        plot(df)
