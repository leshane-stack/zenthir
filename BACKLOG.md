# Zenthir Backlog

## Provider Page Improvements
- [ ] Add provider credentials (years licensed, board certification, NPI display)
- [ ] Expand "Compare Nearby Providers" table (add avg charge, price level columns)
- [ ] Neighborhood pricing comparison on provider pages

## New Page Types
- [ ] Provider Hub Pages ("Family Medicine Providers in Miami" with rankings, median, counts)
- [ ] Neighborhood Pages ("Family Medicine in Kendall" vs "Coral Gables" vs "Brickell")
- [ ] Procedure Market Reports ("Most Affordable MRI Providers in Miami")
- [ ] "Is $X a Fair Price for Y?" pages (generated from price checker data)
- [ ] Comparison Pages ("Hospital MRI vs Imaging Center MRI", "Botox: Med Spa vs Plastic Surgeon")

## Internal Linking
- [ ] Every provider page links: Provider → Procedure → City → Specialty
- [ ] Every procedure page links to city-level cost pages
- [ ] Dense link graph across all page types

## Data Coverage
- [ ] MRF import via Hetzner server (DoltHub baseline + fresh MRF parsing)
- [ ] Provider team/doctor linking (match individual NPIs to practice addresses)
- [ ] Geocode 25,429 locations without coordinates
- [ ] Historical price tracking (change detection on import)

## Content
- [ ] "How to Negotiate a Hospital Bill" guide
- [ ] "How to Compare Medical Quotes" guide
- [ ] Top 20 procedure descriptions (data-driven, not generic)

## Tools
- [ ] Cost Estimator (before-treatment tool)
- [ ] Good Faith Estimate checker
- [ ] Bill audit tool ($19-29)

## Future Data Layers
- [ ] Insurance-specific negotiated rates on provider pages (after MRF import)
- [ ] Monthly MRF refresh pipeline
- [ ] Hospital MRF files for CPT-level hospital pricing
- [ ] Price trend/history tracking

## SEO / Sitemaps
- [ ] Full prod sitemap regeneration (nice-to-have, not a blocker). The 2026-07-24
      cleanup stripped ~29k credentialed individuals via the conservative
      `healthcare/sitemap_utils.is_individual_slug()` classifier and split the
      oversized market sitemap. Plain-name individuals (no `-md`/`-dc` suffix,
      e.g. `anthony-deriggi`) remain in the provider sitemaps and rely on the
      provider page's noindex. Durable fix: backfill `Provider.is_individual`
      in prod, then run `generate_sitemaps.py` (excludes individuals, chunks at
      50k) + `generate_cash_sitemaps.py` (Postgres-only) against the prod DB to
      regenerate all child sitemaps from current data. Would also pick up
      providers added since the last local snapshot.
