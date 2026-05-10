import calendar
from datetime import date
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django import forms
from django.contrib import admin
from django.contrib import messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import Group, User
from django.db import models
from django.db.models import Q
from django.forms.models import BaseInlineFormSet
from django.urls import path
from django.urls import reverse
from django.utils.html import format_html, format_html_join
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils import timezone

from .views import _pdf_image, _pdf_line, _pdf_rect, _pdf_text, _styled_pdf_response
from .models import (
    Attendance,
    AttendanceRecord,
    AttendanceStatus,
    Campus,
    ClassSubject,
    FeeStatus,
    Homework,
    Notification,
    NotificationAudience,
    NotificationRead,
    SchoolTimingSettings,
    SchoolClass,
    SchoolClassSubject,
    Student,
    StudentFee,
    Subject,
    Teacher,
    TeacherAttendance,
    TeacherAttendanceStatus,
    TimetableEntry,
    Weekday,
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
    campus = forms.ChoiceField(label="Campus", choices=Campus.choices)
    father_name = forms.CharField(label="Father name", required=True)
    date_of_birth = forms.DateField(
        label="Date of birth",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    id_card_valid_until = forms.DateField(
        label="ID card valid until",
        required=True,
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    student_photo = forms.FileField(label="Student photo", required=False)

    class Meta:
        model = Student
        fields = (
            "user_account",
            "father_name",
            "campus",
            "class_name",
            "roll_number",
            "monthly_fee",
            "date_of_birth",
            "id_card_valid_until",
            "student_photo",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        class_choices = [(school_class.name, school_class.name) for school_class in SchoolClass.objects.all()]
        self.fields["class_name"].choices = class_choices
        if self.instance.pk:
            self.fields["user_account"].initial = self.instance.user_account
            self.fields["class_name"].initial = self.instance.class_name
            self.fields["campus"].initial = self.instance.campus
            self.fields["date_of_birth"].initial = self.instance.date_of_birth
            self.fields["id_card_valid_until"].initial = self.instance.id_card_valid_until
        self.fields["student_photo"].required = not bool(
            self.instance.pk and self.instance.student_photo
        )

    def save(self, commit=True):
        self.instance.user_account = self.cleaned_data["user_account"]
        self.instance.class_name = self.cleaned_data["class_name"]
        self.instance.campus = self.cleaned_data["campus"]
        return super().save(commit=commit)


class StudentFeeInline(admin.TabularInline):
    model = StudentFee
    extra = 0
    fields = ("year", "month", "amount", "paid_amount", "due_date", "status", "paid_date", "receipt_number", "remarks")
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


class SchoolTimingSettingsForm(forms.ModelForm):
    class Meta:
        model = SchoolTimingSettings
        fields = ("title", "school_start_time", "school_end_time", "late_after_time", "leave_before_time")
        widgets = {
            "school_start_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "school_end_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "late_after_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
            "leave_before_time": forms.TimeInput(format="%H:%M", attrs={"type": "time"}),
        }


class NotificationAdminForm(forms.ModelForm):
    select_all_classes = forms.BooleanField(
        required=False,
        label="Select all classes",
    )
    target_classes = forms.ModelMultipleChoiceField(
        queryset=SchoolClass.objects.order_by("name"),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Classes",
        help_text="Select one or more classes for class-wise notifications.",
    )

    class Meta:
        model = Notification
        fields = "__all__"

    class Media:
        js = ("admin/notification_admin.js",)

    def clean(self):
        cleaned_data = super().clean()
        audience = cleaned_data.get("audience")
        target_classes = cleaned_data.get("target_classes")
        if audience == NotificationAudience.CLASS_WISE and not target_classes:
            self.add_error("target_classes", "Select at least one class for a class-wise notification.")
        return cleaned_data


def _teacher_day_status(entry_time, exit_time, late_after_time, leave_before_time):
    if not entry_time and not exit_time:
        return "Absent"
    if exit_time and exit_time < leave_before_time:
        return "Leave"
    if entry_time and entry_time > late_after_time:
        return "Late"
    return "Present"


def _staff_attendance_month_label(month_value):
    if not month_value:
        return "All months"
    try:
        year_text, month_text = month_value.split("-")
        month_number = int(month_text)
        year_number = int(year_text)
        return f"{calendar.month_name[month_number]} {year_number}"
    except (TypeError, ValueError, IndexError):
        return month_value


def _staff_attendance_filters_and_rows(teacher_query, month_value):
    timing_settings = SchoolTimingSettings.get_solo()
    records = TeacherAttendance.objects.select_related("teacher__user").order_by(
        "-date",
        "teacher__user__first_name",
        "teacher__user__last_name",
        "teacher__user__username",
    )

    if teacher_query:
        records = records.filter(
            Q(teacher__user__first_name__icontains=teacher_query)
            | Q(teacher__user__last_name__icontains=teacher_query)
            | Q(teacher__user__username__icontains=teacher_query)
        )

    if month_value:
        try:
            year_text, month_text = month_value.split("-")
            records = records.filter(date__year=int(year_text), date__month=int(month_text))
        except ValueError:
            pass

    record_rows = []
    for record in records:
        record_rows.append(
            {
                "teacher_name": record.teacher.user.get_full_name().strip() or record.teacher.user.username,
                "date": record.date,
                "status": _teacher_day_status(
                    record.entry_time,
                    record.exit_time,
                    timing_settings.late_after_time,
                    timing_settings.leave_before_time,
                ),
                "entry_time": record.entry_time,
                "exit_time": record.exit_time,
                "remarks": record.remarks,
            }
        )
    return timing_settings, record_rows


def _staff_attendance_records_pdf(record_rows, teacher_query, month_value):
    timing_settings = SchoolTimingSettings.get_solo()
    if month_value:
        try:
            year_text, month_text = month_value.split("-")
            selected_year = int(year_text)
            selected_month = int(month_text)
        except ValueError:
            today = timezone.localdate()
            selected_year = today.year
            selected_month = today.month
    else:
        today = timezone.localdate()
        selected_year = today.year
        selected_month = today.month

    days_in_month = calendar.monthrange(selected_year, selected_month)[1]
    teachers = Teacher.objects.select_related("user").order_by(
        "user__first_name",
        "user__last_name",
        "user__username",
    )
    if teacher_query:
        teachers = teachers.filter(
            Q(user__first_name__icontains=teacher_query)
            | Q(user__last_name__icontains=teacher_query)
            | Q(user__username__icontains=teacher_query)
        )

    teacher_list = list(teachers)
    month_records = TeacherAttendance.objects.select_related("teacher__user").filter(
        teacher__in=teacher_list,
        date__year=selected_year,
        date__month=selected_month,
    )
    attendance_lookup = {(record.teacher_id, record.date): record for record in month_records}

    page_width = 842
    page_height = 595
    logo_path = Path(settings.BASE_DIR) / "core" / "static" / "core" / "images" / "logo.png"
    page_commands = []

    def cell_status(record_date, teacher_id):
        record = attendance_lookup.get((teacher_id, record_date))
        if not record:
            if record_date > timezone.localdate():
                return "Unmarked"
            return "Absent"
        return _teacher_day_status(
            record.entry_time,
            record.exit_time,
            timing_settings.late_after_time,
            timing_settings.leave_before_time,
        )

    def add_page_header(page_index, teacher_names):
        commands = [
            _pdf_rect(28, 28, page_width - 56, page_height - 56, stroke_color=(0.83, 0.88, 0.95), line_width=1.2),
            _pdf_rect(28, page_height - 82, page_width - 56, 54, fill_color=(0.10, 0.22, 0.44)),
            _pdf_text(94, page_height - 58, "Decent Model School", size=21, font="F2", color=(1, 1, 1)),
            _pdf_text(94, page_height - 74, "Staff Attendance Records", size=10, font="F1", color=(0.82, 0.90, 1.0)),
            _pdf_text(
                page_width - 120,
                page_height - 58,
                f"Page {page_index + 1}",
                size=10,
                font="F1",
                color=(1, 1, 1),
            ),
            _pdf_image("Im1", 40, page_height - 73, 38, 38),
            _pdf_text(40, page_height - 108, f"Teacher filter: {teacher_query or 'All teachers'}", size=10, font="F2", color=(0.09, 0.20, 0.38)),
            _pdf_text(40, page_height - 124, f"Month: {_staff_attendance_month_label(month_value)}", size=10, font="F2", color=(0.09, 0.20, 0.38)),
            _pdf_text(40, page_height - 140, f"Teachers on this page: {', '.join(teacher_names) or '-'}", size=10, font="F2", color=(0.09, 0.20, 0.38)),
            _pdf_text(40, page_height - 156, f"Saved records matched: {len(record_rows)}", size=10, font="F2", color=(0.09, 0.20, 0.38)),
            _pdf_line(40, page_height - 166, page_width - 40, page_height - 166, color=(0.74, 0.80, 0.89), line_width=1),
        ]
        return commands

    def build_table_header(y, teacher_chunk):
        day_col_width = 88
        teacher_col_width = (page_width - 80 - day_col_width) / max(len(teacher_chunk), 1)
        commands = [
            _pdf_rect(40, y - 18, page_width - 80, 24, fill_color=(0.91, 0.95, 1.0)),
            _pdf_text(48, y - 2, "Date", size=10, font="F2", color=(0.10, 0.22, 0.44)),
        ]
        start_x = 40 + day_col_width
        for index, teacher in enumerate(teacher_chunk):
            name = teacher.user.get_full_name().strip() or teacher.user.username
            if len(name) > 16:
                name = name[:13] + "..."
            commands.append(_pdf_text(start_x + 6 + index * teacher_col_width, y - 2, name, size=9, font="F2", color=(0.10, 0.22, 0.44)))
        return commands

    teacher_chunks = [teacher_list[index : index + 5] for index in range(0, len(teacher_list), 5)] or [[]]

    if not teacher_list:
        commands = add_page_header(0, [])
        commands.extend(
            [
                _pdf_rect(40, 330, page_width - 80, 90, fill_color=(0.97, 0.98, 1.0), stroke_color=(0.86, 0.90, 0.96), line_width=1),
                _pdf_text(60, 384, "No staff attendance records match the selected filters.", size=14, font="F2", color=(0.12, 0.23, 0.42)),
                _pdf_text(60, 360, "Try a different teacher name or month and export again.", size=11, font="F1", color=(0.35, 0.43, 0.55)),
            ]
        )
        page_commands.append("\n".join(commands))
    else:
        for page_index, teacher_chunk in enumerate(teacher_chunks):
            teacher_names = [
                teacher.user.get_full_name().strip() or teacher.user.username
                for teacher in teacher_chunk
            ]
            commands = add_page_header(page_index, teacher_names)
            table_top = page_height - 192
            commands.extend(build_table_header(table_top, teacher_chunk))
            row_y = table_top - 22
            day_col_width = 88
            teacher_col_width = (page_width - 80 - day_col_width) / max(len(teacher_chunk), 1)
            for day_number in range(1, days_in_month + 1):
                record_date = date(selected_year, selected_month, day_number)
                fill = (1, 1, 1) if day_number % 2 == 1 else (0.98, 0.99, 1.0)
                commands.append(_pdf_rect(40, row_y - 10, page_width - 80, 18, fill_color=fill, stroke_color=(0.87, 0.91, 0.95)))
                commands.append(
                    _pdf_text(
                        48,
                        row_y - 1,
                        record_date.strftime("%d %a"),
                        size=8.5,
                        font="F2",
                        color=(0.17, 0.19, 0.24),
                    )
                )
                for col_index, teacher in enumerate(teacher_chunk):
                    status = cell_status(record_date, teacher.pk)
                    color = {
                        "Present": (0.11, 0.53, 0.27),
                        "Late": (0.75, 0.43, 0.06),
                        "Leave": (0.68, 0.20, 0.08),
                        "Absent": (0.66, 0.10, 0.10),
                        "Unmarked": (0.35, 0.43, 0.55),
                    }.get(status, (0.20, 0.25, 0.35))
                    text = status if len(status) <= 9 else status[:9]
                    commands.append(
                        _pdf_text(
                            40 + day_col_width + 6 + col_index * teacher_col_width,
                            row_y - 1,
                            text,
                            size=8.2,
                            font="F2",
                            color=color,
                        )
                    )
                row_y -= 18
            page_commands.append("\n".join(commands))

    filename = f"staff-attendance-{timezone.localdate().isoformat()}.pdf"
    return _styled_pdf_response(page_commands, filename, logo_path=logo_path if logo_path.exists() else None)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    form = StudentAdminForm
    list_display = (
        "name",
        "father_name",
        "campus",
        "class_name",
        "roll_number",
        "monthly_fee",
        "user_account",
    )
    search_fields = (
        "name",
        "father_name",
        "campus",
        "class_name",
        "roll_number",
        "user_account__username",
    )


@admin.register(StudentFee)
class StudentFeeAdmin(admin.ModelAdmin):
    change_list_template = "admin/core/studentfee/change_list.html"
    form = StudentFeeAdminForm
    list_display = (
        "student",
        "year",
        "month_name",
        "amount",
        "paid_amount",
        "balance_display",
        "status",
        "paid_date",
        "receipt_number",
        "session_months",
    )
    list_filter = ()
    search_fields = ("student__name", "student__father_name", "student__user_account__username", "receipt_number")
    list_editable = ("amount", "paid_amount", "paid_date", "receipt_number")

    @admin.display(description="Month")
    def month_name(self, obj):
        return dict(MONTH_CHOICES).get(obj.month, obj.month)

    @admin.display(description="Balance")
    def balance_display(self, obj):
        return obj.balance_amount

    @admin.display(description="Open Any Month")
    def session_months(self, obj):
        month_records = obj.student.fees.order_by("year", "month")
        if not month_records.exists():
            return "-"
        options = []
        for fee in month_records:
            month_label = dict(MONTH_CHOICES).get(fee.month, str(fee.month))
            if fee.year != obj.year:
                month_label = f"{month_label} {fee.year}"
            options.append(
                (
                    reverse("admin:core_studentfee_change", args=[fee.pk]),
                    fee.pk == obj.pk,
                    month_label,
                )
            )

        return format_html(
            '<select class="dms-fee-month-select" onchange="if(this.value){{window.location.href=this.value;}}">'
            '<option value="">Select month</option>{}</select>',
            format_html_join(
                "",
                '<option value="{}"{}>{}</option>',
                (
                    (
                        url,
                        format_html(' selected="selected"') if is_selected else "",
                        label,
                    )
                    for url, is_selected, label in options
                ),
            ),
        )

    def changelist_view(self, request, extra_context=None):
        fee_filters = {
            "class_name": request.GET.get("class_name", ""),
            "student_name": request.GET.get("student_name", ""),
            "father_name": request.GET.get("father_name", ""),
            "roll_number": request.GET.get("roll_number", ""),
            "status_filter": request.GET.get("status_filter", ""),
        }
        request.fee_filters = fee_filters
        filtered_query = request.GET.copy()
        for key in fee_filters:
            filtered_query.pop(key, None)
        request.GET = filtered_query
        extra_context = extra_context or {}
        extra_context.update(
            {
                "class_filter_value": fee_filters["class_name"],
                "student_name_value": fee_filters["student_name"],
                "father_name_value": fee_filters["father_name"],
                "roll_number_value": fee_filters["roll_number"],
                "status_filter_value": fee_filters["status_filter"],
                "class_options": SchoolClass.objects.order_by("name"),
                "has_fee_search": self._has_fee_search(request),
            }
        )
        return super().changelist_view(request, extra_context=extra_context)

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related("student", "student__user_account")
        if not self._has_fee_search(request):
            return queryset.none()

        fee_filters = getattr(request, "fee_filters", {})
        student_name = fee_filters.get("student_name", "").strip()
        father_name = fee_filters.get("father_name", "").strip()
        class_name = fee_filters.get("class_name", "").strip()
        roll_number = fee_filters.get("roll_number", "").strip()
        status_filter = fee_filters.get("status_filter", "").strip()

        if student_name:
            queryset = queryset.filter(student__name__icontains=student_name)
        if father_name:
            queryset = queryset.filter(student__father_name__icontains=father_name)
        if class_name:
            queryset = queryset.filter(student__class_name=class_name)
        if roll_number:
            queryset = queryset.filter(student__roll_number=roll_number)
        if status_filter in {FeeStatus.UNPAID, FeeStatus.PARTIAL, FeeStatus.PAID}:
            queryset = queryset.filter(status=status_filter)

        today = timezone.localdate()
        session_start_year = today.year if today.month >= 3 else today.year - 1
        current_month_year = session_start_year if today.month >= 3 else session_start_year + 1
        queryset = queryset.filter(month=today.month, year=current_month_year)
        return queryset

    def _has_fee_search(self, request):
        fee_filters = getattr(request, "fee_filters", None)
        if fee_filters is not None:
            return any(
                value.strip()
                for key, value in fee_filters.items()
                if key != "status_filter"
            ) or fee_filters.get("status_filter", "").strip() in {FeeStatus.UNPAID, FeeStatus.PARTIAL, FeeStatus.PAID}
        return any(
            request.GET.get(key, "").strip()
            for key in ("student_name", "father_name", "class_name", "roll_number", "status_filter")
        )

    def lookup_allowed(self, lookup, value, request=None):
        if lookup in {"student_name", "father_name", "class_name", "roll_number"}:
            return True
        return super().lookup_allowed(lookup, value, request)


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
        now_time = timezone.localtime().time().replace(second=0, microsecond=0)

        selected_year = int(request.GET.get("year", request.POST.get("year", today.year)))
        selected_month = int(request.GET.get("month", request.POST.get("month", today.month)))
        max_days = calendar.monthrange(selected_year, selected_month)[1]
        selected_day = int(request.GET.get("day", request.POST.get("day", min(today.day, max_days))))
        selected_day = min(max(selected_day, 1), max_days)
        selected_date = date(selected_year, selected_month, selected_day)
        if selected_month == 1:
            previous_month_year = selected_year - 1
            previous_month = 12
        else:
            previous_month_year = selected_year
            previous_month = selected_month - 1
        if selected_month == 12:
            next_month_year = selected_year + 1
            next_month = 1
        else:
            next_month_year = selected_year
            next_month = selected_month + 1

        teachers = Teacher.objects.select_related("user").order_by("user__first_name", "user__last_name", "user__username")

        if request.method == "POST":
            teacher_id = request.POST.get("teacher_id")
            action_name = request.POST.get("attendance_action")
            target_teacher = teachers.filter(pk=teacher_id).first()
            if target_teacher and action_name in {"mark_entry", "mark_exit"}:
                attendance_record, _ = TeacherAttendance.objects.get_or_create(
                    teacher=target_teacher,
                    date=selected_date,
                    defaults={"status": TeacherAttendanceStatus.PRESENT},
                )
                if action_name == "mark_entry":
                    if attendance_record.entry_time:
                        messages.info(
                            request,
                            f"Entry time is already marked for {target_teacher.user.get_full_name() or target_teacher.user.username}.",
                        )
                    else:
                        attendance_record.entry_time = now_time
                        attendance_record.status = TeacherAttendanceStatus.PRESENT
                        attendance_record.save()
                        messages.success(
                            request,
                            f"Entry time marked for {target_teacher.user.get_full_name() or target_teacher.user.username}.",
                        )
                elif action_name == "mark_exit":
                    if not attendance_record.entry_time:
                        messages.error(
                            request,
                            f"Mark entry first for {target_teacher.user.get_full_name() or target_teacher.user.username}.",
                        )
                    elif attendance_record.exit_time:
                        messages.info(
                            request,
                            f"Exit time is already marked for {target_teacher.user.get_full_name() or target_teacher.user.username}.",
                        )
                    else:
                        attendance_record.exit_time = now_time
                        attendance_record.status = TeacherAttendanceStatus.PRESENT
                        attendance_record.save()
                        messages.success(
                            request,
                            f"Exit time marked for {target_teacher.user.get_full_name() or target_teacher.user.username}.",
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
                    "entry_time": record.entry_time.strftime("%H:%M") if record and record.entry_time else "",
                    "exit_time": record.exit_time.strftime("%H:%M") if record and record.exit_time else "",
                    "can_mark_entry": not bool(record and record.entry_time),
                    "can_mark_exit": bool(record and record.entry_time and not record.exit_time),
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
            "teacher_rows": teacher_rows,
            "calendar_weeks": calendar_weeks,
            "weekday_labels": list(calendar.day_abbr),
            "previous_month_url": f"{request.path}?year={previous_month_year}&month={previous_month}&day=1",
            "next_month_url": f"{request.path}?year={next_month_year}&month={next_month}&day=1",
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
    change_list_template = "admin/core/timetableentry/change_list.html"
    form = TimetableEntryAdminForm
    list_display = ("class_name", "day", "lecture_number", "subject")
    list_filter = ()

    def changelist_view(self, request, extra_context=None):
        selected_class = request.GET.get("class_name", "").strip()
        class_options = SchoolClass.objects.order_by("name")
        weekdays = [
            Weekday.MONDAY,
            Weekday.TUESDAY,
            Weekday.WEDNESDAY,
            Weekday.THURSDAY,
            Weekday.FRIDAY,
            Weekday.SATURDAY,
        ]
        lecture_numbers = list(range(1, 8))

        timetable_rows = []
        selected_entries = TimetableEntry.objects.none()
        if selected_class:
            selected_entries = TimetableEntry.objects.filter(class_name=selected_class).order_by(
                "day", "lecture_number"
            )
            timetable_lookup = {
                (entry.day, entry.lecture_number): entry for entry in selected_entries
            }
            for day in weekdays:
                lectures = []
                for lecture_number in lecture_numbers:
                    entry = timetable_lookup.get((day, lecture_number))
                    add_url = (
                        f"{reverse('admin:core_timetableentry_add')}"
                        f"?class_name={selected_class}&day={day}&lecture_number={lecture_number}"
                    )
                    lectures.append(
                        {
                            "subject": entry.subject if entry else "-",
                            "change_url": reverse("admin:core_timetableentry_change", args=[entry.pk]) if entry else "",
                            "add_url": add_url,
                            "has_entry": bool(entry),
                        }
                    )
                timetable_rows.append({"day": day, "lectures": lectures})

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Timetable",
            "selected_class": selected_class,
            "class_options": class_options,
            "lecture_numbers": lecture_numbers,
            "timetable_rows": timetable_rows,
            "selected_entries_count": selected_entries.count(),
            "clear_url": reverse("admin:core_timetableentry_changelist"),
            "add_url": reverse("admin:core_timetableentry_add"),
        }
        if extra_context:
            context.update(extra_context)
        return TemplateResponse(
            request,
            self.change_list_template,
            context,
        )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    form = NotificationAdminForm
    list_display = ("title", "audience", "target_classes_summary", "is_active", "created_at")
    list_filter = ("audience", "is_active", "created_at")
    search_fields = ("title", "message")
    filter_horizontal = ()

    @admin.display(description="Classes")
    def target_classes_summary(self, obj):
        if obj.audience != NotificationAudience.CLASS_WISE:
            return "-"
        class_names = list(obj.target_classes.order_by("name").values_list("name", flat=True))
        return ", ".join(class_names) if class_names else "-"


def save_school_timing_view(request):
    settings_obj = SchoolTimingSettings.get_solo()
    if request.method == "POST":
        form = SchoolTimingSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "School timing updated successfully.")
        else:
            messages.error(request, "Please correct the school timing fields and save again.")
    return HttpResponseRedirect(reverse("admin:index"))


def staff_attendance_records_view(request):
    teacher_query = request.GET.get("teacher_name", "").strip()
    month_value = request.GET.get("month", "").strip()
    _, record_rows = _staff_attendance_filters_and_rows(teacher_query, month_value)

    if request.GET.get("export") == "pdf":
        return _staff_attendance_records_pdf(record_rows, teacher_query, month_value)

    export_query = request.GET.copy()
    export_query["export"] = "pdf"

    context = {
        **admin.site.each_context(request),
        "title": "Staff Attendance Records",
        "teacher_query": teacher_query,
        "month_value": month_value,
        "record_rows": record_rows,
        "staff_records_clear_url": reverse("admin:staff_attendance_records"),
        "staff_records_export_url": f"{reverse('admin:staff_attendance_records')}?{export_query.urlencode()}",
    }
    return TemplateResponse(
        request,
        "admin/staff_attendance_records.html",
        context,
    )


_original_admin_get_urls = admin.site.get_urls


def _dms_admin_get_urls():
    custom_urls = [
        path(
            "school-timings/save/",
            admin.site.admin_view(save_school_timing_view),
            name="save_school_timings",
        ),
        path(
            "staff-attendance-records/",
            admin.site.admin_view(staff_attendance_records_view),
            name="staff_attendance_records",
        ),
    ]
    return custom_urls + _original_admin_get_urls()


admin.site.get_urls = _dms_admin_get_urls

_original_admin_each_context = admin.site.each_context


def _dms_admin_each_context(request):
    context = _original_admin_each_context(request)
    settings_obj = SchoolTimingSettings.get_solo()
    today = timezone.localdate()
    current_month_year = today.year
    if today.month in (1, 2):
        current_month_year = today.year
    student_count = Student.objects.count()
    teacher_count = Teacher.objects.count()
    todays_teacher_attendance = TeacherAttendance.objects.filter(
        date=today,
        entry_time__isnull=False,
    ).count()
    unpaid_fees_this_month = StudentFee.objects.filter(
        month=today.month,
        year=current_month_year,
        paid_amount__lt=models.F("amount"),
    ).count()
    student_user_ids = list(Student.objects.values_list("user_account_id", flat=True).distinct())
    teacher_user_ids = list(Teacher.objects.values_list("user_id", flat=True).distinct())
    unread_notification_total = 0
    active_notifications = Notification.objects.filter(is_active=True)
    for notification in active_notifications:
        if notification.audience == NotificationAudience.STUDENTS:
            target_count = len(student_user_ids)
        elif notification.audience == NotificationAudience.STAFF:
            target_count = len(teacher_user_ids)
        elif notification.audience == NotificationAudience.CLASS_WISE:
            target_count = Student.objects.filter(
                class_name__in=notification.target_classes.values_list("name", flat=True)
            ).values("user_account_id").distinct().count()
        else:
            target_count = len(set(student_user_ids + teacher_user_ids))
        read_count = NotificationRead.objects.filter(notification=notification).count()
        unread_notification_total += max(target_count - read_count, 0)
    context.update(
        {
            "school_timing_settings": settings_obj,
            "school_timing_form": SchoolTimingSettingsForm(instance=settings_obj),
            "school_timing_save_url": reverse("admin:save_school_timings"),
            "staff_attendance_records_url": reverse("admin:staff_attendance_records"),
            "dashboard_widgets": {
                "student_count": student_count,
                "teacher_count": teacher_count,
                "todays_teacher_attendance": todays_teacher_attendance,
                "unpaid_fees_this_month": unpaid_fees_this_month,
                "unread_notifications": unread_notification_total,
            },
        }
    )
    return context


admin.site.each_context = _dms_admin_each_context


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.unregister(TeacherAttendance)
admin.site.unregister(Group)
