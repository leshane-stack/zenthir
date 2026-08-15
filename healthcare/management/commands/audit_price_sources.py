"""Log every PricingRecord source_name that matches no display allowlist prefix,
with its row count. A future import landing under a new/unexpected name surfaces
loudly here instead of being silently suppressed on every page.

Run standalone, or rely on the call wired into compute_medians (post-import).
"""
from django.core.management.base import BaseCommand
from healthcare.price_visibility import audit_source_names, ALLOWED_SOURCE_PREFIXES


class Command(BaseCommand):
    help = 'Report PricingRecord source_names that are suppressed (match no allowlist prefix).'

    def handle(self, *args, **options):
        self.stdout.write('Allowlist prefixes:')
        for p in ALLOWED_SOURCE_PREFIXES:
            self.stdout.write(f'    {p!r}')
        suppressed = audit_source_names()
        if suppressed:
            total = sum(n for _, n in suppressed)
            self.stdout.write(self.style.WARNING(
                f'\n{len(suppressed)} suppressed source_name value(s), {total:,} rows:'))
            for name, n in suppressed:
                self.stdout.write(f'  {n:>13,}  {name!r}')
        else:
            self.stdout.write(self.style.SUCCESS('\nAll source_name values are allowlisted.'))
