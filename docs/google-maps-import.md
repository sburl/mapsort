**Created:** 2026-03-07-03-50
**Last Updated:** 2026-03-07-03-50

# Google Maps Import Guide

## Overview

The pipeline produces KML files in `output/` with category-specific icons.
Google My Maps supports KML import with up to **10 layers per map** and
**2,000 features per layer**.

19 categories x 2 layers each (blue=want-to-go, green=visited) = 38 layers,
so we need **4 maps** with 5 categories each (last map has 4).

## Map Layout

| Map | Categories | ~Placemarks |
|-----|-----------|-------------|
| **Food** | Restaurants, Cafes & Bakeries, Quick Bites, Bars & Nightlife, Sweets & Snacks | 4,301 |
| **Culture** | Landmarks & History, Museums & Culture, Entertainment, Sacred Sites, Shopping | 2,578 |
| **Outdoors** | Nature & Outdoors, Parks & Gardens, Regions & Destinations, Ski Resorts, Scuba & Diving | 2,018 |
| **Logistics** | Hotels & Stays, Practical, Airports, Train & Transit | 1,544 |

Each category gets 2 layers (blue + green) so you can toggle visited vs
want-to-go independently.

## Pre-import: Merge Part Files

Some categories were split into multiple files (e.g. `blue_restaurants_part1.kml`
through `part4`). Run the merge script to combine them:

```bash
python3 merge_kml_parts.py
```

This produces files organized into map subfolders:

```
output/import/
  food/          10 files (5 categories x blue/green)
  culture/       10 files
  outdoors/      10 files
  logistics/      8 files (4 categories x blue/green)
```

## Import Steps

1. Go to [Google My Maps](https://www.google.com/mymaps)
2. Click **Create a new map**
3. Name it to match the folder (e.g. "MapSort - Food")
4. Click **Import** on the first layer
5. Select a KML file from that folder (e.g. `food/blue_restaurants.kml`)
6. Import all remaining files from the same folder (up to 10 layers)
7. Rename each layer to match the category
8. Repeat for the remaining 3 maps/folders

## After Import

- Icons should appear automatically from the `<Style>` elements in each KML
- Toggle layers on/off to show visited vs want-to-go
- Access from Google Maps app: Your places > Maps

## Limits Reference

- 10 layers per map
- 2,000 features per layer
- 10,000 total features per map
- KML files must be under 5 MB each

## Greatest Hits Layer (personal, single file)

The four-map layout above is the full archive. For everyday use there is a
much smaller alternative: one KML holding only the top gems, sized to carry
on a phone and consult while standing in an unfamiliar city.

```bash
python export_gems_kml.py                        # output/gems_greatest_hits.kml
python export_gems_kml.py --per-location 10 --max-total 200
```

Selection takes the highest-scoring non-famous places per location before
capping globally, so one densely-rated city cannot crowd out everywhere
else. Places outside every known bounding box are pooled into their own
bucket and get the same allowance, so a high-scoring rural find is not lost.

Import it as a single layer:

1. Go to [Google My Maps](https://www.google.com/mymaps)
2. **Create a new map**, name it something like "Greatest Hits"
3. Click **Import** and select `output/gems_greatest_hits.kml`
4. Access it from the Google Maps app: Your places > Maps

Each placemark's description carries the rating, review count, and gem
score, plus a `maps.google.com` link back to the original listing where a
CID is known. Category icons come from the same mapping as the per-category
files, so pins look consistent with the full archive.
