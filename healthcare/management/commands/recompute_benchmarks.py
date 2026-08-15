"""Recompute the price benchmarks (ProcedureMedian + Procedure.national_*) from
SUBMITTED-CHARGE rows only, so the benchmark is the same basis as the charge the
provider pages render ("Submitted Charge"). Replaces the previous one-off that
populated national_* over a blend of negotiated + submitted + fabricated rows.

Repeatable and reviewable. Filters on price_basis='submitted_charge' (populated by
backfill_price_basis), NOT on a startswith against source_name. Batched by
procedure id so no single statement rewrites 605K medians at once.

Reports rows changed, how many medians moved materially (>10%), and before/after
national_median for three reference codes (761, 5, 1).
"""
from django.core.management.base import BaseCommand
from django.db import connection

BASIS = 'submitted_charge'
NAT_FIELDS = ['national_median', 'national_p25', 'national_p75', 'national_p5',
              'national_p95', 'national_avg', 'national_avg_medicare',
              'national_record_count', 'national_provider_count']
REF_CODES = [761, 5, 1]


class Command(BaseCommand):
    help = 'Recompute ProcedureMedian + Procedure.national_* from submitted_charge rows (batched).'

    def add_arguments(self, p):
        p.add_argument('--batch', type=int, default=500, help='procedures per batch window')
        p.add_argument('--min-providers', type=int, default=5, help='ProcedureMedian floor')

    def _proc_bounds(self, cur):
        cur.execute('SELECT MIN(id), MAX(id) FROM healthcare_procedure')
        return cur.fetchone()

    def _ref_nat(self, cur):
        cur.execute('SELECT id, national_median FROM healthcare_procedure WHERE id = ANY(%s)', [REF_CODES])
        return {r[0]: r[1] for r in cur.fetchall()}

    def handle(self, *args, **o):
        batch = o['batch']
        floor = o['min_providers']
        with connection.cursor() as cur:
            cur.execute("SET statement_timeout = '600s'")
            before_ref = self._ref_nat(cur)

            # ---------- Phase A: ProcedureMedian ----------
            self.stdout.write('Phase A: ProcedureMedian (submitted_charge only)')
            cur.execute('DROP TABLE IF EXISTS _old_pm')
            cur.execute('CREATE TEMP TABLE _old_pm AS SELECT procedure_id, location_id, '
                        'provider_type_id, median_price FROM healthcare_proceduremedian')
            cur.execute('SELECT COUNT(*) FROM _old_pm')
            old_pm_n = cur.fetchone()[0]
            cur.execute('DELETE FROM healthcare_proceduremedian')

            lo, hi = self._proc_bounds(cur)
            start = lo
            while start <= hi:
                end = start + batch - 1
                cur.execute(f'''
                    INSERT INTO healthcare_proceduremedian
                        (procedure_id, location_id, provider_type_id, median_price, p25, p75, provider_count, updated_at)
                    SELECT pr.procedure_id, p.location_id, p.provider_type_id,
                        PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY pr.cash_price),
                        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY pr.cash_price),
                        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY pr.cash_price),
                        COUNT(DISTINCT p.id), NOW()
                    FROM healthcare_pricingrecord pr
                    JOIN healthcare_provider p ON pr.provider_id = p.id
                    WHERE pr.price_basis = %s AND pr.cash_price > 0
                      AND p.location_id IS NOT NULL AND p.provider_type_id IS NOT NULL
                      AND pr.procedure_id BETWEEN %s AND %s
                    GROUP BY pr.procedure_id, p.location_id, p.provider_type_id
                    HAVING COUNT(DISTINCT p.id) >= %s
                ''', [BASIS, start, end, floor])
                start = end + 1
            cur.execute('SELECT COUNT(*) FROM healthcare_proceduremedian')
            new_pm_n = cur.fetchone()[0]
            cur.execute('''SELECT COUNT(*) FROM healthcare_proceduremedian n
                JOIN _old_pm o ON n.procedure_id=o.procedure_id AND n.location_id=o.location_id
                   AND n.provider_type_id=o.provider_type_id
                WHERE o.median_price > 0 AND ABS(n.median_price - o.median_price)/o.median_price > 0.10''')
            pm_moved = cur.fetchone()[0]
            self.stdout.write(self.style.SUCCESS(
                f'  ProcedureMedian: {old_pm_n:,} -> {new_pm_n:,} rows; {pm_moved:,} kept-keys moved >10%'))

            # ---------- Phase B: Procedure.national_* ----------
            self.stdout.write('Phase B: Procedure.national_* (submitted_charge only)')
            cur.execute('DROP TABLE IF EXISTS _old_nat')
            cur.execute('CREATE TEMP TABLE _old_nat AS SELECT id, national_median FROM healthcare_procedure')
            cur.execute('UPDATE healthcare_procedure SET ' + ', '.join(f'{f}=NULL' for f in NAT_FIELDS))

            start = lo
            while start <= hi:
                end = start + batch - 1
                cur.execute('''
                    UPDATE healthcare_procedure p SET
                        national_median = s.p50, national_p25 = s.p25, national_p75 = s.p75,
                        national_p5 = s.p5, national_p95 = s.p95, national_avg = s.avg,
                        national_avg_medicare = s.avg_ins,
                        national_record_count = s.n, national_provider_count = s.np
                    FROM (
                        SELECT pr.procedure_id,
                            PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY pr.cash_price) p50,
                            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY pr.cash_price) p25,
                            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY pr.cash_price) p75,
                            PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY pr.cash_price) p5,
                            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY pr.cash_price) p95,
                            AVG(pr.cash_price) avg, AVG(pr.insured_price) avg_ins,
                            COUNT(*) n, COUNT(DISTINCT pr.provider_id) np
                        FROM healthcare_pricingrecord pr
                        WHERE pr.price_basis = %s AND pr.cash_price > 0
                          AND pr.procedure_id BETWEEN %s AND %s
                        GROUP BY pr.procedure_id
                    ) s
                    WHERE p.id = s.procedure_id
                ''', [BASIS, start, end])
                start = end + 1

            cur.execute('''SELECT COUNT(*) FROM healthcare_procedure n JOIN _old_nat o ON n.id=o.id
                WHERE COALESCE(o.national_median,0) <> COALESCE(n.national_median,0)''')
            nat_changed = cur.fetchone()[0]
            cur.execute('''SELECT COUNT(*) FROM healthcare_procedure n JOIN _old_nat o ON n.id=o.id
                WHERE o.national_median > 0 AND n.national_median IS NOT NULL
                  AND ABS(n.national_median - o.national_median)/o.national_median > 0.10''')
            nat_moved = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM healthcare_procedure WHERE national_median IS NOT NULL')
            nat_have = cur.fetchone()[0]
            self.stdout.write(self.style.SUCCESS(
                f'  national_*: {nat_changed:,} procedures changed, {nat_moved:,} moved >10%, '
                f'{nat_have:,} now have a national_median'))

            after_ref = self._ref_nat(cur)
            self.stdout.write('  Reference codes (national_median before -> after):')
            for cid in REF_CODES:
                self.stdout.write(f'    id {cid}: {before_ref.get(cid)} -> {after_ref.get(cid)}')
