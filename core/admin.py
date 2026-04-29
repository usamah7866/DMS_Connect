import calendar
from datetime import date

from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group, User
from django.forms.models import BaseInlineFormSet
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.http import HttpResponseRedirect
from django.utils import timezone

from .models import (
    Attendance,
    AttendanceRecord,
    AttendanceStatus,
    ClassSubject,
    Homework,
    Notification,
    SchoolClass,
    SchoolClassSubject,
    Student,
    StudentFee,
    Subject,
    Teacher,
    TeacherAttendance,
    TimetableEntry,
)


MONTH_CHOICES = [
    (3, "March"),
    (4, "April"),
    (5, "May"),
    (6, "June"),
    (7, "July"),
    (8, "August"),
    (9, "September"),
    (10, "October"),
    (11, "November"),
    (12, "December"),
    (1, "January"),
    (2, "February"),
]


class RequiredNameUserCreationForm(UserCreationForm):
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name")


class RequiredNameUserChangeForm(UserChangeForm):
    first_name = forms.CharField(required=True)
    last_name = forms.CharField(required=True)

    class Meta(UserChangeForm.Meta):
        model = User
        fields = "__all__"


class CustomUserAdmin(UserAdmin):
    add_form = RequiredNameUserCreationForm
    form = RequiredNameUserChangeForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "first_name", "last_name", "password1", "password2"),
            },
        ),
    )
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name", "email")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    list_display = ("username", "first_name", "last_name", "is_staff")


class StudentAdminForm(forms.ModelForm):
    user_account = forms.ModelChoiceField(
        queryset=User.objects.order_by("username"),
        label="User account",
    )
    class_name = forms.ChoiceField(label="Class")

    class Meta:
        model = Student
        fields = ("user_account", "class_name", "roll_number", "monthly_fee")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        class_choices = [(school_class.name, school_class.name) for school_class in SchoolClass.objects.all()]
        self.fields["class_name"].choices = class_choices
        if self.instance.pk:
            self.fields["user_account"].initial = self.instance.user_account
            self.fields["class_name"].initial = self.instance.class_name

    def save(self, commit=True):
        self.instance.user_account = self.cleaned_data["user_account"]
        self.instance.class_name = self.cleaned_data["class_name"]
        return super().save(commit=commit)


class StudentFeeInline(admin.TabularInline):
    model = StudentFee
    extra = 0
    fields = ("year", "month", "amount", "due_date", "status", "paid_date", "receipt_number", "remarks")
    ordering = ("-year", "-month")


class StudentFeeAdminForm(forms.ModelForm):
    month = forms.ChoiceField(choices=MONTH_CHOICES)

    class Meta:
        model = StudentFee
        fields = "__all__"


class RequiredSchoolClassSubjectInlineFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        active_forms = [
            form
            for form in self.forms
            if form.cleaned_data and not form.cleaned_data.get("DELETE", False)
        ]
        if not active_forms:
            raise forms.ValidationError("Add at least one subject for this class.")


class SchoolClassSubjectInline(admin.TabularInline):
    model = SchoolClassSubject
    extra = 1
    min_num = 1
    formset = RequiredSchoolClassSubjectInlineFormSet


class ClassSubjectAdminForm(forms.ModelForm):
    class_name = forms.ChoiceField(label="Class name")
    subject = forms.ChoiceField(label="Subject")

    class Meta:
        model = ClassSubject
        fields = ("teacher", "class_name", "subject")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        class_names = [school_class.name for school_class in SchoolClass.objects.all()]
        self.fields["class_name"].choices = [(name, name) for name in class_names]
        selected_class_name = (
            self.data.get("class_name")
            or getattr(self.instance, "class_name", None)
            or (class_names[0] if class_names else None)
        )
        allowed_subjects = SchoolClassSubject.objects.filter(
            school_class__name=selected_class_name
        ).select_related("subject")
        if allowed_subjects.exists():
            self.fields["subject"].choices = [
                (item.subject.name, item.subject.name) for item in allowed_subjects
            ]
        else:
            self.fields["subject"].choices = [
                (subject.name, subject.name) for subject in Subject.objects.all()
            ]
        if self.instance.pk:
            self.fields["class_name"].initial = self.instance.class_name
            self.fields["subject"].initial = self.instance.subject


class TimetableEntryAdminForm(forms.ModelForm):
    class_name = forms.ChoiceField(label="Class")
    subject = forms.ChoiceField(label="Subject")
    lecture_number = forms.ChoiceField(
        choices=[(lecture, f"Lecture {lecture}") for lecture in range(1, 8)],
        label="Lecture",
    )

    class Meta:
        model = TimetableEntry
        fields = ("class_name", "day", "lecture_number", "subject")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        class_names = [school_class.name for school_class in SchoolClass.objects.all()]
        self.fields["class_name"].choices = [(name, name) for name in class_names]
        selected_class_name = (
            self.data.get("class_name")
            or getattr(self.instance, "class_name", None)
            or (class_names[0] if class_names else None)
        )
        allowed_subjects = SchoolClassSubject.objects.filter(
            school_class__name=selected_class_name
        ).select_related("subject")
        if allowed_subjects.exists():
            self.fields["subject"].choices = [
                (item.subject.name, item.subject.name) for item in allowed_subjects
            ]
        else:
            self.fields["subject"].choices = [
                (subject.name, subject.name) for subject in Subject.objects.all()
            ]
        if self.instance.pk:
            self.fields["class_name"].initial = self.instance.class_name
            self.fields["subject"].initial = self.instance.subject
            self.fields["lecture_number"].initial = self.instance.lecture_number


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    form = StudentAdminForm
    list_display = ("name", "class_name", "roll_number", "monthly_fee", "user_account")
    search_fields = ("name", "class_name", "roll_number", "user_account__username")
    inlines = [StudentFeeInline]


@admin.register(StudentFee)
class StudentFeeAdmin(admin.ModelAdmin):
    form = StudentFeeAdminForm
    list_display = (
        "student",
        "year",
        "month_name",
        "amount",
        "status",
        "paid_date",
        "receipt_number",
        "session_months",
    )
    list_filter = ("year", "month", "status", "student__class_name")
    search_fields = ("student__name", "student__user_account__username", "receipt_number")
    list_editable = ("status", "paid_date", "receipt_number")

    @admin.display(description="Month")
    def month_name(self, obj):
        return dict(MONTH_CHOICES).get(obj.month, obj.month)

    @admin.display(description="Open Any Month")
    def session_months(self, obj):
        month_records = obj.student.fees.order_by("year", "month")
        if not month_records.exists():
            return "-"

        pills = []
        for fee in month_records:
            month_label = dict(MONTH_CHOICES).get(fee.month, str(fee.month))[:3]
            css_class = "dms-fee-month-link is-current" if fee.pk == obj.pk else "dms-fee-month-link"
            pills.append(
                (
                    reverse("admin:core_studentfee_change", args=[fee.pk]),
                    css_class,
                    month_label,
                )
            )

        return format_html(
            '<div class="dms-fee-month-links">{}</div>',
            format_html_join(
                "",
                '<a class="{}" href="{}">{}</a>',
                ((css_class, url, label) for url, css_class, label in pills),
            ),
        )

    def changelist_view(self, request, extra_context=None):
        if "month__exact" not in request.GET:
            today = timezone.localdate()
            query = request.GET.copy()
            query["month__exact"] = str(today.month)
            if today.month >= 3:
                query["year__exact"] = str(today.year)
            else:
                query["year__exact"] = str(today.year)
            return HttpResponseRedirect(f"{request.path}?{query.urlencode()}")
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("user", "qualification")
    search_fields = ("user__username", "user__first_name", "user__last_name")


@admin.register(TeacherAttendance)
class TeacherAttendanceAdmin(admin.ModelAdmin):
    change_list_template = "admin/core/teacherattendance/change_list.html"
    list_display = ("teacher", "date", "status", "remarks")
    list_filter = ("date", "status")
    search_fields = ("teacher__user__username", "teacher__user__first_name", "teacher__user__last_name")
    list_editable = ("status", "remarks")
    date_hierarchy = "date"

    def changelist_view(self, request, extra_context=None):
        today = timezone.localdate()

        selected_year = int(request.GET.get("year", request.POST.get("year", today.year)))
        selected_month = int(request.GET.get("month", request.POST.get("month", today.month)))
        max_days = calendar.monthrange(selected_year, selected_month)[1]
        selected_day = int(request.GET.get("day", request.POST.get("day", min(today.day, max_days))))
        selected_day = min(max(selected_day, 1), max_days)
        selected_date = date(selected_year, selected_month, selected_day)

        teachers = Teacher.objects.select_related("user").order_by("user__first_name", "user__last_name", "user__username")

        if request.method == "POST" and "_save_attendance" in request.POST:
            for teacher in teachers:
                status = request.POST.get(f"status_{teacher.pk}", AttendanceStatus.PRESENT)
                remarks = request.POST.get(f"remarks_{teacher.pk}", "").strip()
                TeacherAttendance.objects.update_or_create(
                    teacher=teacher,
                    date=selected_date,
                    defaults={
                        "status": status,
                        "remarks": remarks,
                    },
                )
            messages.success(
                request,
                f"Teacher attendance saved for {selected_date.strftime('%d %B %Y')}.",
            )
            return HttpResponseRedirect(
                f"{request.path}?year={selected_year}&month={selected_month}&day={selected_day}"
            )

        existing_records = {
            record.teacher_id: record
            for record in TeacherAttendance.objects.filter(
                teacher__in=teachers,
                date=selected_date,
            )
        }

        teacher_rows = []
        for teacher in teachers:
            record = existing_records.get(teacher.pk)
            full_name = teacher.user.get_full_name().strip() or teacher.user.username
            teacher_rows.append(
                {
                    "teacher": teacher,
                    "teacher_name": full_name,
                    "status": record.status if record else AttendanceStatus.PRESENT,
                    "remarks": record.remarks if record else "",
                }
            )

        calendar_weeks = []
        month_calendar = calendar.Calendar(firstweekday=0).monthdayscalendar(selected_year, selected_month)
        for week in month_calendar:
            week_days = []
            for day_number in week:
                week_days.append(
                    {
                        "number": day_number,
                        "is_blank": day_number == 0,
                        "is_selected": day_number == selected_day,
                        "url": (
                            f"{request.path}?year={selected_year}&month={selected_month}&day={day_number}"
                            if day_number
                            else ""
                        ),
                    }
                )
            calendar_weeks.append(week_days)

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Teacher attendance",
            "selected_date": selected_date,
            "selected_year": selected_year,
            "selected_month": selected_month,
            "selected_day": selected_day,
            "month_name": calendar.month_name[selected_month],
            "month_choices": [(month, calendar.month_name[month]) for month in range(1, 13)],
            "day_choices": list(range(1, max_days + 1)),
            "status_choices": [
                (AttendanceStatus.PRESENT, "Present"),
                (AttendanceStatus.ABSENT, "Absent"),
            ],
            "teacher_rows": teacher_rows,
            "calendar_weeks": calendar_weeks,
            "weekday_labels": list(calendar.day_abbr),
        }
        if extra_context:
            context.update(extra_context)
        return super().changelist_view(request, extra_context=context)


@admin.register(ClassSubject)
class ClassSubjectAdmin(admin.ModelAdmin):
    form = ClassSubjectAdminForm
    list_display = ("teacher", "class_name", "subject")
    list_filter = ("class_name", "subject")


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    inlines = [SchoolClassSubjectInline]


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ("class_name", "subject", "date", "teacher")
    list_filter = ("class_name", "subject", "date")


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("class_name", "subject", "date", "teacher")
    list_filter = ("class_name", "subject", "date")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("attendance", "student", "status")
    list_filter = ("status",)


@admin.register(TimetableEntry)
class TimetableEntryAdmin(admin.ModelAdmin):
    form = TimetableEntryAdminForm
    list_display = ("class_name", "day", "lecture_number", "subject")
    list_filter = ("class_name", "day")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "audience", "is_active", "created_at")
    list_filter = ("audience", "is_active", "created_at")
    search_fields = ("title", "message")


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.unregister(Group)
