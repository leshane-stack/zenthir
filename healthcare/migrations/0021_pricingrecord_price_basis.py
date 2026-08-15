from django.db import migrations, models


class Migration(migrations.Migration):
    # Depends on 0019, NOT the uncommitted collector migration 0020, so deploying
    # this never creates the ObservedPrice/PriceAvailability/PriceReviewItem tables
    # on prod. Adding a nullable column is a metadata-only op on Postgres (instant,
    # no table rewrite) even at 40M rows.
    dependencies = [
        ('healthcare', '0019_providerprofile_providerproceduredetail'),
    ]

    operations = [
        migrations.AddField(
            model_name='pricingrecord',
            name='price_basis',
            field=models.CharField(
                max_length=20, null=True, blank=True,
                choices=[
                    ('submitted_charge', 'Submitted / gross charge'),
                    ('negotiated_rate', 'Insurer-negotiated rate'),
                    ('cash_rate', 'Hospital cash price'),
                    ('medicare_allowed', 'Medicare allowed amount'),
                    ('min', 'Hospital MRF minimum'),
                    ('max', 'Hospital MRF maximum'),
                    ('fabricated', 'Fabricated / synthetic'),
                ],
            ),
        ),
    ]
