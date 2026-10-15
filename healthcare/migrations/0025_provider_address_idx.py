"""Index Provider.address.

provider_detail checks how many providers share an address on every page
view. Without an index that is a full scan of healthcare_provider
(~2.97M rows, ~2.7s), which saturates the gunicorn workers under crawler
load and produces 524s.

Built CONCURRENTLY so the table is never locked for writes. IF NOT EXISTS
makes this a no-op if the index was already created by hand in psql.

Depends on 0021 (the latest committed migration) rather than the
uncommitted 0020/0022-0024 work in the tree, so it can ship on its own.
When that work is committed, run `makemigrations --merge` to join the
two leaves.

The index is created with raw SQL, so it is not part of the model state
and makemigrations will not try to add or drop it.
"""
from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # CREATE INDEX CONCURRENTLY cannot run inside a transaction

    dependencies = [
        ("healthcare", "0021_pricingrecord_price_basis"),
    ]

    operations = [
        migrations.RunSQL(
            sql="CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_provider_address "
                "ON healthcare_provider (address);",
            reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS idx_provider_address;",
        ),
    ]
