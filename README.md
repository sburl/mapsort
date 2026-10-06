# mapsort

Turn a decade of Google Maps stars into city guides that skip the places
everyone already knows.

You export your saved places from Google Takeout, this fills in ratings
from the Google Places API, normalises every rating against its own
country, then **subtracts** a multiple of the review count. Most rankings
treat review volume as evidence of quality. This treats it as evidence of
fame, and filters it out.

```
hidden_gem_score = rating_z − 0.35 × log10(review_count)
```

A 4.8 with 200 reviews beats a 4.8 with 20,000. Output is one Markdown
guide per city, region or country that has enough places to be worth
publishing, each grouped into sections (eat, coffee, drink, see & do,
outdoors) with ratings, review counts and map links.

Pure standard library. No services, no database, no runtime dependencies
— JSON files on disk and one API key. 351 tests.

## Quickstart

```bash
# 1. Export "Saved Places" from https://takeout.google.com and unzip it
#    into ./takeout (or set TAKEOUT_DIR). One folder per Google account.
export GOOGLE_ACCOUNTS=your.account        # comma-separated for several
export GOOGLE_MAPS_API_KEY=...             # see "Cost" below

python3 ingest_takeout.py        # Takeout -> output/places_classified.json
python3 enrich_ratings.py        # fill in ratings, inside the free tier
python3 gem_score.py             # country baselines + gem scores
python3 generate_gem_guides.py   # render guides to output/guides/

python3 -m pytest tests -q
```

`python3 <script>.py --help` works on every script.

## Cost

Nothing, if you are patient. Google's Places API bills by field, not by
call:

| Fields requested | SKU | Free per month |
| --- | --- | --- |
| `id` only | Essentials | 10,000 |
| `rating`, `userRatingCount` | Enterprise | 1,000 |

So the real budget is **a thousand rated places a month**, which is the
constraint that shapes everything else. `enrich_ratings.py` therefore:

- caches every response permanently, so a place is never paid for twice;
- orders the queue by leverage, calling places that could change a
  guide's contents before ones that could only ever rank fortieth;
- never calls categories you would not publish (lodging, airports,
  transit, utilities);
- re-checks closures separately, via `businessStatus`.

A dataset of ~3,000 visited places takes three or four months of free
tier. Set `--limit` and come back next month.

## How it works

### 1. Ingest

Takeout gives you KML and CSV with no categories and no ratings, and many
pins resolve only to coordinates. Ingest normalises everything to one
record per place, keyed on Google's CID where there is one and on rounded
coordinates where there is not, then classifies each into one of 19
categories from its name and context.

Residential and private addresses are dropped before anything else —
saved pins include friends' houses. Low-confidence classifications go to
a review queue rather than being trusted silently; `reclassify_queue.py`
and `build_reclassify_review_ui.py` build a self-contained HTML page for
working through them.

### 2. Country-normalised scoring

A 4.4 in Tokyo and a 4.4 in Austin are not the same claim. Each rating
becomes a z-score against a baseline computed from the other places in
its own country. Across one real dataset of 28 countries, Italy ran most
generous at a 4.60 mean and Japan harshest at 4.22 — a gap of nearly four
tenths of a star that has nothing to do with the places.

Small samples shrink toward the global mean with a pseudo-count of 30, so
a country with twelve places cannot invent its own baseline.

Three guards stop the popularity penalty producing nonsense:

- **The no-Louvre rule.** Anything in the top 10% of review counts for
  its location is dropped outright, whatever it scores.
- **A rating floor of 4.0.** Being obscure is not a qualification.
- **A review floor of 30.** A 5.0 from eight reviews is somebody's
  cousins.

All of these are constants at the top of `gem_score.py`.

### 3. Geography

Places are assigned to guides by bounding box. Boxes nest — a Manhattan
restaurant is inside New York, Greater New York and the United States at
once — and assignment is **exclusive**: the smallest box containing a
place wins it, and bigger boxes become "Rest of" guides for the leftovers.

`LOCATIONS` in `generate_travel_guides.py` ships with 89 boxes. Replace
them with your own. Two warnings from experience:

- A rectangle is a bad model of a country. France's rectangle covers all
  of Belgium and most of Switzerland, so without guard boxes it claims
  places in both.
- Check that each box is actually inside its country's box. One country
  edge sat 0.01° short of the region inside it, which quietly promoted
  that region to a top-level entry in the index.

### 4. Guides

`generate_gem_guides.py` writes one Markdown file per eligible location,
with front matter for a Jekyll collection. A location needs at least two
sections of three places to get a page at all.

Two files absorb what no algorithm will get right: `excluded_places.py`
for places that score well and should not be shown, and
`category_overrides.py` for classifications to correct by place id. Both
ship empty, with commented examples of the kinds of thing that land
there. Expect to use both — the write-up below has the examples.

## Also in here

| Script | What it does |
| --- | --- |
| `taste_report.py` | What a decade of saves says about you |
| `trip_list.py` | Rank the want-to-go backlog for one city |
| `overrated_report.py` | The inverse gem score |
| `country_baseline_report.py` | Per-country rating baselines |
| `closed_places_report.py` | Saved places that have since closed |
| `export_gems_kml.py` | A "greatest hits" KML for Google My Maps |
| `export_site_data.py` | A slim, public-safe dataset for a website |
| `refresh_pipeline.py` | Diff a fresh Takeout export against the current one |

`docs/annual-refresh.md` covers re-running it a year later.
`docs/google-maps-import.md` covers getting results back into Google Maps.

## Privacy

Your saved places are personal data. They include where you live, where
your friends live, and where you have been. This repo ships **no data at
all**, and `.gitignore` excludes `takeout/` and the generated JSON. If you
publish guides, read `export_site_data.py` first — it is the only script
that deliberately produces something public-safe.

Set `GUIDE_CONTACT` to a `mailto:` link if you want guides to invite
corrections. Left unset, the invitation is omitted.
