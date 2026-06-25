from django.core.management.base import BaseCommand
from django.db import connection
from healthcare.models import ProcedureMedian


class Command(BaseCommand):
    help = 'Compute regional median prices for all procedure+location+type combinations'

    def handle(self, *args, **options):
        self.stdout.write('Computing regional medians...')

        with connection.cursor() as cur:
            # Clear old data
            cur.execute('DELETE FROM healthcare_proceduremedian')
            self.stdout.write(f'  Cleared old medians')

            # Compute medians for all combos with 5+ providers
            cur.execute('''
                INSERT INTO healthcare_proceduremedian
                    (procedure_id, location_id, provider_type_id, median_price, p25, p75, provider_count, updated_at)
                SELECT
                    pr.procedure_id,
                    p.location_id,
                    p.provider_type_id,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pr.cash_price),
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY pr.cash_price),
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY pr.cash_price),
                    COUNT(DISTINCT p.id),
                    NOW()
                FROM healthcare_pricingrecord pr
                JOIN healthcare_provider p ON pr.provider_id = p.id
                WHERE pr.cash_price IS NOT NULL
                  AND pr.cash_price > 0
                  AND p.location_id IS NOT NULL
                  AND p.provider_type_id IS NOT NULL
                GROUP BY pr.procedure_id, p.location_id, p.provider_type_id
                HAVING COUNT(DISTINCT p.id) >= 5
            ''')

            cur.execute('SELECT COUNT(*) FROM healthcare_proceduremedian')
            count = cur.fetchone()[0]
            self.stdout.write(self.style.SUCCESS(f'  Computed {count:,} medians'))
