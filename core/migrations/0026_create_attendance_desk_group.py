from django.db import migrations


def create_attendance_desk_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="Attendance Desk")


def remove_attendance_desk_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="Attendance Desk").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_schooltimingsettings_school_end_time"),
    ]

    operations = [
        migrations.RunPython(
            create_attendance_desk_group,
            reverse_code=remove_attendance_desk_group,
        ),
    ]
