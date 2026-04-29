from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_admissionapplication_more_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="careerapplication",
            name="address",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="careerapplication",
            name="cnic_number",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="careerapplication",
            name="date_of_birth",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="careerapplication",
            name="job_post_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="careerapplication",
            name="organization_name",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="careerapplication",
            name="religion",
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
