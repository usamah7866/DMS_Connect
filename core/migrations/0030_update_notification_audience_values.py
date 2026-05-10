from django.db import migrations


def update_notification_audiences(apps, schema_editor):
    Notification = apps.get_model("core", "Notification")
    Notification.objects.filter(audience="both").update(audience="all")
    Notification.objects.filter(audience="teachers").update(audience="staff")


def reverse_notification_audiences(apps, schema_editor):
    Notification = apps.get_model("core", "Notification")
    Notification.objects.filter(audience="all").update(audience="both")
    Notification.objects.filter(audience="staff").update(audience="teachers")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0029_notification_target_classes_and_more"),
    ]

    operations = [
        migrations.RunPython(
            update_notification_audiences,
            reverse_notification_audiences,
        ),
    ]
