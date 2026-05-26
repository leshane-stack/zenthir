from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('healthcare', '0002_alter_provider_slug'),
    ]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE healthcare_provider ALTER COLUMN slug TYPE varchar(200);",
            reverse_sql="ALTER TABLE healthcare_provider ALTER COLUMN slug TYPE varchar(50);",
        ),
        migrations.RunSQL(
            "ALTER TABLE healthcare_location ALTER COLUMN slug TYPE varchar(200);",
            reverse_sql="ALTER TABLE healthcare_location ALTER COLUMN slug TYPE varchar(50);",
        ),
    ]
