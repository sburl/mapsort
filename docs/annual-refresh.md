**Created:** 2026-08-30-11-15
**Last Updated:** 2026-08-30-11-15

# Annual Refresh Runbook

## Overview

Two rhythms keep this project current:

- **Monthly** — spend the Places API free tier on ratings until the backlog
  is enriched, then regenerate guides.
- **Annually** — pull a fresh Google Takeout export, diff it against the
  current dataset, and publish a "year in places" summary.

Both are driven by `refresh_pipeline.py`. Run `python3 refresh_pipeline.py --plan`
for the checklist with live numbers; this document is the narrative version.

## Monthly Rhythm

Run on the 1st, when the free tier resets:

```bash
python3 enrich_ratings.py --limit 950    # metered — see Free Tier below
python3 gem_score.py                     # rescore with the new ratings
python3 generate_gem_guides.py           # write newly-eligible guide drafts
```

The last two steps are wrapped by:

```bash
python3 refresh_pipeline.py --run-downstream
```

Enrichment is resumable and cached in `output/ratings_cache.json`, so nothing
is ever fetched twice. Check progress without spending anything:

```bash
python3 enrich_ratings.py --dry-run
```

`generate_gem_guides.py` never overwrites an existing draft unless `--force`
is passed, so hand-edited posts survive regeneration.

## Monthly Batch Plan

Visited places are **done** (3,243 of 3,243). Everything below is either
upkeep or the optional want-to-go backlog, and the free tier covers all of
it without ever paying.

The backlog splits on perishability, which is what drives the order:

| | Places | Why |
|---|---:|---|
| Sights (museums, parks, landmarks) | 2,244 | Durable. A park is still a park in a year, so enrich wholesale |
| Food and drink | 2,950 | Perishable. Enrich a city when a trip is booked, not before |

### November — correctness first

```bash
python3 enrich_ratings.py --recheck-closures --limit 438
python3 trip_list.py --location "Copenhagen & Malmo" --fetch --budget 43
python3 gem_score.py && python3 generate_gem_guides.py
```

438 re-checks cover every place a guide actually prints. At the observed
2.6% closure rate that should surface roughly a dozen dead places currently
on the site. The remaining ~560 calls go to want-to-go sights, starting with
the cities never visited at all (Copenhagen 43, Osaka 37, CDMX 36, Sydney
33, Melbourne 23).

### December — sights, wholesale

1,000 calls against the want-to-go sights backlog.

### January — finish the sights

The last ~680. From here every museum, park and landmark on the want list is
ranked, and the only unrated places are restaurants and bars.

### February onwards — on demand

No standing batch. Enrich a city's food when a trip is booked:

```bash
python3 trip_list.py --location Lisbon --fetch --budget 100
```

A typical city is 30-70 calls, so a month's allowance covers several trips.
Food data is also freshest this way, which matters more for restaurants than
for cathedrals.

### Twice a year — re-check closures

Closure data goes stale. Re-run the November command each spring and autumn;
it is cheap and it is the only error a reader actually pays for.

```bash
python3 enrich_ratings.py --recheck-closures --dry-run   # count first, free
```

Scoped to places shown in guides by default. `--all-places` widens it to
every rated place, which costs more and changes nothing a reader sees.

## Free Tier

Google prices the Places API (New) per SKU, each with its own monthly
allowance. The two phases of enrichment land in different SKUs:

| Phase | SKU | Free per month | Notes |
|-------|-----|----------------|-------|
| Text search (resolve `place_id`) | Essentials | 10,000 | Never the bottleneck |
| Place details (`rating`, `userRatingCount`) | Enterprise | 1,000 | The real constraint |

Requesting rating fields re-prices the whole call at Enterprise
(~$35/1,000 beyond the free tier), which is why `--limit 950` is the default:
it leaves headroom inside the 1,000 and stops before anything bills.

Guardrails worth keeping in the Cloud console:

- A daily quota cap on the Places API (~1,100 requests) makes overage
  impossible rather than merely avoided.
- A $1 budget alert catches anything unexpected at pennies.

Running the script twice in one calendar month spends that month's
allowance twice. `--dry-run` is always free.

## Annual Refresh

### 1. Export (manual)

Google Takeout > Maps (your places) > Saved Places. Unzip into the directory
named by `DATA_DIR` in `settings.py`.

### 2. Rebuild the dataset

Some upstream entry points are **not committed to this repo** — they exist
only on the local machine, though `settings.py` still carries their config:

| Script | Stage | Status |
|--------|-------|--------|
| `scrape.py` | Scrape shared/starred Maps lists | Not in repo |
| `sort.py` | LLM classification into categories | Not in repo |
| `enrich.py` | Address/name enrichment | Not in repo |

The stages that *are* in the repo:

```bash
python3 reverse_geocode.py      # resolve coordinate-only pins (Nominatim)
python3 ingestion_filters.py    # triage + dedupe -> places_filtered.json
```

Pipeline position, for orientation:

```
Takeout -> places_raw.json -> ingestion_filters.py -> places_filtered.json -> classifier -> places_classified.json
```

Write the newly classified output to a **new path**. Do not overwrite
`output/places_classified.json` until the diff has been reviewed.

### 3. Diff

```bash
python3 refresh_pipeline.py --diff output/places_classified_2027.json
```

Writes `output/year_diff.md` with:

- **Places you finally went** — rows that moved `want_to_go -> visited`.
  This is the heart of the "year in places" post.
- **Added** / **Removed** — new saves, and pins that vanished from Takeout.
- **Tier changes** and **category changes** — everything else that moved.

Identity is the Takeout `id` where it is meaningful. Roughly 470 rows carry
the degenerate id `name:` (nameless, address-only pins at 0,0); those fall
back to a composite of name, address, and coordinates.

### 4. Promote and re-enrich

Once the diff looks right, promote the new dataset over
`output/places_classified.json`, then:

```bash
python3 refresh_pipeline.py --plan    # recomputed budget, including new places
python3 enrich_ratings.py --limit 950
python3 refresh_pipeline.py --run-downstream
```

Newly added places need enrichment too, so the month count in `--plan` will
grow after a refresh.

## Privacy Rules

These are not preferences. Nothing published may violate them:

- **Visited only.** `want_to_go` places are a backlog, not a recommendation,
  and publishing them exposes intent rather than taste.
- **Never publish `source_lists`.** The field contains friends' names
  (e.g. list titles ending in a parenthesized name). It is stripped by
  `export_site_data.py` and must stay stripped everywhere else.
  `output/friends_scoreboard.md` is private and gitignored.
- **Excluded categories.** Hotels & stays (6), airports (14), train & transit
  (15), and practical (16) never ship publicly — lodging and logistics reveal
  patterns of movement rather than taste.
- **No full-map publication.** A pin-level map of every visited place is a
  pattern-of-life record. Per-guide maps of a curated handful are fine; the
  complete atlas is not.

`export_site_data.py` enforces the first three in code, with tests asserting
that no provenance field survives export.
