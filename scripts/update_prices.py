#!/usr/bin/env python3
"""Daily updater for the cable metal price tracker.

Fetches LME copper and aluminium official cash settlement prices (USD/tonne)
and the USD/INR reference rate, merges them into the CSV history in data/,
and rebuilds data/prices.json and data/monthly_averages.csv for the web page.

Standard library only, so the GitHub Action needs no installs.

Usage:
    python scripts/update_prices.py                 # current year
    python scripts/update_prices.py --years 2024 2025
    python scripts/update_prices.py --offline       # rebuild JSON from CSVs only
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

USER_AGENT = "cable-price-tracker/1.0 (+https://github.com/ka51resident/cable-price-tracker)"

# Price source: Westmetall's public market data tables (official LME prices).
METAL_URL = "https://www.westmetall.com/en/markdaten.php?action=table&field={field}"
METALS = {
    # key: (source field, csv file, plausible USD/tonne range)
    "copper": ("LME_Cu_cash", DATA / "lme_copper.csv", (2000.0, 60000.0)),
    "aluminium": ("LME_Al_cash", DATA / "lme_aluminium.csv", (500.0, 15000.0)),
}

# Optional comparison market: COMEX front-month futures (Yahoo Finance chart
# data). Copper is quoted in USD per pound, aluminium in USD per tonne.
# A failure here is reported as a warning and never blocks the LME update.
COMEX_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={span}&interval=1d"
COMEX = {
    # key: (symbol, csv file, plausible range in the contract's own unit)
    "copper": ("HG%3DF", DATA / "comex_copper.csv", (0.5, 30.0)),
    "aluminium": ("ALI%3DF", DATA / "comex_aluminium.csv", (500.0, 15000.0)),
}
LB_PER_TONNE = 2204.62262

# India reference entered by hand each month from the IEEMA circular.
IEEMA_FILE = DATA / "ieema.csv"

# FX source: Frankfurter (open API over central bank reference rates, no key).
FX_URL = "https://api.frankfurter.dev/v1/{start}..?base=USD&symbols=INR"
FX_FILE = DATA / "usdinr.csv"
FX_RANGE = (40.0, 200.0)

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    # German spellings, in case the English page is ever unavailable.
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "mai": 5, "juni": 6,
    "juli": 7, "oktober": 10, "dezember": 12,
}
DATE_RE = re.compile(r"^(\d{1,2})\.\s*([A-Za-zäÄ]+)\s+(\d{4})$")
NUM_RE = re.compile(r"^-?\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^-?\d+(?:\.\d+)?$")


class TableRows(HTMLParser):
    """Collects the text of every table row as a list of cell strings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def parse_number(text: str) -> float | None:
    text = text.strip()
    if not NUM_RE.match(text):
        return None
    return float(text.replace(",", ""))


def parse_metal_table(html: str, valid_range: tuple[float, float]) -> dict[str, tuple[float, float | None]]:
    """Returns {iso_date: (cash_settlement, three_month)} from a price table page."""
    parser = TableRows()
    parser.feed(html)
    lo, hi = valid_range
    out: dict[str, tuple[float, float | None]] = {}
    for row in parser.rows:
        if len(row) < 2:
            continue
        m = DATE_RE.match(row[0])
        if not m:
            continue
        month = MONTHS.get(m.group(2).lower())
        if not month:
            continue
        try:
            date = dt.date(int(m.group(3)), month, int(m.group(1)))
        except ValueError:
            continue
        cash = parse_number(row[1])
        if cash is None or not (lo <= cash <= hi):
            continue  # holiday rows carry "-" or 0
        three = parse_number(row[2]) if len(row) > 2 else None
        if three is not None and not (lo <= three <= hi):
            three = None
        out[date.isoformat()] = (cash, three)
    return out


def http_get(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def read_csv(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        return {row[0]: row[1:] for row in reader if row}


def write_csv(path: Path, header: list[str], rows: dict[str, list[str]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(header)
        for date in sorted(rows):
            writer.writerow([date, *rows[date]])


def update_metal(name: str, years: list[int]) -> int:
    field, path, valid = METALS[name]
    existing = read_csv(path)
    before = dict(existing)
    this_year = dt.date.today().year
    fetched = 0
    for year in years:
        url = METAL_URL.format(field=field)
        if year != this_year:
            url += f"&year={year}"
        parsed = parse_metal_table(http_get(url), valid)
        if not parsed:
            raise RuntimeError(
                f"No {name} prices could be read from {url}. "
                "The source page layout has probably changed."
            )
        fetched += len(parsed)
        for date, (cash, three) in parsed.items():
            existing[date] = [f"{cash:.2f}", "" if three is None else f"{three:.2f}"]
    write_csv(path, ["date", "cash", "three_month"], existing)
    changed = sum(1 for d in existing if before.get(d) != existing[d])
    print(f"{name}: read {fetched} rows, {changed} new or changed, latest {max(existing)}")
    return changed


def update_fx(start: str) -> int:
    existing = read_csv(FX_FILE)
    before = dict(existing)
    payload = json.loads(http_get(FX_URL.format(start=start)))
    rates = payload.get("rates", {})
    lo, hi = FX_RANGE
    for date, values in rates.items():
        rate = values.get("INR") if isinstance(values, dict) else None
        if isinstance(rate, (int, float)) and lo <= rate <= hi:
            existing[date] = [f"{rate:.4f}"]
    if not existing:
        raise RuntimeError("No USD/INR rates could be read from the FX source.")
    write_csv(FX_FILE, ["date", "rate"], existing)
    changed = sum(1 for d in existing if before.get(d) != existing[d])
    print(f"usdinr: {changed} new or changed, latest {max(existing)}")
    return changed


def parse_comex_chart(text: str, valid_range: tuple[float, float], today: dt.date) -> dict[str, float]:
    """Returns {iso_date: settlement/close} from a Yahoo chart response.

    Bars dated today or later are dropped because the session is still open.
    """
    result = json.loads(text)["chart"]["result"][0]
    offset = int(result.get("meta", {}).get("gmtoffset", 0))
    stamps = result.get("timestamp") or []
    closes = result["indicators"]["quote"][0].get("close") or []
    lo, hi = valid_range
    out: dict[str, float] = {}
    for stamp, close in zip(stamps, closes):
        if not isinstance(close, (int, float)) or not (lo <= close <= hi):
            continue
        date = (dt.datetime(1970, 1, 1) + dt.timedelta(seconds=int(stamp) + offset)).date()
        if date >= today:
            continue
        out[date.isoformat()] = float(close)
    return out


def update_comex(name: str, backfill: bool) -> int:
    symbol, path, valid = COMEX[name]
    existing = read_csv(path)
    before = dict(existing)
    span = "5y" if (backfill or not existing) else "1mo"
    today = dt.datetime.now(dt.timezone.utc).date()
    parsed = parse_comex_chart(http_get(COMEX_URL.format(symbol=symbol, span=span)), valid, today)
    if not parsed:
        raise RuntimeError(f"No COMEX {name} prices could be read.")
    for date, close in parsed.items():
        existing[date] = [f"{close:.4f}"]
    write_csv(path, ["date", "close"], existing)
    changed = sum(1 for d in existing if before.get(d) != existing[d])
    print(f"comex {name}: {changed} new or changed, latest {max(existing)}")
    return changed


def build_outputs() -> None:
    """Merges the three CSVs into prices.json and monthly_averages.csv."""
    cu = read_csv(METALS["copper"][1])
    al = read_csv(METALS["aluminium"][1])
    fx = read_csv(FX_FILE)
    fx_dates = sorted(fx)
    comex_cu = read_csv(COMEX["copper"][1])
    comex_al = read_csv(COMEX["aluminium"][1])
    ieema = read_csv(IEEMA_FILE)

    def num(row: list[str] | None, i: int) -> float | None:
        if not row or len(row) <= i or row[i] == "":
            return None
        return float(row[i])

    daily = []
    fx_i = -1
    for date in sorted(set(cu) | set(al)):
        # Most recent FX rate on or before this date (LME and FX holidays differ).
        while fx_i + 1 < len(fx_dates) and fx_dates[fx_i + 1] <= date:
            fx_i += 1
        rate = float(fx[fx_dates[fx_i]][0]) if fx_i >= 0 else None
        daily.append({
            "d": date,
            "cu": num(cu.get(date), 0),
            "cu3": num(cu.get(date), 1),
            "al": num(al.get(date), 0),
            "al3": num(al.get(date), 1),
            "fx": rate,
            # COMEX in USD per tonne (copper converted from USD per pound).
            "ccu": None if num(comex_cu.get(date), 0) is None else round(num(comex_cu.get(date), 0) * LB_PER_TONNE, 2),
            "cal": num(comex_al.get(date), 0),
        })

    months: dict[str, dict[str, list[float]]] = {}
    for row in daily:
        bucket = months.setdefault(row["d"][:7], {"cu": [], "al": [], "fx": [], "cu_inr": [], "al_inr": [], "ccu": [], "cal": []})
        for key in ("cu", "al", "fx", "ccu", "cal"):
            if row[key] is not None:
                bucket[key].append(row[key])
        if row["fx"] is not None:
            if row["cu"] is not None:
                bucket["cu_inr"].append(row["cu"] * row["fx"] / 1000)
            if row["al"] is not None:
                bucket["al_inr"].append(row["al"] * row["fx"] / 1000)

    def mean(values: list[float], digits: int) -> float | None:
        return round(sum(values) / len(values), digits) if values else None

    monthly = [
        {
            "m": month,
            "days": len(b["cu"]) or len(b["al"]),
            "cu": mean(b["cu"], 2),
            "al": mean(b["al"], 2),
            "fx": mean(b["fx"], 4),
            "cu_inr": mean(b["cu_inr"], 2),
            "al_inr": mean(b["al_inr"], 2),
            "ccu": mean(b["ccu"], 2),
            "cal": mean(b["cal"], 2),
            "ie_cu": num(ieema.get(month), 0),
            "ie_al": num(ieema.get(month), 1),
        }
        for month, b in sorted(months.items())
    ]

    payload = {
        "latest": daily[-1]["d"] if daily else None,
        "sources": {
            "metals": "Official LME cash settlement prices, USD per tonne, as published by Westmetall",
            "fx": "USD/INR reference rate via Frankfurter (central bank reference rates)",
            "comex": "COMEX front-month futures daily close via Yahoo Finance chart data",
            "ieema": "IEEMA monthly circular prices, entered by hand in data/ieema.csv",
        },
        "daily": daily,
        "monthly": monthly,
    }
    (DATA / "prices.json").write_text(json.dumps(payload, separators=(",", ":")) + "\n")

    with (DATA / "monthly_averages.csv").open("w", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(["month", "trading_days", "lme_copper_usd_per_t", "lme_aluminium_usd_per_t",
                         "usd_inr", "lme_copper_inr_per_kg", "lme_aluminium_inr_per_kg",
                         "comex_copper_usd_per_t", "comex_aluminium_usd_per_t",
                         "ieema_copper_inr_per_kg", "ieema_aluminium_inr_per_kg"])
        for m in monthly:
            writer.writerow([m["m"], m["days"], m["cu"], m["al"], m["fx"], m["cu_inr"], m["al_inr"],
                             m["ccu"], m["cal"], m["ie_cu"], m["ie_al"]])
    print(f"built prices.json: {len(daily)} days, {len(monthly)} months, latest {payload['latest']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", nargs="*", type=int, help="years to fetch (default: current year)")
    ap.add_argument("--offline", action="store_true", help="skip fetching, rebuild outputs only")
    args = ap.parse_args()

    failures: list[str] = []
    if not args.offline:
        years = sorted(set(args.years or [dt.date.today().year]))
        for name in METALS:
            try:
                update_metal(name, years)
            except (urllib.error.URLError, TimeoutError, RuntimeError, OSError) as exc:
                failures.append(f"{name}: {exc}")
        # Re-read a week of FX each run so late corrections are picked up, and
        # reach back further when older years are being backfilled.
        fx_existing = read_csv(FX_FILE)
        first_needed = dt.date(min(years), 1, 1) - dt.timedelta(days=7)
        if fx_existing:
            first_have = dt.date.fromisoformat(min(fx_existing))
            last_have = dt.date.fromisoformat(max(fx_existing))
            fx_start = first_needed if first_needed < first_have else last_have - dt.timedelta(days=7)
        else:
            metal_dates = [d for name in METALS for d in read_csv(METALS[name][1])]
            earliest = dt.date.fromisoformat(min(metal_dates)) if metal_dates else first_needed
            fx_start = min(first_needed, earliest - dt.timedelta(days=7))
        try:
            update_fx(fx_start.isoformat())
        except (urllib.error.URLError, TimeoutError, RuntimeError, OSError, ValueError) as exc:
            failures.append(f"usdinr: {exc}")

        for name in COMEX:
            try:
                update_comex(name, backfill=bool(args.years))
            except Exception as exc:  # optional source: warn, never fail the run
                print(f"::warning title=COMEX {name} not updated::{exc}")

    build_outputs()

    if failures:
        # Outputs are still rebuilt from what we have; the non-zero exit makes
        # GitHub email the repo owner so a broken source does not go unnoticed.
        print("\nUPDATE PROBLEMS:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
