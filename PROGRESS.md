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
