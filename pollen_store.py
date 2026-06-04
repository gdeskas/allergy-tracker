"""Pollen persistence as a CSV committed to the repo.

Only the collector (in GitHub Actions) writes it. Readers (the bot, analysis)
can load it from a local file or directly from its raw GitHub URL, so the
always-on Mac never has to pull the repo just to see fresh pollen data.
"""
import csv
import io
import os

import config

FIELDS = ["date", "species", "mean_value", "max_value", "latitude", "longitude"]


def _read_text(source):
    """CSV text from a local path or http(s) URL. Returns '' if not found yet."""
    if source.startswith(("http://", "https://")):
        import requests  # imported lazily so the writer path needs no network deps
        resp = requests.get(source, timeout=30)
        if resp.status_code == 404:
            return ""
        resp.raise_for_status()
        return resp.text
    if os.path.exists(source):
        with open(source, newline="") as fh:
            return fh.read()
    return ""


def _to_float(value):
    return float(value) if value not in (None, "") else None


def read_rows(source=None):
    source = source or config.POLLEN_SOURCE
    text = _read_text(source)
    if not text.strip():
        return []
    reader = csv.DictReader(io.StringIO(text))
    return [
        {
            "date": r["date"],
            "species": r["species"],
            "mean_value": _to_float(r.get("mean_value")),
            "max_value": _to_float(r.get("max_value")),
            "latitude": _to_float(r.get("latitude")),
            "longitude": _to_float(r.get("longitude")),
        }
        for r in reader
    ]


def upsert_rows(new_rows, path=None):
    """Merge rows by (date, species) and rewrite the CSV sorted. Idempotent."""
    path = path or config.POLLEN_CSV
    merged = {(r["date"], r["species"]): r for r in read_rows(path)}
    for r in new_rows:
        merged[(r["date"], r["species"])] = r
    ordered = sorted(merged.values(), key=lambda r: (r["date"], r["species"]))

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    return len(ordered)


def pollen_for_date(date, source=None):
    rows = [r for r in read_rows(source) if r["date"] == date]
    rows.sort(key=lambda r: (r["max_value"] or 0), reverse=True)
    return rows
