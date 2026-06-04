"""One-off backfill: fetch pollen data for April 1 – June 1, 2026 and upsert into pollen.csv."""
import logging
from collections import defaultdict

import requests

import config
import pollen_store

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
log = logging.getLogger("backfill-pollen")

START_DATE = "2026-04-01"
END_DATE = "2026-06-01"


def fetch_range(start, end):
    params = {
        "latitude": config.LATITUDE,
        "longitude": config.LONGITUDE,
        "hourly": ",".join(config.POLLEN_SPECIES),
        "timezone": config.TIMEZONE,
        "start_date": start,
        "end_date": end,
    }
    resp = requests.get(config.AIR_QUALITY_URL, params=params, timeout=60)
    resp.raise_for_status()
    return resp.json()


def aggregate(payload):
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    by_date = defaultdict(lambda: defaultdict(list))
    for species in config.POLLEN_SPECIES:
        series = hourly.get(species) or []
        for stamp, value in zip(times, series):
            if value is None:
                continue
            by_date[stamp[:10]][species].append(value)
    return by_date


def run():
    log.info("Fetching pollen %s → %s", START_DATE, END_DATE)
    payload = fetch_range(START_DATE, END_DATE)
    by_date = aggregate(payload)

    rows = []
    for day, species_map in sorted(by_date.items()):
        for species, values in species_map.items():
            if not values:
                continue
            rows.append({
                "date": day,
                "species": species,
                "mean_value": round(sum(values) / len(values), 2),
                "max_value": round(max(values), 2),
                "latitude": config.LATITUDE,
                "longitude": config.LONGITUDE,
            })

    total = pollen_store.upsert_rows(rows)
    log.info("Upserted %d row(s) across %d day(s); %s now holds %d rows.", len(rows), len(by_date), config.POLLEN_CSV, total)


if __name__ == "__main__":
    run()
