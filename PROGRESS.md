# PROGRESS — Cash-Pay Shopping Pages + Computed Market FAQs

Branch: `cash-pay-pages` (NOT merged, NOT deployed — for review)
Date: 2026-06-05

## Scope this session
Two phases, both validated on **one page** before any scaling:
1. **Phase 1** — New cash-pay shopping pages: `/cash/<procedure>/<city>/` and `/cash/<procedure>/`.
2. **Phase 2** — Add the same computed-FAQ-with-schema block to the existing live
   market pages (`/market/<procedure>/<city>/`).

No new data sources, no scraping, no Stripe/claim work. No mass-generation. No
sitemap changes. No migrations (the `billing_component` / `price_category` fields
already existed on `PricingRecord`).

---

## Important data note (must read before scaling)
Development/validation ran against the **local SQLite** copy (`db.sqlite3`, full
dataset: 2.97M providers, 6.03M pricing records). No `.env`/production read-only
connection string exists in this repo, so I could not point at Railway. The local
copy has the real cash-price **values** but is **out of sync on the categorical tags**:

| Field | Production (per task) | Local SQLite (actual) |
|---|---|---|
| `price_category` for cash-pay rows | `cash_price` | `submitted_charge` (legacy) |
| `billing_component` | tagged | `None` (all 6M rows) |
| `source_name` (cash-pay rows) | — | `Market Estimate` |
| `price_type` (cash-pay rows) | — | `estimated` |

**How the code handles this:** the cash-pay record filter
(`views_cash._cash_records`) prefers `price_category='cash_price'` and only falls
back to "populated `cash_price` for this cash-pay-flagged procedure" when no tagged
rows exist. So it is **production-correct** (uses the tag when present) and
**locally validatable** (falls back to legacy). The view reports which path ran via
`basis` = `cash_price` (prod) or `cash_price_legacy` (local). Validation below shows
`cash_price_legacy`, as expected locally.

**Data-quality smells found (flagged, not fixed — out of scope):**
- Botox (Full Face) and CoolSculpting have **identical** record counts (11,937) and
  identical city distributions — looks like one synthetic "Market Estimate" provider
  set was mapped to multiple aesthetic procedures. Verify against production.
- A city named `"Hollywood FL"` in state `FL` (state appears duplicated in the city
  string).
- Cash-pay prices are **advertised market estimates**, not scraped quotes
  (`price_type='estimated'`). Pages are labeled honestly to reflect this.

---

## Cash-pay URL structure
| URL | View | Page |
|---|---|---|
| `/cash/<procedure>/<city>/` | `views_cash.cash_procedure_city` | "[Procedure] Prices in [City]" — ranked providers, range, FAQ |
| `/cash/<procedure>/` | `views_cash.cash_procedure_national` | National overview + by-city breakdown |

- A cash page only renders for procedures flagged `is_cash_pay_common=True` (else 404).
- Routes are ordered city-before-national in `urls.py`.

### Procedures/cities covered
- **36 procedures** are flagged `is_cash_pay_common=True`, including all Tier-1 targets:
  Botox (Full Face), Dermal Fillers (Lips), CoolSculpting, Dental Crown (Porcelain),
  Dental Implant (Single), Teeth Whitening, Rhinoplasty, Liposuction,
  Breast Augmentation, Blepharoplasty, Facelift.
- The view serves **any** city with enough data; nothing was mass-generated. Only one
  page (Botox / Miami) was rendered for review.

### Thin-data threshold
- **`THIN_DATA_THRESHOLD = 10`** clean providers (after dedup).
- Below it: no confident stats/FAQ; page renders a labeled "limited data" view with
  `<meta name="robots" content="noindex,follow">` and (if any) the few listed prices.

### Cleaning rules for the provider list (the two visible bugs)
`market_utils.dedupe_ranked_providers`:
1. One row per provider (lowest `cash_price`).
2. **Collapse duplicate phone numbers** (normalized digits) — a shared main line
   (hospital switchboard) otherwise appears as many "providers"; keep the cheapest.
3. Drop low outliers below `0.10 × median` (catches a stray cross-tagged cheap line).

---

## Validation: Botox (Full Face) in Miami, FL  (the one reviewed page)

Render: `GET /cash/botox-full-face/miami-fl/` → **200**, valid `FAQPage` JSON-LD (4 Q&A).

| Metric | Value |
|---|---|
| Raw cash records | 478 |
| Distinct providers (pre-phone-dedupe) | 478 |
| **Clean providers (after phone-dedupe)** | **403** (75 duplicate-phone entries collapsed) |
| Low outliers dropped | 0 |
| Filter basis | `cash_price_legacy` (local; prod would be `cash_price`) |
| Median | **$442** |
| Typical range (p25–p75) | $361 – $514 |
| Full range | $251 – $600 (1.9x) |
| Cheapest | Laria MedSpa — $251 |

Top of cleaned ranked list (each a distinct phone):
```
 #1 $251 Laria MedSpa                         (305) 299-7290
 #2 $255 EDGE by ELIXR Wellness Brickell      (786) 323-7099
 #3 $267 Morpheus8 Miami                      (786) 297-7548
 #4 $267 Alive Miami - IV Therapy             (305) 897-7121
 #5 $274 Lavish Laser Med Spa Coconut Grove   (786) 550-2480
```

Sample computed FAQ (per-page-unique, schema-marked):
> **How much does Botox (Full Face) cost in Miami, FL?**
> Across 403 advertised cash-pay listings in Miami, FL, the median price for
> Botox (Full Face) is $442. Most providers fall between $361 and $514.
>
> **What is the cheapest Botox (Full Face) provider in Miami, FL?**
> The lowest advertised price in Miami, FL is $251, listed by Laria MedSpa. A lower
> listed price does not always mean a lower total cost — confirm exactly what is
> included with the provider before booking.
>
> **Is Botox (Full Face) covered by insurance?**
> Botox (Full Face) is typically an elective, cash-pay procedure that most insurance
> plans do not cover. The prices shown are advertised market estimates...

Other checks passed:
- `/cash/botox-full-face/` (national) → 200, valid FAQPage JSON-LD, by-city table.
- `/cash/lasik-both-eyes/miami-fl/` → 200 (61 raw records).
- Thin city `bay-harbor-islands-fl` (1 provider) → 200, **noindex**, no FAQ schema.
- Non-cash procedure → **404**.
- Rich pages are **indexable** (no robots meta); only thin pages are noindex.

### Framing / honesty (no "overcharged" framing on cash pages)
- Shopping CTAs: "Compare providers", "see the range", "Shopping for [procedure]?".
- Honest labeling line on every cash page: cash prices are advertised market
  estimates, "a lower listed price does not always mean a lower total cost — confirm
  the all-in price with the provider."
- "What affects the cost" is a short **data-anchored** blurb (uses the page's own
  range/multiplier) + one link to the canonical explainer (`/guides/why-prices-vary/`),
  not a repeated generic essay.
- (The site-wide header/footer still link to `/overcharged/` — that's global chrome,
  not cash-page framing.)

---

## Phase 2: computed FAQ on existing market pages
Added `build_market_faq` + JSON-LD to `views_market.procedure_market` and a
`{% block schema %}` + `_faq.html` include to `procedure_market.html`.
Answers are bill-audit framing, computed per page.

Validated: `GET /market/mri-scan-of-brain-without-contrast/miami-fl/` → 200,
valid FAQPage JSON-LD (3 Q&A) computed from page data:
- median $359, typical $280–$948, lowest $146 (DEBORAH PEVSNER, M.D.), range 6.8x.

---

## Files changed
- **New:** `healthcare/market_utils.py` (stats, dedupe, FAQ builders, JSON-LD),
  `healthcare/views_cash.py`, templates `cash_city.html`, `cash_national.html`,
  `_faq.html`.
- **Modified:** `healthcare/urls.py` (+2 routes), `healthcare/views_market.py` (FAQ),
  `templates/.../procedure_market.html` (FAQ + schema block),
  `templates/.../base.html` (added `{% block robots %}`).
- `python manage.py check` → no issues. No migrations.

---

## Open decisions / next steps
1. **When to mass-generate** Tier-1 × cities. Validate the filter against **production**
   first (confirm `basis` resolves to `cash_price`, not the legacy fallback) before
   scaling. Decide indexable-page count per procedure (thin-data guard already gates
   at 10 providers/city).
2. **Re-sync local DB or get a prod read-only URL** so future validation matches prod
   tags (`price_category='cash_price'`, `billing_component`).
3. **Botox == CoolSculpting data duplication** — confirm whether production has
   distinct provider sets per aesthetic procedure or the same smell exists; affects
   page credibility.
4. **By-city median on national page** currently shows **average** (true per-city
   median across many cities is expensive in SQLite). Revisit if median is preferred.
5. **Scraping spend** to deepen city coverage for cash-pay procedures (separate session).
6. Sitemap entries for `/cash/` pages — intentionally NOT touched this session.

---

# PRODUCTION VERIFICATION (read-only) — 2026-06-05

Read-only audit of the **production** Postgres (Railway `Zenthir` → service
`Postgres`, env `production`) before any mass-generation. Connection via
`DATABASE_PUBLIC_URL` with `PGOPTIONS='-c default_transaction_read_only=on'`
(verified: a test `CREATE TABLE` was rejected — *"cannot execute CREATE TABLE in
a read-only transaction"*). No writes, no migrations, no generation. Only
COUNT/AVG/`percentile_cont` aggregates and ≤5-row samples.

Production `price_category` distribution: `negotiated_rate` 11,374,211 ·
`submitted_charge` 5,977,585 · `gross_charge` 138,753 · **`cash_price` 110,738**.
The real cash_price path **exists in prod** (local had 0 — local was legacy only).

## BLOCKER affecting ALL cash-pay procedures
`is_cash_pay_common = FALSE` for **every** target procedure in production. The
cash view (`views_cash._get_cash_procedure`) 404s unless this flag is true, so
**no `/cash/` page renders in production today** regardless of data quality. This
flag is set locally but not in prod. Must be set (data update — separate session)
or the gating relaxed, before any launch.

## 1. cash_price number table (clean = provider+phone deduped, production)
| Procedure | Miami (n / median / range) | Los Angeles | New York | Median plausible? |
|---|---|---|---|---|
| Botox (Full Face) | 403 / $442 / $251–600 | 116 / $416 | 112 / $422 | ✅ |
| Dermal Fillers (Lips) | 403 / $680 / $407–916 | 116 / $699 | 112 / $664 | ✅ |
| CoolSculpting | 403 / $1,128 / $615–1,496 | 116 / $1,030 | 112 / $1,066 | ✅ |
| Dental Crown | 90 / $1,324 | 93 / $1,321 | 95 / $1,343 | ✅ |
| Dental Implant | 90 / $3,226 | 93 / $2,959 | 95 / $3,243 | ✅ |
| Teeth Whitening | 89 / $407 | 93 / $413 | 94 / $450 | ✅ |
| Rhinoplasty | 359 / $8,857 | 64 / $8,826 | 62 / $9,544 | ✅ (but see §2) |
| Liposuction | 359 / $5,217 | 64 / $5,296 | 62 / $5,304 | ✅ (but see §2) |
| Breast Augmentation | 359 / $7,505 | 63 / $7,784 | 61 / $7,552 | ✅ (but see §2) |
| Blepharoplasty | 354 / $4,376 | 58 / $4,742 | 58 / $4,364 | ✅ (but see §2) |
| Facelift | 354 / $12,316 | 58 / $12,685 | 58 / $12,984 | ✅ (but see §2) |
| Gastric Sleeve | 53 / $14,881 | 53 / $14,978 | 60 / $15,935 | ✅ |
| IVF Cycle | 48 / $18,810 | 54 / $18,368 | 53 / $17,871 | ✅ |
| Egg Freezing | 44 / $8,229 | 50 / $8,860 | 50 / $7,916 | ✅ |
| IUI | 44 / $1,243 | 50 / $1,277 | 50 / $1,514 | ✅ |
| LASIK (Both Eyes) | 49 / $3,079 | 54 / $3,418 | 47 / $3,247 | ✅ |
| FUE Hair Transplant | 47 / $7,612 | 52 / $8,731 | 54 / $8,826 | ✅ |

**All 17 medians are plausible — no implausible values flagged.** The cash_price
path produces sane numbers. (Botox-Miami = 403 providers / $442 median here
matches the local legacy-path validation exactly, so the page logic is confirmed
against the real path.) Note Miami counts are ~5–7× LA/NY because the dataset is
FL-heavy.

## 2. Real-vs-duplicate provider sets — THE KEY FINDING
Provider-set overlap (Miami, distinct provider_ids on the cash_price path) and
provider-type mix:

| Group | Overlap finding | Provider types | Verdict |
|---|---|---|---|
| **Injectables** (Botox, Fillers, CoolSculpting) | Identical 478-provider set (Botox∩CoolSculpting = 478/478/478; Botox∩Fillers = 478) | 351 Clinic + 77 Plastic Surgery + 50 Med Spa | **Shared but APPROPRIATE** — med spas/clinics genuinely offer all three. Prices differ per procedure (modeled). ✅ |
| **Plastic surgery (surgical)** (Rhinoplasty, Liposuction, Breast Aug, Blepharoplasty, Facelift) | Same ~433-provider set across all five (Rhino∩Lipo = 433/433); ~99% is a **subset of the injectable medspa pool** (Botox∩Rhino = 428) | **351 generic "Clinic" (81%)** + only 77 real "Plastic Surgery Practice" (18%) + 5 hospital/surgery | **CONTAMINATED** — the same medspa pool (and an orthodontist: *"123Braces… Miami Beach Orthodontics"* listed with a $7,918 rhinoplasty / $12,488 facelift) is bulk-assigned surgical procedures. Same bug class as "ENT at $78 on an MRI page." ❌ |
| **Dental** (Crown, Implant, Whitening) | Distinct ~90-provider set; Dental∩LASIK = **0** | All "Dental Office" | **Genuinely distinct & credible** ✅ |
| **LASIK** | Distinct ~49–61 set | 57 Eye Center + 4 Hospital (47 rows are real `CMS Price Transparency`, rest estimates) | **Distinct & credible** ✅ |
| **Fertility** (IVF, Egg Freezing, IUI) | Egg Freezing & IUI = identical 2,940 set; IVF = those + 47 | All "Fertility Clinic" | **Shared but APPROPRIATE** — fertility clinics do all three ✅ |
| **Gastric Sleeve** | Distinct ~53–60 set | 54 Weight Loss Clinic + 4 Hospital + 1 Surgery Center | **Distinct & credible** ✅ |
| **FUE Hair Transplant** | Distinct ~47–54 set | 51 Hair Restoration Clinic | **Distinct & credible** ✅ |

**Price source:** ~all records are `price_type='estimated'`, `source_name='Market
Estimate'`, `confidence='medium'` (only ~47 LASIK/Rhino rows are real CMS data).
These are **modeled market estimates, not verified provider quotes** — the
honest-labeling already on the cash pages ("advertised market estimates") is
accurate and essential.

## 3. Data-quality smells
- **"Hollywood FL FL" is a DATA problem, not the template.** 155 `healthcare_location`
  rows have a city value ending in a 2-letter token (`Hollywood Fl`, `Andover Ma`,
  also junk like `1120 15Th St`, `Apo Ae`). The template faithfully renders
  `{{ city }}, {{ state }}` → "Hollywood FL, FL". 74 are state-doubling, 81 are other
  junk (street addresses / APO military codes). **2,470 providers** attach to these
  155 bad locations → exclude/clean these locations before generating city pages.
- **Duplicate-phone cleaning is NOT applied to the market pages.** `dedupe_ranked_providers`
  (phone-dedupe) is used only by `views_cash`. `views_market.procedure_market` groups
  by `provider_id` only, so shared-phone rows (e.g. one hospital switchboard as 10
  "providers") still appear on `/market/` pages. Separate fix.

## GO / NO-GO for mass-generating cash-pay pages
Gated behind the global blocker (set `is_cash_pay_common=true` in prod first).

**GO** (credible, distinct/appropriate provider→procedure mapping; keep
"market estimate" labeling):
- Injectables: **Botox, Dermal Fillers, CoolSculpting**
- Dental: **Crown, Implant, Teeth Whitening**
- **LASIK**, **FUE Hair Transplant**, **Gastric Sleeve**
- Fertility: **IVF, Egg Freezing, IUI**

**NO-GO until provider→procedure mapping is restricted** (e.g. limit to
`Plastic Surgery Practice` / `Surgery Center` / `Hospital`, dropping the 351
generic-"Clinic" medspa rows): **Rhinoplasty, Liposuction, Breast Augmentation,
Blepharoplasty, Facelift**. Numbers are plausible but the providers listed would
be wrong (med spas/orthodontists as surgeons).

**Cross-cutting before launch:** (a) set `is_cash_pay_common` in prod; (b) exclude
the 155 malformed locations; (c) decide whether to apply phone-dedupe to market
pages; (d) confirm the "GO" set still clears the ≥10-clean-providers thin-data
guard per city you intend to index (Miami/LA/NY all clear it; smaller cities won't).

---

# PRODUCTION WRITES + DATA-QUALITY FIXES — 2026-06-08

Targeted production writes (Task 1) plus two code-level data-quality fixes
(Tasks 2 & 3). Write discipline followed: pre-write COUNT, explicit transaction
with in-transaction guard, post-write verification. No schema changes, no
migrations, no deletes.

**Backup:** Railway managed backups are not confirmable via the CLI
(dashboard-only). Safety net taken before writes: a local CSV snapshot of all
6,472 `healthcare_procedure` flag values (`.dbbackup/…`, gitignored) — a precise
restore point for Task 1.

## Task 1 — Flagged the 12 GO procedures `is_cash_pay_common=true` (prod) ✅
- Pre-write: each of the 12 names matched **exactly one** row; total to update = **12**.
  Name correction surfaced: the brief listed "IUI (Intrauterine Insemination)" but
  the stored name is **"IUI"** — matched the real row, did not guess.
- Write: `BEGIN; UPDATE … WHERE name IN (12 names); <guard: abort if true≠12>; COMMIT;`
  → `UPDATE 12`, guard OK, committed.
- Post-write verify: **exactly 12 true** (Botox, Dermal Fillers, CoolSculpting,
  Dental Crown, Dental Implant, Teeth Whitening, LASIK, FUE Hair Transplant,
  Gastric Sleeve, IVF Cycle, Egg Freezing, IUI); the **5 surgical procedures
  remain `false`** (Rhinoplasty, Liposuction, Breast Augmentation, Blepharoplasty,
  Facelift); no other procedure accidentally true.

## Task 2 — Exclude malformed locations from city pages (code, no prod write) ✅
**Count correction (flagged per discipline):** the audit's "155" used an
over-broad regex (` [A-Za-z]{2}$`) that also catches **legitimate** cities — e.g.
**Santa Fe, NM**. The genuinely-malformed set is **102 locations**, in three
precise categories:
- **74 state-doubling** — city ends in space + 2 letters equal to state (`Hollywood FL`/FL)
- **16 street-address-as-city** — starts with a digit (`2500 Alhambra Avenue`, `11978`)
- **13 military APO/FPO/DPO** (`Apo Ae`, `Fpo Ap`)

(User chose the precise-102 set.) Impact: 504 providers attach to these 102; 297
are cash_price providers for the 12 GO procedures.

**Mechanism (no schema change):** `healthcare/location_quality.py` — single source
of truth with `is_malformed_location(city, state)` (pure Python) and
`exclude_malformed_locations(qs, prefix='')` (ORM, mirrors the predicate). Applied:
- `views_cash.cash_procedure_city` → **404** for a malformed location (no page).
- `views_cash.cash_procedure_national` → malformed cities dropped from by-city table.
- `views.cities_index` → malformed locations excluded from the listing.
- Sitemaps untouched (out of scope).

**Verified (local, same 102 set):** Python predicate flags 102, ORM helper excludes
102 (consistent). `/cash/botox-full-face/hollywood-fl-fl/` → **404**;
`/cash/botox-full-face/miami-fl/` → **200**. Predicate unit-tests pass incl. the
false-positive guards (Santa Fe, Washington Ch kept).
*Known minor edge:* "100 Mile House, BC" (a real Canadian town, digit-prefixed) is
caught by the street-address rule — harmless for US city pages.

## Task 3 — Phone-dedup on market pages (code) ✅
`views_market.procedure_market` now builds its ranked provider list via the shared
`market_utils.dedupe_ranked_providers` (per-provider lowest price + duplicate-phone
collapse + low-outlier drop), the same cleaning the cash pages use. `provider_count`
now reflects the cleaned list for headline/snapshot/FAQ consistency.
**Before/after (MRI brain without contrast / Miami):** **69 → 42 providers**
(27 duplicate-phone entries collapsed, 0 outliers dropped); page renders 200.

## Files changed (code, this session)
- **New:** `healthcare/location_quality.py`
- **Modified:** `healthcare/views_cash.py` (malformed-location 404 + by-city filter),
  `healthcare/views.py` (`cities_index` exclusion), `healthcare/views_market.py`
  (phone-dedup ranked list + provider_count), `.gitignore` (ignore `.dbbackup/`).
- `python manage.py check` → no issues. No migrations.

## What remains before mass-generation
1. **The actual generate step** — enumerate the 12 GO procedures × eligible cities
   (respecting the ≥10-clean-providers thin-data guard and the malformed-location
   exclusion), then build/index pages. Not done this session.
2. **Plastic-surgery mapping fix** (separate session) — restrict Rhinoplasty,
   Liposuction, Breast Augmentation, Blepharoplasty, Facelift to surgical provider
   types (Plastic Surgery Practice / Surgery Center / Hospital), dropping the generic
   "Clinic" medspa pool, before flagging them `is_cash_pay_common=true`.
3. **Sitemap** generation for `/cash/` pages — deferred (left serving as-is).
4. Optional: extend the malformed-location exclusion to the `/market/` city pages
   and `city_detail` if those will be (re)generated.

---

# PROVIDER-TYPE WHITELIST (contamination fix) — 2026-06-09

The cash-pay pages had a provider→procedure contamination bug: the generic
**"Clinic"** provider-type bucket (from scraped "Market Estimate" data) was
bulk-assigned procedures, so the Botox/Miami tail listed orthodontists, an
endocrinologist, general-surgery and weight clinics. A user seeing an orthodontist
on the Botox list distrusts the whole page. Counts missed this — rendered lists
caught it.

## Step 1 — Provider-type distribution (national, distinct providers w/ cash_price)
| Procedure(s) | Credible types | Contaminant "Clinic" |
|---|---|---|
| Botox / CoolSculpting / Dermal Fillers | Plastic Surgery 5,350 · Med Spa 5,214 | **1,373** |
| Dental Crown / Implant / Teeth Whitening | Dental Office ~7,775 | 0 |
| LASIK | Eye Center 2,831 · Hospital 47 | 0 |
| FUE Hair Transplant | Hair Restoration Clinic 1,511 | 0 |
| Gastric Sleeve | Weight Loss 3,982 · Hospital 44 · Surgery Center 9 | 0 |
| IVF / Egg Freezing / IUI | Fertility Clinic 2,940 · Hospital ≤47 | 0 |
| Rhinoplasty/Lipo/Breast Aug/Bleph/Facelift *(surgical, OFF)* | Plastic Surgery 5,350 · Surgery Center 9 · Hospital ≤47 | **1,373** |

Contamination is **injectables + surgical only, and Miami-concentrated** (Botox/Miami
"Clinic" = 295–351 of the pool; LA/NY "Clinic" = 0). Proof — Botox/Miami "Clinic"
sample: `123Braces… Miami Beach Orthodontics`, `Sun Orthodontist`, `Miami Diabetes &
Endocrinology`, `Steward Orthopedics and General Surgery`. The bucket also holds a few
**legit med spas miscategorized as "Clinic"** (`4Beauty Medspa`), so it can't be split
by type → drop the whole bucket (precision over recall).

## Step 2 — Approved whitelist (`healthcare/provider_whitelist.py`)
Data-driven mapping, procedure-slug → allowed `ProviderType.name`:

| Procedure(s) | Whitelist |
|---|---|
| botox-full-face, dermal-fillers-lips, coolsculpting | Med Spa, Plastic Surgery Practice, Dermatology |
| dental-crown-porcelain, dental-implant-single, teeth-whitening | Dental Office |
| lasik-both-eyes | Eye Center, Hospital |
| fue-hair-transplant | Hair Restoration Clinic |
| gastric-sleeve | Weight Loss Clinic, Surgery Center, Hospital |
| ivf-cycle, egg-freezing, iui | Fertility Clinic, Hospital |
| rhinoplasty, liposuction, breast-augmentation, blepharoplasty, facelift *(staged for when surgical is enabled; Med Spa intentionally excluded)* | Plastic Surgery Practice, Surgery Center, Hospital |

- **"Dermatology" verified allowed-if-present and a true no-op:** there are **0**
  Dermatology-typed providers with cash_price records anywhere in the DB, so it
  filters nothing today — purely future-proofing.
- **Thin-data after cleaning:** every GO procedure's credible pool stays ≥51 in
  Miami/LA/NY — **no procedure dropped below the 10-provider threshold.** Smaller
  cities remain auto-guarded by the render-time ≥10 check.

## Step 3 — Implementation
`healthcare/provider_whitelist.py` (config mapping + `allowed_provider_types(slug)`),
applied in `views_cash._cash_records` before the tagged/legacy split, so the median,
ranking, and by-city table all reflect only credible providers. No schema change, no
prod write. `manage.py check` clean.

## Step 4 — Rendered before/after (the gate)
**Botox (Full Face) / Miami:** 403 → **112** providers.
- Types BEFORE: Med Spa 49 · **Clinic 295** · Plastic Surgery 59
- Types AFTER:  Med Spa 49 · Plastic Surgery 63 *(no Clinic)*
- Removed (sample): Sun Orthodontist Braces & Invisalign, Esteem Braces & Aligners,
  Miami Diabetes & Endocrinology, Steward Orthopedics and General Surgery, Vida
  Hormone Therapy, Majestic Whitening, Miami Dermatology and Mohs Surgery *(real derm
  typed "Clinic" — approved precision casualty)*.
- AFTER tail now all credible: Alicia Med Spa, CG Cosmetic Surgery, Xiluet Plastic
  Surgery, Chopra Plastic Surgery.
- *(Plastic Surgery rose 59→63: removing junk un-suppressed 4 plastic surgeons that
  had shared a phone with a cheaper Clinic entry — a positive side effect.)*

**LASIK (Both Eyes) / Miami:** 49 → **49**, 0 removed — all Eye Center (45) + Hospital (4).

Both pages render 200; rendered HTML contains **no** Orthodont/Endocrinolog/Braces/
Diabetes strings.

## Status / what remains
- Whitelist committed to `cash-pay-pages` (not pushed). Ready code `980f2a4`
  (+ empty `a84a65d` "Trigger redeploy") is staged to merge independently first.
- Before mass-generation: merge/deploy ready code; then (separately) the whitelist;
  fix + enable the 5 surgical procedures; sitemap generation. No mass-generation done.

---

# DEPLOY + PRODUCTION VERIFICATION — 2026-06-10

Both commits are now in `origin/main` and live in production. (They had already
been merged to `main` between sessions — `980f2a4` ready code and `780f73a`
whitelist are both ancestors of the current `origin/main` tip, which has since
advanced with sitemap/cache work. No further push was needed; the planned
`git push origin a84a65d:main` was NOT run — it would have rewound `main` and
deleted the newer commits.)

**Live production verification (read-only against https://zenthir.com):**

Ready code (location-exclusion + market phone-dedup):
- `GET /market/mri-scan-of-brain-without-contrast/miami-fl/` → **200**, provider
  count **8**. NOTE: not the local "~42" — production has real `billing_component`
  tagging so the market view filters to facility-component only (a stricter,
  smaller set) then phone-dedups; the local 42 used the "mixed" fallback because
  local lacks `billing_component`. Phone-dedup code confirmed present in
  `origin/main:views_market.py`. (Market template does not render phone numbers,
  so duplicate-phone is verified via the code path + reduced count, not visually.)
- `GET /cash/botox-full-face/hollywood-fl-fl/` → **404** ✓ (malformed location)
- `GET /cash/botox-full-face/miami-fl/` → **200** ✓ (normal location)

Whitelist (provider-type contamination fix):
- `GET /cash/botox-full-face/miami-fl/` → **200**, provider count **112** (down from
  403) ✓. Contamination strings (Orthodont / Braces / Endocrinolog / Diabetes /
  Invisalign / Weight Loss) → **NONE** ✓.
- `GET /cash/lasik-both-eyes/miami-fl/` → **200**, **49** providers, all Eye Center
  ✓ (clean procedure unaffected).

**Production state now confirmed:**
- ✅ 12 procedures flagged `is_cash_pay_common=true`; the 5 surgical still `false`.
- ✅ Malformed locations cleaned (102-row exclusion live → city 404s).
- ✅ Market pages phone-deduped.
- ✅ Provider-type whitelist applied (Clinic-bucket contamination gone).

**Next session:** mass-generation of cash-pay pages + sitemaps (and, separately,
fixing/enabling the 5 surgical procedures). None of that done here — deploy+verify only.


---

# CASH-PAY SITEMAP GENERATION — 2026-06-10

Branch: `cash-pay-sitemap` (off `origin/main` 5b7d294). The ready code + whitelist
are already live in production (prior session). This session adds the cash-pay
pages to the sitemap so Google discovers/crawls them. No new pages were generated —
the cash views already render dynamically; this is sitemap-only.

**Git state cleanup (Step 0):** the prior session's local-only PROGRESS commit
`1688c23` (deploy verification) was moved to branch `progress-doc-update`; local
`main` reset to `origin/main`; work done on new branch `cash-pay-sitemap`.
(Note: the `1688c23` deploy-verification notes live on `progress-doc-update` and
still need reconciling into main's PROGRESS.)

## Step 1 — Qualifying page set (read-only prod)
Per procedure, count of cities with **≥10 clean providers**, computed with the exact
view logic (whitelist → per-provider min → low-outlier floor 0.10×median →
phone-dedup), excluding malformed locations:

| Procedure | Cities |
|---|---|
| Botox (Full Face) | 113 |
| Dermal Fillers (Lips) | 113 |
| CoolSculpting | 113 |
| Dental Crown (Porcelain) | 107 |
| Dental Implant (Single) | 107 |
| Teeth Whitening | 107 |
| Gastric Sleeve | 102 |
| LASIK (Both Eyes) | 80 |
| IVF Cycle | 75 |
| Egg Freezing | 74 |
| IUI | 74 |
| FUE Hair Transplant | 56 |
| **City pages total** | **1,121** |
| National pages (`/cash/<proc>/`) | 12 |
| **Grand total cash URLs** | **1,133** |

In the expected low-thousands range (12 × ~56–113 cities, threshold-gated). No
sanity alarm.

## Step 2 — Sitemap generated
- New command **`healthcare/management/commands/generate_cash_sitemaps.py`** —
  self-contained, reproducible. Computes qualifying combos via SQL that mirrors the
  view (whitelist pulled from `provider_whitelist`, malformed rules from
  `location_quality`), writes `sitemap-cash-N.xml` (chunked at 10k), and patches the
  index `sitemap.xml` idempotently (own child sitemap → separately trackable in
  Search Console). Run against prod read-only (`PGOPTIONS` enforced).
- **Files:** `static_src/sitemaps/sitemap-cash-1.xml` (1,133 URLs — all 1,133 fit in
  one file, well under the 50k limit) + `static_src/sitemaps/sitemap.xml` index gains
  one `<sitemap>` entry for the cash child. No other sitemap files touched.
- City pages priority 0.8, national 0.7 (matching existing market/procedure priorities).

## Step 3 — Verification (local pre-deploy + production post-deploy)
Local pre-deploy:
- ✅ `sitemap-cash-1.xml` well-formed XML, 1,133 `<loc>` (1,121 city + 12 national), all `/cash/`.
- ✅ Index `sitemap.xml` well-formed (24 children) and references `sitemap-cash-1.xml`.
- ✅ Sample URLs 200 / not-noindex locally; no thin/malformed/surgical leakage; exactly 12 GO slugs.

## DEPLOYED + PRODUCTION-VERIFIED — 2026-06-10
Branch `cash-pay-sitemap` (commit `d822e5b`) fast-forward-merged to `main` and pushed
(`5b7d294..d822e5b`) → Railway redeployed (web ● Online). Production verification
(curl needed a browser User-Agent — Cloudflare blocks the default curl UA, which had
caused the prior "HTTP 000" timeouts):
- ✅ `GET /static/sitemaps/sitemap-cash-1.xml` → **HTTP 200**, `content-type: text/xml`, **1,133 URLs** served.
- ✅ `GET /sitemap.xml` → **HTTP 200**, `text/xml`, references `sitemap-cash-1.xml`.
- ✅ `GET /cash/botox-full-face/akron-oh/` → **200**, not noindex (84 providers).
- ✅ `GET /cash/lasik-both-eyes/akron-oh/` → **200**, not noindex (36 providers).
- ✅ `GET /cash/dental-crown-porcelain/akron-oh/` → **200**, not noindex (58 providers).

## What remains
1. **Submit to Search Console** — the cash child sitemap is live and trackable separately.
2. **5 surgical procedures** — fix provider mapping + enable `is_cash_pay_common`, then
   re-run `manage.py generate_cash_sitemaps` (auto-includes any flagged procedure) and redeploy.
3. **Stale `static_sitemaps/` dir** (103 files, unserved) — untouched; flagged for later cleanup.

---

# SURGICAL PROCEDURES ENABLED + SITEMAP EXPANDED + STALE DIR REMOVED — 2026-06-10

Branch: `surgical-cash-enable` (off `main` ffa7357). Enabled the 5 surgical
plastic-surgery procedures with the surgeon-only whitelist, regenerated the cash
sitemap to include them, and removed the stale `static_sitemaps/` dir.

## Task 1 — Surgical procedures enabled (surgeon-only whitelist)
The whitelist (`provider_whitelist.py`) already restricts the 5 surgical procedures
to **Plastic Surgery Practice, Surgery Center, Hospital** (Med Spa intentionally
excluded). 

**1a — credible surgeon-only pool (read-only prod), all clear the ≥10 threshold:**
| Procedure | Miami | LA | NY | Median (Miami) |
|---|---|---|---|---|
| Rhinoplasty | 68 | 64 | 62 | $8,992 |
| Liposuction | 68 | 64 | 62 | $5,216 |
| Breast Augmentation | 68 | 63 | 61 | $7,174 |
| Blepharoplasty | 63 | 58 | 58 | $4,321 |
| Facelift | 63 | 58 | 58 | $13,534 |

None thin (surgeon-only removed ~290 contaminating providers vs the old ~354 Miami pool).

**1b — render-eyeball gate (confirmed clean before flag write):** Rhinoplasty/Miami
(68 providers: 63 Plastic Surgery Practice + 4 Hospital + 1 Surgery Center) and
Facelift/Miami (63 Plastic Surgery Practice) rendered with **0 non-surgeon entries** —
no med spas, no orthodontists, no generic clinics. User confirmed.

**1c — production flag write (discipline followed):** snapshot saved; pre-count = 12
true + 5 surgical false; guarded transaction (`UPDATE 5`, guard aborts unless 17 true);
post-verify = **17 total true** (5 surgical now true, original 12 still true, no extras).

## Task 2 — Cash sitemap regenerated (now 17 procedures)
Re-ran `generate_cash_sitemaps` against prod (read-only). New per-procedure city counts
for the surgical additions: Rhinoplasty 112, Liposuction 112, Breast Augmentation 112,
Blepharoplasty 112, Facelift 112 (the original 12 unchanged). **Total cash URLs:
1,133 → 1,698** (1,681 city + 17 national; +565). Validated locally: well-formed XML,
exactly the 17 GO procedures (no others), 0 thin/malformed leakage, index references the
cash child; surgical city pages render 200/not-noindex.

## Task 3 — Stale `static_sitemaps/` dir removed
Confirmed genuinely unserved: **zero references** in any code/config; serving is from
`static_src/sitemaps/` (`SITEMAP_DIR` in config/urls.py) and `STATICFILES_DIRS=[static_src]`.
Removed all 103 tracked files (94 provider + 5 market + locations/procedures/static/index).
This eliminates the two-directories confusion. The live `static_src/sitemaps/` is untouched
(only `sitemap-cash-1.xml` changed, now 1,698 URLs).

## What remains
1. **Deploy** — branch `surgical-cash-enable` NOT pushed (pushing `main` → Railway deploy).
   Awaiting review before push/merge. Diff: `sitemap-cash-1.xml` (1,698 URLs) + 103
   `static_sitemaps/` deletions + this PROGRESS update. (No code change — the whitelist
   already covered surgical; the prod flag flip is already live.)
2. **Re-verify in prod after deploy** (browser UA): `sitemap-cash-1.xml` → 200/XML with
   1,698 URLs; spot-check a surgical city (e.g. `/cash/rhinoplasty/miami-fl/`) → 200, not noindex.
3. **Submit/refresh in Search Console.**
Note: the prod `is_cash_pay_common` flag for the 5 surgical is ALREADY live (Task 1c),
so surgical cash pages render in production now; the deploy only ships the expanded
sitemap + dir cleanup.
