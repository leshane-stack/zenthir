"""Populate PricingRecord.price_basis from source_name, in id-range batches.

Idempotent and repeatable: re-running only touches rows whose price_basis is NULL
(or, with --all, everything). One bulk UPDATE per basis per batch window keeps each
transaction small enough for the container; a 40M-row single UPDATE would not.
"""
from django.core.management.base import BaseCommand
from django.db import connection
from healthcare.models import PricingRecord
from healthcare.price_basis import BASIS_PREFIXES, basis_for


class Command(BaseCommand):
    help = 'Backfill PricingRecord.price_basis from source_name (batched).'

    def add_arguments(self, p):
        p.add_argument('--batch', type=int, default=200_000, help='id-range window size')
        p.add_argument('--all', action='store_true', help='rewrite every row, not just NULL')
        p.add_argument('--only-basis', help='classify only rows mapping to this basis (critical-path)')
        p.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **o):
        from django.db.models import Min, Max
        bounds = PricingRecord.objects.aggregate(lo=Min('id'), hi=Max('id'))
        lo, hi = bounds['lo'], bounds['hi']
        if lo is None:
            self.stdout.write('No rows.'); return
        batch = o['batch']
        only_null = '' if o['all'] else 'AND price_basis IS NULL'
        self.stdout.write(f'Backfilling ids {lo:,}..{hi:,} in windows of {batch:,} '
                          f'({"ALL" if o["all"] else "NULL only"}, dry_run={o["dry_run"]})')
        only = o.get('only_basis')
        prefixes = [(p, b) for p, b in BASIS_PREFIXES if (not only or b == only)]
        if only and not prefixes:
            self.stdout.write(f'No prefixes map to basis {only!r}.'); return
        # One UPDATE per window: a CASE over source_name classifies every row in
        # the id range in a single pass (one statement, not one-per-prefix), each a
        # small bounded transaction. Idempotent via the NULL guard. With --only-basis
        # only that basis's rows are written (critical-path: fewer rows to rewrite).
        case_sql = 'CASE ' + ' '.join(
            "WHEN source_name LIKE %s THEN %s" for _ in prefixes
        ) + ' ELSE price_basis END'
        case_params = []
        for prefix, basis in prefixes:
            case_params += [prefix + '%', basis]
        match_clause = '(' + ' OR '.join('source_name LIKE %s' for _ in prefixes) + ')'
        match_params = [p + '%' for p, _ in prefixes]

        touched = 0
        start = lo
        while start <= hi:
            end = start + batch - 1
            if not o['dry_run']:
                with connection.cursor() as cur:
                    cur.execute(
                        f"UPDATE healthcare_pricingrecord SET price_basis = {case_sql} "
                        f"WHERE id BETWEEN %s AND %s AND {match_clause} {only_null}",
                        case_params + [start, end] + match_params)
                    touched += cur.rowcount
            self.stdout.write(f'  ..ids <= {min(end, hi):,}  rows classified so far: {touched:,}')
            start = end + 1
        total = {}
        with connection.cursor() as cur:
            cur.execute("SELECT price_basis, COUNT(*) FROM healthcare_pricingrecord "
                        "GROUP BY price_basis")
            total = {b: n for b, n in cur.fetchall()}
        self.stdout.write(self.style.SUCCESS('Backfill complete. Per-basis rows touched:'))
        for b, c in sorted(total.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f'  {b:16} {c:,}')
        # Surface anything still NULL (an unmapped/new source_name).
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM healthcare_pricingrecord WHERE price_basis IS NULL")
            nulls = cur.fetchone()[0]
        if nulls:
            self.stdout.write(self.style.WARNING(
                f'  {nulls:,} rows still NULL (source_name maps to no basis) — investigate.'))
