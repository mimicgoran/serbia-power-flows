# Serbia Cross-Border Electricity Flows

An interactive 3D map of hourly cross-border electricity flows for the Serbian bidding zone (BZN|RS),
built on official data from the ENTSO-E Transparency Platform and refreshed automatically every day.

**Live map:** https://mimicgoran.github.io/serbia-power-flows/

The map compares, for every border and every hour:

- **Measured** physical flows,
- **Scheduled** (net) commercial exchanges, and
- the **difference** between the two, i.e. unscheduled flows.

Commercial schedules determine how much power is exchanged; the physical grid determines which way it flows.
Unscheduled flows arise because power distributes across all parallel paths of the interconnected network,
regardless of contractual routes.

---

## Contents

- [Features](#features)
- [Data sources](#data-sources)
- [Methodology](#methodology)
- [Architecture](#architecture)
- [Repository structure](#repository-structure)
- [Deployment](#deployment)
- [Local development](#local-development)
- [Data format](#data-format)
- [Limitations](#limitations)
- [Notes](#notes)

---

## Features

- 3D arcs per border; arc width is proportional to power (MW), colour indicates direction.
- Three views: **Measured**, **Net schedule** and **Difference** (unscheduled flows).
- Hour slider with playback, day selector, and shareable links that preserve the selected day, hour and view
  (e.g. `#2026-11-03/18/razlika`).
- Hourly indicators for Serbia: total load, net import or export, share of load covered by net import,
  and total deviation from schedule.
- Daily net import/export profile (measured vs. net schedule).
- Per-border table and CSV export for the selected day.
- The default view opens on the most recent day with complete data.
- Fully automated: data acquisition, archiving and publishing run on GitHub Actions at no cost.

## Data sources

All electricity data are retrieved from the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu)
through its RESTful API.

| View / indicator | ENTSO-E data item | Article (Reg. 543/2013) | Notes |
|---|---|---|---|
| Measured | Cross-Border Physical Flows | 12.1.G | Average netted values per market time unit |
| Net schedule | Scheduled Commercial Exchanges, Total | 12.1.F | Both directions retrieved, netted per border |
| Load | Actual Total Load | 6.1.A | Bidding zone BZN\|RS |

Borders covered: Hungary (HU), Romania (RO), Bulgaria (BG), North Macedonia (MK), Kosovo\* (XK),
Montenegro (ME), Bosnia and Herzegovina (BA), Croatia (HR) and Albania (AL).

Base map: [Natural Earth](https://www.naturalearthdata.com/) Admin 0 countries, 1:50m (public domain),
clipped to the region and simplified.

## Methodology

**Sign convention.** Positive values denote net import into Serbia; negative values denote net export from Serbia.

**Measured flows.** ENTSO-E publishes physical flows as average netted values. For each hour, one direction
carries the net value and the opposite direction is zero. The map therefore shows a single arc per border.

**Net schedule.** Scheduled exchanges are published separately for each direction and are typically non-zero
in both directions at the same time. The net schedule per border is computed as:

```
net_schedule = scheduled(neighbour → RS) − scheduled(RS → neighbour)
```

Both directional values are retained in the data and shown in the map tooltip.

**Unscheduled flow (difference).** For each border and hour:

```
difference = measured_net − net_schedule
```

Both terms are net values, so the comparison is like for like. Gross contractual volumes in opposite
directions offset each other and are never physically transmitted.

**Deviation from schedule.** The hourly indicator is the sum of absolute differences across all borders:

```
deviation = Σ |measured_net − net_schedule|
```

**Temporal resolution.** Values are aggregated to hourly averages in local time (Europe/Belgrade).
Days with a daylight-saving transition have 23 or 25 hours and are handled accordingly.
Where a series is published at 15-minute resolution, it is averaged to the hour.

**Data completeness.** A day is considered complete when load is available for every hour and every border
has either a value for every hour or no published values at all (e.g. a border that is not reported).
Incomplete days remain selectable and are labelled in the day selector.

**Revisions.** Transmission system operators may revise published values. The pipeline re-downloads the
three most recent days on every run, so corrections are picked up automatically.

## Architecture

```
ENTSO-E RESTful API
        │  (daily, GitHub Actions)
        ▼
scripts/entsoe_srbija.py ── parallel requests, retries, hourly aggregation, netting
        │
        ▼
docs/data/dani/YYYY-MM-DD.json  +  docs/data/index.json   (committed to the repository)
        │
        ▼
docs/index.html ── static page (deck.gl), served by GitHub Pages
```

- **Acquisition:** Python with [`entsoe-py`](https://github.com/EnergieID/entsoe-py) and pandas.
  Requests are sent in parallel (8 workers) with a 60 s timeout and up to three attempts on transient
  server errors. The API token is masked in all log output.
- **Storage:** one JSON file per day, versioned in Git. No database or server is required.
- **Presentation:** a single static HTML page using [deck.gl](https://deck.gl) (ArcLayer, GeoJsonLayer,
  TextLayer). No build step.
- **Automation:** a scheduled GitHub Actions workflow fetches data, commits changes and deploys GitHub Pages.

## Repository structure

```
.github/workflows/osvezi.yml     Scheduled workflow: fetch, commit, deploy
scripts/entsoe_srbija.py         Data acquisition and processing
docs/index.html                  Web application
docs/data/zemlje.geojson         Base map geometry
docs/data/dani/YYYY-MM-DD.json   Daily data files (generated)
docs/data/index.json             List of available and incomplete days (generated)
requirements.txt                 Python dependencies
```

## Deployment

1. **Fork or clone** this repository. The repository must be public to use GitHub Pages on a free plan.
2. **Obtain an ENTSO-E API token.** Register on the Transparency Platform, request RESTful API access
   from `transparency@entsoe.eu`, then generate a security token in your account settings.
3. **Add the token as a secret:** *Settings → Secrets and variables → Actions → New repository secret*,
   name `ENTSOE_TOKEN`.
4. **Enable GitHub Pages:** *Settings → Pages → Build and deployment → Source: GitHub Actions*.
5. **Initial backfill:** *Actions → "Osvezi podatke i objavi mapu" → Run workflow*, setting `od` (start date,
   `YYYY-MM-DD`) to the first day you want in the archive. Leave `do` (end date) empty to stop at yesterday.

After the initial run, the workflow runs daily at 04:41 UTC and refreshes the last three completed days.

## Local development

```bash
pip install -r requirements.txt

# Linux / macOS
export ENTSOE_TOKEN=your_token
# Windows PowerShell
$env:ENTSOE_TOKEN="your_token"

# Fetch data (defaults to the last three completed days)
python scripts/entsoe_srbija.py
python scripts/entsoe_srbija.py --od 2026-10-25 --do 2026-11-03
python scripts/entsoe_srbija.py --poslednjih-dana 7

# Serve the page
cd docs && python -m http.server 8000
```

Open `http://localhost:8000`. The token must never be committed to the repository.

## Data format

Each daily file `docs/data/dani/YYYY-MM-DD.json` has the following structure (values in MW, `null` = not published):

```json
{
  "datum": "2026-11-03",
  "sati": ["00:00", "01:00", "..."],
  "vreme": ["2026-11-03T00:00:00+01:00", "..."],
  "granice": {
    "BA": {
      "stvarno":    [427.03, "..."],
      "plan":       [350.0,  "..."],
      "plan_uvoz":  [350.0,  "..."],
      "plan_izvoz": [0.0,    "..."]
    }
  },
  "srbija": { "potrosnja": [3988.0, "..."] },
  "osvezeno": "2026-11-05T04:45Z"
}
```

| Field | Meaning |
|---|---|
| `sati` / `vreme` | Hour labels and ISO 8601 timestamps in local time |
| `stvarno` | Measured net flow (positive = import into Serbia) |
| `plan` | Net schedule |
| `plan_uvoz` / `plan_izvoz` | Scheduled exchange towards / from Serbia |
| `potrosnja` | Actual total load of BZN\|RS |
| `osvezeno` | Time of retrieval (UTC) |

`index.json` lists all available days (`dani`), days with incomplete data (`nepotpuni`) and the time of the last update.

## Limitations

- Values are aggregated **per border**, not per transmission line. Arcs connect symbolic points and do not
  represent the location of individual interconnectors.
- Values are **hourly averages**; intra-hour dynamics are not visible.
- Net position of BZN|RS is not available through the API (data item 12.1.E returns no data for Serbia),
  so schedules are validated per border rather than against an official net position.
- Flows on the Serbia–Albania border are not published (`n/e`); the border is shown without an arc
  until data become available.
- Data are provided as published by the transmission system operators and may be revised after publication.

## Notes

- Bidding zones are shown as defined in ENTSO-E data. Kosovo and Metohija is displayed as part of Serbia;
  Kosovo\* denotes a separate bidding zone in ENTSO-E data. \*This designation is in line with UNSC Resolution 1244.
- This project is an independent, non-commercial demonstration and is not affiliated with ENTSO-E or any
  transmission system operator.

**Author:** Goran Mimić
