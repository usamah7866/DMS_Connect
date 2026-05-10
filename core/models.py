from datetime import date, time
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class AttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LATE = "late", "Late"


class TeacherAttendanceStatus(models.TextChoices):
    PRESENT = "present", "Present"
    ABSENT = "absent", "Absent"
    LEAVE = "leave", "Leave"


class DiaryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    DONE = "done", "Done"
    NOT_DONE = "not_done", "Not Done"


class Weekday(models.TextChoices):
    MONDAY = "Monday", "Monday"
    TUESDAY = "Tuesday", "Tuesday"
    WEDNESDAY = "Wednesday", "Wednesday"
    THURSDAY = "Thursday", "Thursday"
    FRIDAY = "Friday", "Friday"
    SATURDAY = "Saturday", "Saturday"


class NotificationAudience(models.TextChoices):
    ALL = "all", "All"
    STUDENTS = "students", "Students"
    STAFF = "staff", "Staff"
    CLASS_WISE = "classwise", "Class Wise"


class FeeStatus(models.TextChoices):
    UNPAID = "unpaid", "Unpaid"
    PARTIAL = "partial", "Partial"
    PAID = "paid", "Paid"


class Campus(models.TextChoices):
    GIRLS = "Girls Campus", "Girls Campus"
    KIDS = "Kids Campus", "Kids Campus"
    RUSTAM = "Rustam Park Campus", "Rustam Park Campus"


class SchoolTimingSettings(models.Model):
    title = models.CharField(max_length=80, default="Current School Timing")
    school_start_time = models.TimeField(default=time(7, 0))
    school_end_time = models.TimeField(default=time(13, 30))
    late_after_time = models.TimeField(default=time(7, 15))
    leave_before_time = models.TimeField(default=time(13, 0))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "School Timing"
        verbose_name_plural = "School Timings"

    def __str__(self):
        return self.title

    @classmethod
    def get_solo(cls):
        defaults = {
            "title": "Current School Timing",
            "school_start_time": time(7, 0),
            "school_end_time": time(13, 30),
            "late_after_time": time(7, 15),
            "leave_before_time": time(13, 0),
        }
        return cls.objects.get_or_create(pk=1, defaults=defaults)[0]


class SchoolClass(models.Model):
    name = models.CharField(max_length=20, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Class"
        verbose_name_plural = "Classes"

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField(max_length=50, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class SchoolClassSubject(models.Model):
    school_class = models.ForeignKey(
        SchoolClass,
        on_delete=models.CASCADE,
        related_name="class_subjects",
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)

    class Meta:
        ordering = ["school_class__name", "subject__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school_class", "subject"],
                name="unique_subject_per_school_class",
            )
        ]

    def __str__(self):
        return f"{self.school_class.name} - {self.subject.name}"


def student_id_photo_upload_path(instance, filename):
    safe_roll = str(instance.roll_number or "no-roll")
    safe_name = (instance.name or instance.user_account.username).lower().replace(" ", "-")
    return f"student-id-cards/{instance.class_name}/{safe_roll}-{safe_name}/{filename}"


# Student Model
class Student(models.Model):
    name = models.CharField(max_length=100)
    father_name = models.CharField(max_length=100, blank=True)
    class_name = models.CharField(max_length=20)
    roll_number = models.IntegerField()
    monthly_fee = models.DecimalField(max_digits=10, decimal_places=2)
    campus = models.CharField(max_length=30, choices=Campus.choices, default=Campus.GIRLS)
    date_of_birth = models.DateField(null=True, blank=True)
    id_card_valid_until = models.DateField(null=True, blank=True)
    student_photo = models.FileField(
        upload_to=student_id_photo_upload_path,
        null=True,
        blank=True,
    )
    user_account = models.ForeignKey(User, on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        full_name = self.user_account.get_full_name().strip()
        if full_name:
            self.name = full_name
        elif not self.name:
            self.name = self.user_account.username
        super().save(*args, **kwargs)
        self.ensure_fee_records()

    def __str__(self):
        return self.name

    def ensure_fee_records(self, year=None):
        today = timezone.now().date()
        session_start_year = year or (today.year if today.month >= 3 else today.year - 1)
        session_slots = (
            [(session_start_year, month) for month in range(3, 13)]
            + [(session_start_year + 1, month) for month in (1, 2, 3)]
        )
        for record_year, month in session_slots:
            StudentFee.objects.get_or_create(
                student=self,
                year=record_year,
                month=month,
                defaults={
                    "amount": self.monthly_fee,
                    "due_date": date(record_year, month, 7),
                },
            )

# Teacher Model
class Teacher(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    qualification = models.CharField(max_length=100, blank=True)

    def __str__(self):
        return self.user.username


class TeacherAttendance(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="attendance_records")
    date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=10,
        choices=TeacherAttendanceStatus.choices,
        default=TeacherAttendanceStatus.PRESENT,
    )
    entry_time = models.TimeField(blank=True, null=True)
    exit_time = models.TimeField(blank=True, null=True)
    remarks = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-date", "teacher__user__first_name", "teacher__user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "date"],
                name="unique_teacher_attendance_per_day",
            )
        ]

    def __str__(self):
        return f"{self.teacher.user.get_full_name() or self.teacher.user.username} - {self.date}"


class TeacherYearlyRemark(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="yearly_remarks")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="yearly_remarks")
    class_name = models.CharField(max_length=20)
    subject = models.CharField(max_length=50)
    academic_year = models.PositiveIntegerField(default=timezone.localdate().year)
    behavior_marks = models.PositiveSmallIntegerField(default=0)
    participation_marks = models.PositiveSmallIntegerField(default=0)
    remarks = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "-academic_year",
            "student__roll_number",
            "student__name",
            "subject",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "student", "class_name", "subject", "academic_year"],
                name="unique_teacher_yearly_remark_per_student_subject_year",
            )
        ]

    def __str__(self):
        return (
            f"{self.student.name} - {self.subject} - {self.academic_year}"
        )

class ClassSubject(models.Model):
    teacher = models.ForeignKey('Teacher', on_delete=models.CASCADE)
    class_name = models.CharField(max_length=20)
    subject = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.class_name} - {self.subject}"

# Homework Model (Digital Diary)
class Homework(models.Model):
    class_name = models.CharField(max_length=20)
    subject = models.CharField(max_length=50)
    description = models.TextField()
    date = models.DateField(auto_now_add=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.class_name} - {self.subject}"


class HomeworkFeedback(models.Model):
    homework = models.ForeignKey(Homework, on_delete=models.CASCADE, related_name="feedbacks")
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=10,
        choices=DiaryStatus.choices,
        default=DiaryStatus.PENDING,
    )
    message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    teacher_read = models.BooleanField(default=False)
    teacher_read_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ["student__roll_number", "student__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["homework", "student"],
                name="unique_homework_feedback_per_student",
            )
        ]

    def __str__(self):
        return f"{self.student.name} - {self.homework}"


class TimetableEntry(models.Model):
    class_name = models.CharField(max_length=20)
    day = models.CharField(max_length=10, choices=Weekday.choices)
    lecture_number = models.PositiveSmallIntegerField()
    subject = models.CharField(max_length=50)

    class Meta:
        ordering = ["class_name", "day", "lecture_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["class_name", "day", "lecture_number"],
                name="unique_timetable_slot_per_class",
            )
        ]

    def __str__(self):
        return f"{self.class_name} - {self.day} - Lecture {self.lecture_number}"


class Notification(models.Model):
    title = models.CharField(max_length=150)
    message = models.TextField()
    audience = models.CharField(
        max_length=12,
        choices=NotificationAudience.choices,
        default=NotificationAudience.ALL,
    )
    target_classes = models.ManyToManyField(
        SchoolClass,
        blank=True,
        related_name="notifications",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class NotificationRead(models.Model):
    notification = models.ForeignKey(
        Notification, on_delete=models.CASCADE, related_name="reads"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-read_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["notification", "user"],
                name="unique_notification_read_per_user",
            )
        ]

    def __str__(self):
        return f"{self.user.username} read {self.notification.title}"


class StudentFee(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="fees")
    year = models.PositiveIntegerField()
    month = models.PositiveSmallIntegerField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    due_date = models.DateField()
    status = models.CharField(
        max_length=10,
        choices=FeeStatus.choices,
        default=FeeStatus.UNPAID,
    )
    paid_date = models.DateField(blank=True, null=True)
    receipt_number = models.CharField(max_length=50, blank=True)
    remarks = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "year", "month"],
                name="unique_fee_record_per_student_month",
            )
        ]

    def __str__(self):
        return f"{self.student.name} - {self.month}/{self.year}"

    @property
    def balance_amount(self):
        return max(Decimal("0.00"), self.amount - self.paid_amount)

    def save(self, *args, **kwargs):
        self.amount = self.amount or Decimal("0.00")
        self.paid_amount = self.paid_amount or Decimal("0.00")
        if self.paid_amount < 0:
            self.paid_amount = Decimal("0.00")
        if self.paid_amount > self.amount:
            self.paid_amount = self.amount

        if self.paid_amount <= 0:
            self.status = FeeStatus.UNPAID
        elif self.paid_amount < self.amount:
            self.status = FeeStatus.PARTIAL
        else:
            self.status = FeeStatus.PAID

        super().save(*args, **kwargs)


class Attendance(models.Model):
    class_name = models.CharField(max_length=20)
    subject = models.CharField(max_length=50)
    date = models.DateField()
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "class_name", "subject"]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "class_name", "subject", "date"],
                name="unique_attendance_per_class_subject_date",
            )
        ]

    def __str__(self):
        return f"{self.class_name} - {self.subject} ({self.date})"


class AttendanceRecord(models.Model):
    attendance = models.ForeignKey(
        Attendance, on_delete=models.CASCADE, related_name="records"
    )
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=10,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.PRESENT,
    )

    class Meta:
        ordering = ["student__roll_number", "student__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["attendance", "student"],
                name="unique_student_attendance_record",
            )
        ]

    def __str__(self):
        return f"{self.student.name} - {self.get_status_display()}"


class Exam(models.Model):
    class_name = models.CharField(max_length=20)
    subject = models.CharField(max_length=50)
    title = models.CharField(max_length=100)
    exam_date = models.DateField()
    total_marks = models.PositiveIntegerField()
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-exam_date", "-created_at"]

    def __str__(self):
        return f"{self.title} - {self.class_name} - {self.subject}"


class ExamResult(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="results")
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        ordering = ["student__roll_number", "student__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["exam", "student"],
                name="unique_exam_result_per_student",
            )
        ]

    def __str__(self):
        return f"{self.student.name} - {self.exam.title}"


def admission_upload_path(instance, filename):
    safe_campus = instance.campus.lower().replace(" ", "-")
    return f"admissions/{safe_campus}/{instance.student_name}/{filename}"


class AdmissionApplication(models.Model):
    campus = models.CharField(max_length=30, choices=Campus.choices)
    class_applying_for = models.CharField(max_length=30)
    student_name = models.CharField(max_length=120)
    gender = models.CharField(max_length=10)
    date_of_birth = models.DateField()
    b_form_number = models.CharField(max_length=30, blank=True)
    previous_school = models.CharField(max_length=120, blank=True)
    religion = models.CharField(max_length=50, blank=True)
    guardian_name = models.CharField(max_length=120)
    father_education = models.CharField(max_length=120, blank=True)
    office_phone_no = models.CharField(max_length=30, blank=True)
    relationship = models.CharField(max_length=40)
    cnic_number = models.CharField(max_length=30)
    occupation = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30)
    landline_no = models.CharField(max_length=30, blank=True)
    mother_cell_no = models.CharField(max_length=30, blank=True)
    whatsapp = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    emergency_contact = models.CharField(max_length=30, blank=True)
    medium = models.CharField(max_length=20, blank=True)
    academic_group = models.CharField(max_length=80, blank=True)
    selected_subjects = models.CharField(max_length=200, blank=True)
    address = models.TextField()
    city = models.CharField(max_length=80)
    message = models.TextField(blank=True)
    transport_required = models.CharField(max_length=10, blank=True)
    student_photo = models.FileField(upload_to=admission_upload_path, blank=True)
    birth_certificate = models.FileField(upload_to=admission_upload_path, blank=True)
    guardian_cnic = models.FileField(upload_to=admission_upload_path, blank=True)
    previous_result = models.FileField(upload_to=admission_upload_path, blank=True)
    transfer_certificate = models.FileField(upload_to=admission_upload_path, blank=True)
    additional_document = models.FileField(upload_to=admission_upload_path, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    email_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.student_name} - {self.campus}"


def career_upload_path(instance, filename):
    safe_campus = instance.campus.lower().replace(" ", "-")
    safe_name = instance.full_name.lower().replace(" ", "-")
    return f"careers/{safe_campus}/{safe_name}/{filename}"


class CareerApplication(models.Model):
    campus = models.CharField(max_length=30, choices=Campus.choices)
    full_name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=30)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    cnic_number = models.CharField(max_length=30, blank=True)
    religion = models.CharField(max_length=20, blank=True)
    position_applied_for = models.CharField(max_length=120)
    highest_qualification = models.CharField(max_length=120)
    years_of_experience = models.CharField(max_length=30, blank=True)
    organization_name = models.CharField(max_length=120, blank=True)
    job_post_name = models.CharField(max_length=120, blank=True)
    cover_letter = models.TextField(blank=True)
    cv_file = models.FileField(upload_to=career_upload_path)
    submitted_at = models.DateTimeField(auto_now_add=True)
    email_sent = models.BooleanField(default=False)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.full_name} - {self.campus}"
