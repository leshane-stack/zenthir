"""
Generate the cash-pay child sitemap(s) and register them in the sitemap index.

Kept separate from `generate_sitemaps` so cash URLs live in their own child
sitemap(s) (sitemap-cash-N.xml) — trackable separately in Search Console — and so
this can be re-run incrementally without regenerating the provider/market/etc.
sitemaps. It only writes the cash file(s) and patches the index in place.

Page set = exactly the indexable cash pages: for each is_cash_pay_common procedure,
the procedure×city combos with >= THRESHOLD clean providers, where "clean" mirrors
the live view (views_cash + market_utils.dedupe_ranked_providers + location_quality):

  * provider-type whitelist (healthcare/provider_whitelist.py) — drops the
    contaminated "Clinic" bucket,
  * one row per provider (lowest cash_price),
  * low-outlier floor: drop providers priced below 0.10 × median,
  * duplicate-phone collapse (keep cheapest per phone),
  * malformed locations excluded (state-doubling / street-address / APO-FPO).

Thin combos (< THRESHOLD) are intentionally omitted — those pages render noindex,
so they must not be in the sitemap. National pages (/cash/<proc>/) are always
included for the flagged procedures.

Run against production (read-only) to produce the committed files, e.g.:
  RAILWAY_ENVIRONMENT=1 DATABASE_URL=<prod-url> \
  PGOPTIONS='-c default_transaction_read_only=on' \
  python manage.py generate_cash_sitemaps
"""
import os
from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import connection

from healthcare.models import Procedure
from healthcare.provider_whitelist import allowed_provider_types

BASE_URL = 'https://zenthir.com'
SM_PREFIX = f'{BASE_URL}/static/sitemaps'
THRESHOLD = 10
CHUNK = 10000

# Fixed body of the qualifying-combo query. The wl(slug, ptype) VALUES list is
# prepended at runtime from provider_whitelist (so it stays in sync with the view).
# Regex conditions mirror healthcare/location_quality.is_malformed_location.
_COMBO_BODY = r"""
prov AS (
  SELECT pc.slug AS proc, loc.id AS loc_id, loc.slug AS city_slug,
         pv.id AS pid,
         regexp_replace(coalesce(pv.phone,''), '\D', '', 'g') AS ph,
         MIN(r.cash_price) AS price
  FROM healthcare_pricingrecord r
  JOIN healthcare_provider pv ON pv.id = r.provider_id
  JOIN healthcare_location loc ON loc.id = pv.location_id
  JOIN healthcare_procedure pc ON pc.id = r.procedure_id
  JOIN healthcare_providertype pt ON pt.id = pv.provider_type_id
  JOIN wl ON wl.slug = pc.slug AND wl.ptype = pt.name
  WHERE r.price_category = 'cash_price' AND r.cash_price IS NOT NULL AND r.cash_price <> 0
    AND NOT (loc.city ~ '^\s*[0-9]')
    AND NOT (loc.city ~* '^\s*(apo|fpo|dpo)[ ,]')
    AND NOT (loc.city ~ ' [A-Za-z]{2}$' AND upper(right(loc.city, 2)) = upper(loc.state))
  GROUP BY pc.slug, loc.id, loc.slug, pv.id, ph
),
med AS (
  SELECT proc, loc_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY price) AS median
  FROM prov GROUP BY proc, loc_id
),
floored AS (
  SELECT p.* FROM prov p JOIN med m USING (proc, loc_id) WHERE p.price >= 0.10 * m.median
),
pd AS (
  SELECT *, CASE WHEN ph = '' THEN 0
                 ELSE row_number() OVER (PARTITION BY proc, loc_id, ph ORDER BY price) END AS rn
  FROM floored
),
kept AS (SELECT * FROM pd WHERE ph = '' OR rn = 1)
SELECT proc, city_slug
FROM kept
GROUP BY proc, loc_id, city_slug
HAVING count(*) >= %(threshold)s
ORDER BY proc, city_slug
"""


class Command(BaseCommand):
    help = 'Generate the cash-pay child sitemap(s) and register them in the index.'

    def handle(self, *args, **options):
        output_dir = os.path.join(settings.BASE_DIR, 'static_src', 'sitemaps')
        os.makedirs(output_dir, exist_ok=True)

        go = list(Procedure.objects.filter(is_cash_pay_common=True)
                  .order_by('slug').values_list('slug', flat=True))
        self.stdout.write(f'{len(go)} is_cash_pay_common procedures')

        # Build the whitelist VALUES list from provider_whitelist (DRY with the view).
        pairs = []
        for slug in go:
            for ptype in (allowed_provider_types(slug) or []):
                pairs.append((slug, ptype))
        if not pairs:
            self.stderr.write('No whitelist pairs; aborting.')
            return
        values_sql = ','.join(['(%s,%s)'] * len(pairs))
        params = [v for pair in pairs for v in pair]
        # Use positional placeholders throughout (the VALUES list and the threshold).
        sql = (f'WITH wl(slug, ptype) AS (VALUES {values_sql}), '
               + _COMBO_BODY.replace('%(threshold)s', '%s'))

        with connection.cursor() as cur:
            cur.execute(sql, params + [THRESHOLD])
            combos = cur.fetchall()  # list of (proc_slug, city_slug)

        # Build URL list: national pages for all flagged procedures + qualifying city pages.
        urls = [(f'{BASE_URL}/cash/{slug}/', '0.7') for slug in go]
        urls += [(f'{BASE_URL}/cash/{proc}/{city}/', '0.8') for proc, city in combos]

        # Per-procedure breakdown for the operator.
        from collections import Counter
        by_proc = Counter(proc for proc, _ in combos)
        for slug in go:
            self.stdout.write(f'  {slug}: {by_proc.get(slug, 0)} cities')
        self.stdout.write(f'  national pages: {len(go)}')
        self.stdout.write(f'  TOTAL cash URLs: {len(urls)}')

        # Write cash child sitemap(s), chunked.
        cash_files = []
        for i in range(0, len(urls), CHUNK):
            chunk = urls[i:i + CHUNK]
            page = (i // CHUNK) + 1
            filename = f'sitemap-cash-{page}.xml'
            with open(os.path.join(output_dir, filename), 'w') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
                for loc, priority in chunk:
                    f.write(f'<url><loc>{loc}</loc><changefreq>monthly</changefreq>'
                            f'<priority>{priority}</priority></url>\n')
                f.write('</urlset>\n')
            cash_files.append(filename)
        self.stdout.write(f'  wrote {len(cash_files)} cash sitemap file(s)')

        self._patch_index(output_dir, cash_files)
        self.stdout.write(self.style.SUCCESS('Cash sitemaps generated and index updated.'))

    def _patch_index(self, output_dir, cash_files):
        """Idempotently add the cash child sitemap(s) to sitemap.xml (before </sitemapindex>)."""
        index_path = os.path.join(output_dir, 'sitemap.xml')
        if not os.path.exists(index_path):
            self.stderr.write('sitemap.xml index not found; skipping index patch.')
            return
        with open(index_path) as f:
            lines = f.readlines()
        # Drop any existing cash entries (idempotent re-run).
        lines = [ln for ln in lines if 'sitemap-cash-' not in ln]
        entries = [f'<sitemap><loc>{SM_PREFIX}/{fn}</loc></sitemap>\n' for fn in cash_files]
        out = []
        inserted = False
        for ln in lines:
            if '</sitemapindex>' in ln and not inserted:
                out.extend(entries)
                inserted = True
            out.append(ln)
        if not inserted:  # malformed index without closing tag
            out.extend(entries)
        with open(index_path, 'w') as f:
            f.writelines(out)
