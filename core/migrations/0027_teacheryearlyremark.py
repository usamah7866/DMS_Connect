from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_create_attendance_desk_group"),
    ]

    operations = [
        migrations.CreateModel(
            name="TeacherYearlyRemark",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("class_name", models.CharField(max_length=20)),
                ("subject", models.CharField(max_length=50)),
                ("academic_year", models.PositiveIntegerField(default=2026)),
                ("behavior_marks", models.PositiveSmallIntegerField(default=0)),
                ("participation_marks", models.PositiveSmallIntegerField(default=0)),
                ("remarks", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("student", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="yearly_remarks", to="core.student")),
                ("teacher", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="yearly_remarks", to="core.teacher")),
            ],
            options={
                "ordering": ["-academic_year", "student__roll_number", "student__name", "subject"],
            },
        ),
        migrations.AddConstraint(
            model_name="teacheryearlyremark",
            constraint=models.UniqueConstraint(fields=("teacher", "student", "class_name", "subject", "academic_year"), name="unique_teacher_yearly_remark_per_student_subject_year"),
        ),
    ]
