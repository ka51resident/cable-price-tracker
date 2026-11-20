# Cable Metal Price Tracker

Tracks LME copper and aluminium cash settlement prices and USD/INR every weekday,
keeps the history with monthly averages, and provides a quote checker that shows how
much of a cable price change the metal move justifies.

## What is here

| Path | Purpose |
|---|---|
| `index.html`, `assets/calc.js` | The web page: latest prices, trends, monthly averages, quote checker |
| `data/lme_copper.csv`, `data/lme_aluminium.csv` | Daily cash settlement and 3-month prices, USD per tonne |
| `data/usdinr.csv` | Daily USD/INR reference rate |
| `data/comex_copper.csv`, `data/comex_aluminium.csv` | COMEX front-month futures close, for comparison (copper in USD/lb, aluminium in USD/t) |
| `data/ieema.csv` | IEEMA monthly prices in Rs/kg, entered by hand from the circular |
| `data/prices.json`, `data/monthly_averages.csv` | Built from the CSVs on every update |
| `scripts/update_prices.py` | Fetches new prices and rebuilds the data files |
| `.github/workflows/update-prices.yml` | Runs the updater Monday to Friday at 21:00 IST, and again at 08:00 IST |

## How the numbers work

- **Rs/kg** = LME cash settlement (USD/tonne) x USD/INR / 1000. Duty, premium and
  rod conversion are excluded, so use it to measure change, not absolute cost.
- **Metal in a cable** = conductor area (sq mm) x 8.89 kg/km for copper or 2.703 for
  aluminium. 3.5 core uses the standard reduced neutral.
- **Fair new rate** = earlier rate + metal weight per metre x change in Rs/kg.
- **Gap** = new rate minus fair new rate. Under 4% is treated as noise.

## Running it by hand

```
python scripts/update_prices.py                  # fetch the current year
python scripts/update_prices.py --years 2024 2025  # backfill older years
python scripts/update_prices.py --offline        # rebuild JSON from the CSVs only
python scripts/test_updater.py && node scripts/test_calc.js
```

Backfill can also be run from the Actions tab: "Update metal prices" > Run workflow > years.

## If the update fails

The workflow run fails and GitHub emails the repository owner. The page also shows a
warning when the latest price is more than five days old. The usual cause is a layout
change on the source page; the parser in `scripts/update_prices.py` then needs adjusting.

## Adding IEEMA prices

Edit `data/ieema.csv` on GitHub and add one line per month, for example
`2026-10,1495.50,318.20,IEEMA(PVC)/CABLE/...`. The columns are month, copper Rs/kg,
aluminium Rs/kg and an optional circular reference. The page picks it up on the next update.

## Sources

- Metals: official LME cash settlement prices as published on Westmetall's market data pages.
- FX: Frankfurter API (central bank reference rates).
- COMEX: front-month futures daily close from Yahoo Finance chart data. Optional: if it
  fails, the run shows a warning and the LME update still completes.
- IEEMA: manual entry. MCX is not included because its site blocks automated access.

For internal reference only. Vendor quotes are never stored in this repository;
the quote checker runs entirely in the browser.
