from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_careerapplication"),
    ]

    operations = [
        migrations.AddField(
            model_name="admissionapplication",
            name="academic_group",
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name="admissionapplication",
            name="father_education",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="admissionapplication",
            name="landline_no",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="admissionapplication",
            name="medium",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="admissionapplication",
            name="mother_cell_no",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="admissionapplication",
            name="office_phone_no",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="admissionapplication",
            name="selected_subjects",
            field=models.CharField(blank=True, max_length=200),
        ),
    ]
