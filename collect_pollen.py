"""Daily pollen collector for Edinburgh, designed to run in GitHub Actions.

Fetches hourly pollen from the Open-Meteo Air Quality API, aggregates each day
to a mean and a peak, and upserts the rows into data/pollen.csv. The workflow
commits that CSV back to the repo. Requesting a couple of past days plus today
means missed or still-incomplete days self-heal on the next run.

Dependencies: just `requests` (no key, no secrets needed).
"""
import logging
from collections import defaultdict

import requests

import config
import pollen_store

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO
)
log = logging.getLogger("collect-pollen")


def fetch():
    params = {
        "latitude": config.LATITUDE,
        "longitude": config.LONGITUDE,
        "hourly": ",".join(config.POLLEN_SPECIES),
        "timezone": config.TIMEZONE,
        "past_days": 2,
        "forecast_days": 1,
    }
    resp = requests.get(config.AIR_QUALITY_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def aggregate(payload):
    """Group hourly values into {date: {species: [values...]}}."""
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
    payload = fetch()
    by_date = aggregate(payload)

    rows = []
    for day, species_map in sorted(by_date.items()):
        for species, values in species_map.items():
            if not values:
                continue
            rows.append(
                {
                    "date": day,
                    "species": species,
                    "mean_value": round(sum(values) / len(values), 2),
                    "max_value": round(max(values), 2),
                    "latitude": config.LATITUDE,
                    "longitude": config.LONGITUDE,
                }
            )

    total = pollen_store.upsert_rows(rows)
    log.info(
        "Upserted %d row(s) across %d day(s); %s now holds %d rows.",
        len(rows), len(by_date), config.POLLEN_CSV, total,
    )


if __name__ == "__main__":
    run()
