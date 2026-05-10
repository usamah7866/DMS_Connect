import calendar
from collections import OrderedDict
from datetime import date
from pathlib import Path
import struct
import zlib
from django.utils import timezone

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Q
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.conf import settings

import requests

from .forms import AdmissionApplicationForm, CareerApplicationForm
from .models import (
    AdmissionApplication,
    Attendance,
    AttendanceRecord,
    AttendanceStatus,
    Campus,
    CareerApplication,
    ClassSubject,
    DiaryStatus,
    Exam,
    ExamResult,
    FeeStatus,
    Homework,
    HomeworkFeedback,
    Notification,
    NotificationAudience,
    NotificationRead,
    SchoolClassSubject,
    SchoolTimingSettings,
    Student,
    StudentFee,
    Teacher,
    TeacherAttendance,
    TeacherYearlyRemark,
    TimetableEntry,
    Weekday,
)


BASE_DIR = Path(__file__).resolve().parent.parent
ADMISSION_EMAILS = {
    Campus.GIRLS: "dmchool0077@gmail.com",
    Campus.KIDS: "dmchool0077@gmail.com",
    Campus.RUSTAM: "dmchool0077@gmail.com",
}
CAREER_EMAIL = "dmchool0077@gmail.com"
ATTENDANCE_DESK_GROUP = "Attendance Desk"
ID_CARD_CAMPUS_INFO = {
    Campus.GIRLS: {
        "phone": "042-37463067",
        "email": "dmchool0077@gmail.com",
        "address": "77-A, Nadeem Park, Gulshan Ravi, Lahore",
    },
    Campus.KIDS: {
        "phone": "042-37417770",
        "email": "dmchool0077@gmail.com",
        "address": "500-A, Gulshan Ravi, Lahore",
    },
    Campus.RUSTAM: {
        "phone": "042-37467772",
        "email": "dmchool0077@gmail.com",
        "address": "158, Rustam Park, Gulshan Ravi, Lahore",
    },
}


def _teacher_day_status(entry_time, exit_time, late_after_time, leave_before_time, target_date=None):
    if not entry_time and not exit_time:
        if target_date and target_date > timezone.localdate():
            return "unmarked"
        return "absent"
    if exit_time and exit_time < leave_before_time:
        return "leave"
    if entry_time and entry_time > late_after_time:
        return "late"
    return "present"


def _is_attendance_desk_user(user):
    return user.is_authenticated and user.groups.filter(name=ATTENDANCE_DESK_GROUP).exists()


def _attendance_desk_context(request, selected_date):
    timing_settings = SchoolTimingSettings.get_solo()
    teachers = Teacher.objects.select_related("user").order_by(
        "user__first_name", "user__last_name", "user__username"
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
        teacher_rows.append(
            {
                "teacher": teacher,
                "teacher_name": teacher.user.get_full_name().strip() or teacher.user.username,
                "entry_time": record.entry_time.strftime("%H:%M") if record and record.entry_time else "",
                "exit_time": record.exit_time.strftime("%H:%M") if record and record.exit_time else "",
                "can_mark_entry": not bool(record and record.entry_time),
                "can_mark_exit": bool(record and record.entry_time and not record.exit_time),
            }
        )

    month_calendar = calendar.Calendar(firstweekday=0).monthdayscalendar(
        selected_date.year, selected_date.month
    )
    calendar_weeks = []
    for week in month_calendar:
        week_days = []
        for day_number in week:
            week_days.append(
                {
                    "number": day_number,
                    "is_blank": day_number == 0,
                    "is_selected": day_number == selected_date.day,
                    "url": (
                        f"{request.path}?year={selected_date.year}&month={selected_date.month}&day={day_number}"
                        if day_number
                        else ""
                    ),
                }
            )
        calendar_weeks.append(week_days)

    if selected_date.month == 1:
        previous_month_year = selected_date.year - 1
        previous_month = 12
    else:
        previous_month_year = selected_date.year
        previous_month = selected_date.month - 1
    if selected_date.month == 12:
        next_month_year = selected_date.year + 1
        next_month = 1
    else:
        next_month_year = selected_date.year
        next_month = selected_date.month + 1

    return {
        "selected_date": selected_date,
        "month_name": calendar.month_name[selected_date.month],
        "teacher_rows": teacher_rows,
        "calendar_weeks": calendar_weeks,
        "weekday_labels": list(calendar.day_abbr),
        "previous_month_url": f"{request.path}?year={previous_month_year}&month={previous_month}&day=1",
        "next_month_url": f"{request.path}?year={next_month_year}&month={next_month}&day=1",
        "school_timing_settings": timing_settings,
    }


def _teacher_class_context(teacher, selected_class_name=None, selected_subject=None):
    class_subjects = list(
        ClassSubject.objects.filter(teacher=teacher).order_by("class_name", "subject")
    )
    selected_class = None

    if class_subjects:
        if selected_class_name and selected_subject:
            selected_class = next(
                (
                    class_subject
                    for class_subject in class_subjects
                    if class_subject.class_name == selected_class_name
                    and class_subject.subject == selected_subject
                ),
                None,
            )
        if selected_class is None:
            selected_class = class_subjects[0]

    return class_subjects, selected_class


def _notifications_for(user, student=None):
    notifications = Notification.objects.filter(is_active=True)

    if student is not None:
        notifications = notifications.filter(
            Q(audience=NotificationAudience.ALL)
            | Q(audience=NotificationAudience.STUDENTS)
            | Q(audience=NotificationAudience.CLASS_WISE, target_classes__name=student.class_name)
        )
    elif Teacher.objects.filter(user=user).exists():
        notifications = notifications.filter(
            audience__in=[NotificationAudience.ALL, NotificationAudience.STAFF]
        )
    else:
        notifications = notifications.filter(audience=NotificationAudience.ALL)

    return notifications.distinct()[:5]


def _performance_band(percentage):
    if percentage >= 85:
        return "Excellent"
    if percentage >= 70:
        return "Good"
    if percentage >= 50:
        return "Average"
    return "Needs Attention"


def _attendance_band(percentage):
    if percentage >= 85:
        return "good"
    if percentage >= 70:
        return "average"
    return "needs_attention"


def _attach_notification_state(notifications, user):
    notifications = list(notifications)
    read_ids = set(
        NotificationRead.objects.filter(
            user=user, notification__in=notifications
        ).values_list("notification_id", flat=True)
    )
    for item in notifications:
        item.is_unread = item.id not in read_ids
    return notifications


def _student_id_number(student):
    class_code = "".join(character for character in student.class_name if character.isalnum()).upper()[:6]
    return f"DMS-{class_code}-{int(student.roll_number):03d}"


def _pdf_escape(value):
    return str(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _styled_pdf_response(page_streams, filename, logo_path=None):
    image_map = {"Im1": str(logo_path)} if logo_path else None
    return _pdf_response_with_images(page_streams, filename, image_map=image_map)


def _pdf_text(x, y, text, size=10, font="F1", color=(0, 0, 0)):
    red, green, blue = color
    return (
        "BT "
        f"/{font} {size} Tf "
        f"{red:.3f} {green:.3f} {blue:.3f} rg "
        f"1 0 0 1 {x} {y} Tm "
        f"({_pdf_escape(text)}) Tj ET"
    )


def _pdf_text_centered(x_center, y, text, size=10, font="F1", color=(0, 0, 0), width_factor=0.48):
    text = str(text)
    estimated_width = len(text) * size * width_factor
    return _pdf_text(x_center - (estimated_width / 2), y, text, size=size, font=font, color=color)


def _pdf_rect(x, y, width, height, fill_color=None, stroke_color=None, line_width=1):
    commands = [f"{line_width} w"]
    if fill_color:
        red, green, blue = fill_color
        commands.append(f"{red:.3f} {green:.3f} {blue:.3f} rg")
    if stroke_color:
        red, green, blue = stroke_color
        commands.append(f"{red:.3f} {green:.3f} {blue:.3f} RG")
    commands.append(f"{x} {y} {width} {height} re")
    if fill_color and stroke_color:
        commands.append("B")
    elif fill_color:
        commands.append("f")
    else:
        commands.append("S")
    return " ".join(commands)


def _unfilter_png_scanlines(raw_data, width, height, bytes_per_pixel):
    stride = width * bytes_per_pixel
    rows = []
    position = 0

    def paeth_predictor(left, up, up_left):
        predictor = left + up - up_left
        left_distance = abs(predictor - left)
        up_distance = abs(predictor - up)
        up_left_distance = abs(predictor - up_left)
        if left_distance <= up_distance and left_distance <= up_left_distance:
            return left
        if up_distance <= up_left_distance:
            return up
        return up_left

    for _ in range(height):
        filter_type = raw_data[position]
        position += 1
        scanline = bytearray(raw_data[position : position + stride])
        position += stride
        previous = rows[-1] if rows else bytearray(stride)

        for index in range(stride):
            left = scanline[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
            up = previous[index]
            up_left = previous[index - bytes_per_pixel] if index >= bytes_per_pixel else 0

            if filter_type == 0:
                pass
            elif filter_type == 1:
                scanline[index] = (scanline[index] + left) % 256
            elif filter_type == 2:
                scanline[index] = (scanline[index] + up) % 256
            elif filter_type == 3:
                scanline[index] = (scanline[index] + ((left + up) // 2)) % 256
            elif filter_type == 4:
                scanline[index] = (scanline[index] + paeth_predictor(left, up, up_left)) % 256
            else:
                raise ValueError("Unsupported PNG filter type")

        rows.append(scanline)

    return rows


def _png_image_data(image_path):
    data = Path(image_path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Only PNG logos are supported")

    position = 8
    width = height = None
    bit_depth = color_type = None
    idat_chunks = []

    while position < len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        chunk_type = data[position + 4 : position + 8]
        chunk_data = data[position + 8 : position + 8 + length]
        position += length + 12

        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if bit_depth != 8 or color_type not in (2, 6) or compression != 0 or filter_method != 0 or interlace != 0:
                raise ValueError("Unsupported PNG format for PDF embedding")
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            break

    bytes_per_pixel = 4 if color_type == 6 else 3
    raw_scanlines = zlib.decompress(b"".join(idat_chunks))
    rows = _unfilter_png_scanlines(raw_scanlines, width, height, bytes_per_pixel)

    rgb_stream = bytearray()
    alpha_stream = bytearray()
    for row in rows:
        rgb_stream.append(0)
        if color_type == 6:
            alpha_stream.append(0)
        for index in range(0, len(row), bytes_per_pixel):
            rgb_stream.extend(row[index : index + 3])
            if color_type == 6:
                alpha_stream.append(row[index + 3])

    return {
        "width": width,
        "height": height,
        "rgb_data": zlib.compress(bytes(rgb_stream)),
        "alpha_data": zlib.compress(bytes(alpha_stream)) if color_type == 6 else None,
    }


def _jpeg_image_data(image_path):
    data = Path(image_path).read_bytes()
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("Only JPEG images are supported")

    position = 2
    width = height = None
    color_components = 3
    while position < len(data):
        if data[position] != 0xFF:
            position += 1
            continue
        marker = data[position + 1]
        position += 2
        if marker in (0xD8, 0xD9):
            continue
        if marker == 0xDA:
            break
        segment_length = struct.unpack(">H", data[position : position + 2])[0]
        segment_data = data[position + 2 : position + segment_length]
        if marker in (0xC0, 0xC1, 0xC2):
            height = struct.unpack(">H", segment_data[1:3])[0]
            width = struct.unpack(">H", segment_data[3:5])[0]
            color_components = segment_data[5]
            break
        position += segment_length

    if not width or not height:
        raise ValueError("Unsupported JPEG image")

    return {
        "width": width,
        "height": height,
        "jpeg_data": data,
        "color_space": "/DeviceGray" if color_components == 1 else "/DeviceRGB",
    }


def _pdf_image_resource(image_path):
    suffix = Path(image_path).suffix.lower()
    if suffix == ".png":
        data = _png_image_data(image_path)
        return {
            "type": "png",
            "width": data["width"],
            "height": data["height"],
            "rgb_data": data["rgb_data"],
            "alpha_data": data["alpha_data"],
        }
    if suffix in {".jpg", ".jpeg"}:
        data = _jpeg_image_data(image_path)
        return {
            "type": "jpeg",
            "width": data["width"],
            "height": data["height"],
            "jpeg_data": data["jpeg_data"],
            "color_space": data["color_space"],
        }
    raise ValueError("Unsupported image format")


def _pdf_response_with_images(page_streams, filename, image_map=None):
    page_count = len(page_streams)
    font_object_numbers = {
        "F1": 3 + page_count,
        "F2": 4 + page_count,
    }
    image_map = image_map or {}
    image_names = list(image_map.keys())
    image_resources = []
    image_object_numbers = {}
    next_object_number = 5 + page_count

    for image_name in image_names:
        resource = _pdf_image_resource(image_map[image_name])
        image_object_numbers[image_name] = next_object_number
        next_object_number += 1
        if resource["type"] == "png" and resource["alpha_data"]:
            resource["smask_object_number"] = next_object_number
            next_object_number += 1
        image_resources.append((image_name, resource))

    first_stream_object_number = next_object_number

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (
            "<< /Type /Pages /Count "
            f"{page_count} /Kids "
            + "["
            + " ".join(f"{3 + index} 0 R" for index in range(page_count))
            + "] >>"
        ).encode("ascii"),
    ]

    for index in range(page_count):
        stream_object_number = first_stream_object_number + index
        xobject_resource = ""
        if image_resources:
            xobject_resource = " /XObject << " + " ".join(
                f"/{image_name} {image_object_numbers[image_name]} 0 R"
                for image_name, _ in image_resources
            ) + " >>"
        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 {font_object_numbers['F1']} 0 R /F2 {font_object_numbers['F2']} 0 R >>{xobject_resource} >> "
                f"/Contents {stream_object_number} 0 R >>"
            ).encode("ascii")
        )

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

    for image_name, resource in image_resources:
        if resource["type"] == "png":
            image_dictionary = (
                f"<< /Type /XObject /Subtype /Image /Width {resource['width']} /Height {resource['height']} "
                "/ColorSpace /DeviceRGB /BitsPerComponent 8 "
                "/Filter /FlateDecode "
                f"/DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns {resource['width']} >> "
            )
            if resource["alpha_data"]:
                image_dictionary += f"/SMask {resource['smask_object_number']} 0 R "
            image_dictionary += f"/Length {len(resource['rgb_data'])} >>"
            objects.append(
                image_dictionary.encode("ascii")
                + b"\nstream\n"
                + resource["rgb_data"]
                + b"\nendstream"
            )
            if resource["alpha_data"]:
                smask_dictionary = (
                    f"<< /Type /XObject /Subtype /Image /Width {resource['width']} /Height {resource['height']} "
                    "/ColorSpace /DeviceGray /BitsPerComponent 8 "
                    "/Filter /FlateDecode "
                    f"/DecodeParms << /Predictor 15 /Colors 1 /BitsPerComponent 8 /Columns {resource['width']} >> "
                    f"/Length {len(resource['alpha_data'])} >>"
                )
                objects.append(
                    smask_dictionary.encode("ascii")
                    + b"\nstream\n"
                    + resource["alpha_data"]
                    + b"\nendstream"
                )
        else:
            image_dictionary = (
                f"<< /Type /XObject /Subtype /Image /Width {resource['width']} /Height {resource['height']} "
                f"/ColorSpace {resource['color_space']} /BitsPerComponent 8 "
                "/Filter /DCTDecode "
                f"/Length {len(resource['jpeg_data'])} >>"
            )
            objects.append(
                image_dictionary.encode("ascii")
                + b"\nstream\n"
                + resource["jpeg_data"]
                + b"\nendstream"
            )

    for stream_text in page_streams:
        stream_data = stream_text.encode("latin-1", errors="replace")
        objects.append(
            b"<< /Length "
            + str(len(stream_data)).encode("ascii")
            + b" >>\nstream\n"
            + stream_data
            + b"\nendstream"
        )

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{index} 0 obj\n".encode("ascii"))
        pdf.extend(body)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF"
        ).encode("ascii")
    )

    response = HttpResponse(bytes(pdf), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _pdf_polygon(points, fill_color):
    red, green, blue = fill_color
    if not points:
        return ""
    start_x, start_y = points[0]
    commands = [f"{red:.3f} {green:.3f} {blue:.3f} rg", f"{start_x} {start_y} m"]
    for x_value, y_value in points[1:]:
        commands.append(f"{x_value} {y_value} l")
    commands.append("h f")
    return " ".join(commands)


def _pdf_line(x1, y1, x2, y2, color=(0, 0, 0), line_width=1):
    red, green, blue = color
    return (
        f"{line_width} w "
        f"{red:.3f} {green:.3f} {blue:.3f} RG "
        f"{x1} {y1} m {x2} {y2} l S"
    )


def _pdf_image(name, x, y, width, height):
    return f"q {width} 0 0 {height} {x} {y} cm /{name} Do Q"


def _pdf_barcode(x, y, width, height, seed_text):
    commands = []
    encoded = "".join(str(ord(character) % 10) for character in seed_text) or "1234567890"
    bar_width = max(width / max(len(encoded) * 3, 1), 1.2)
    cursor = x
    for index, digit in enumerate(encoded):
        if index % 2 == 0:
            commands.append(_pdf_rect(cursor, y, bar_width, height, fill_color=(0.17, 0.17, 0.17)))
        cursor += bar_width
        if int(digit) % 2 == 0:
            commands.append(_pdf_rect(cursor, y, bar_width * 0.6, height * 0.86, fill_color=(0.26, 0.26, 0.26)))
        cursor += bar_width * 0.9
        if cursor >= x + width:
            break
    return " ".join(commands)


def _id_card_pdf(student):
    front_template_path = BASE_DIR / "core" / "static" / "core" / "images" / "student-id-front.png"
    back_template_path = BASE_DIR / "core" / "static" / "core" / "images" / "student-id-back.png"
    image_map = {
        "FrontTemplate": str(front_template_path),
        "BackTemplate": str(back_template_path),
    }
    if student.student_photo and Path(student.student_photo.path).exists():
        image_map["Photo"] = student.student_photo.path

    card_x = 150
    card_y = 120
    card_width = 340
    card_height = 530

    front_commands = [
        _pdf_image("FrontTemplate", card_x, card_y, card_width, card_height),
    ]
    back_commands = [
        _pdf_image("BackTemplate", card_x, card_y, card_width, card_height),
    ]

    scale_x = card_width / 290
    scale_y = card_height / 452

    photo_image_x = card_x + (101 * scale_x)
    photo_image_y = card_y + (452 - (95 + 10 + 105)) * scale_y
    photo_image_width = 100 * scale_x
    photo_image_height = 105 * scale_y

    if "Photo" in image_map:
        front_commands.append(_pdf_image("Photo", photo_image_x, photo_image_y, photo_image_width, photo_image_height))
    else:
        front_commands.append(
            _pdf_rect(
                photo_image_x,
                photo_image_y,
                photo_image_width,
                photo_image_height,
                fill_color=(0.94, 0.95, 0.97),
                stroke_color=(0.85, 0.88, 0.93),
            )
        )
        front_commands.append(
            _pdf_text_centered(
                card_x + (151 * scale_x),
                photo_image_y + (photo_image_height / 2) - 4,
                "PHOTO",
                size=9,
                font="F2",
                color=(0.48, 0.53, 0.60),
            )
        )

    student_name = student.name
    if len(student_name) > 23:
        student_name = student_name[:20] + "..."
    name_y = card_y + (452 - 240 - 18) * scale_y
    subtitle_y = name_y - (18 * scale_y)
    front_commands.append(
        _pdf_text_centered(
            card_x + (card_width / 2),
            name_y,
            student_name,
            size=15.5,
            font="F2",
            color=(0.04, 0.26, 0.37),
            width_factor=0.43,
        )
    )
    front_commands.append(
        _pdf_text_centered(
            card_x + (card_width / 2),
            subtitle_y,
            f"Class {student.class_name}",
            size=10.5,
            color=(0.04, 0.26, 0.37),
            width_factor=0.43,
        )
    )
    detail_start_y = card_y + (452 - 240 - 42) * scale_y
    detail_y = detail_start_y
    detail_rows = [
        ("Roll No", str(student.roll_number)),
        ("Campus", student.campus),
        ("Father", student.father_name),
        ("DOB", student.date_of_birth.strftime("%d/%m/%Y") if student.date_of_birth else "-"),
        ("Valid till", student.id_card_valid_until.strftime("%d/%m/%Y") if student.id_card_valid_until else "-"),
    ]
    for label, value in detail_rows:
        value_text = str(value)
        if len(value_text) > 24:
            value_text = value_text[:21] + "..."
        front_commands.append(
            _pdf_text(card_x + (35 * scale_x), detail_y, label, size=8.7, font="F2", color=(0.04, 0.26, 0.37))
        )
        front_commands.append(
            _pdf_text(card_x + (93 * scale_x), detail_y, ":", size=8.7, font="F2", color=(0.04, 0.26, 0.37))
        )
        front_commands.append(
            _pdf_text(card_x + (104 * scale_x), detail_y, value_text, size=8.7, color=(0.04, 0.26, 0.37))
        )
        detail_y -= (15 * scale_y)

    return _pdf_response_with_images(
        ["\n".join(front_commands), "\n".join(back_commands)],
        f"{student.name.replace(' ', '_').lower()}_id_card.pdf",
        image_map=image_map,
    )


def _student_fee_tracker_pdf(student, fee_records, fee_summary):
    logo_path = BASE_DIR / "core" / "static" / "core" / "images" / "logo.png"
    commands = []

    commands.append(_pdf_rect(0, 760, 595, 82, fill_color=(0.09, 0.24, 0.45)))
    commands.append("q 42 0 0 34 34 782 cm /Im1 Do Q")
    commands.append(_pdf_text(92, 812, "DECENT MODEL SCHOOL", size=20, font="F2", color=(1, 1, 1)))
    commands.append(_pdf_text(92, 794, "Student Fee Tracking Report", size=11, color=(0.93, 0.96, 1)))
    commands.append(_pdf_text(92, 779, "Affiliated with B.I.S.E | Established since 1980", size=9, color=(0.93, 0.96, 1)))

    commands.append(_pdf_rect(34, 716, 527, 34, fill_color=(0.91, 0.95, 1)))
    commands.append(_pdf_text(42, 735, f"Student Name: {student.name}", size=11, font="F2"))
    commands.append(_pdf_text(42, 720, f"Class: {student.class_name}", size=10))
    commands.append(_pdf_text(220, 720, f"Roll Number: {student.roll_number}", size=10))
    commands.append(_pdf_text(382, 720, f"Campus: {student.campus}", size=10))

    summary_y = 674
    summary_cards = [
        ("Current Month", fee_summary["current_month_name"]),
        ("Status", str(fee_summary["current_month_status"])),
        ("Monthly Fee", str(fee_summary["current_month_amount"])),
        ("Paid This Month", str(fee_summary["current_month_paid"])),
        ("Balance", str(fee_summary["current_month_balance"])),
    ]
    card_x = 34
    for label, value in summary_cards:
        commands.append(_pdf_rect(card_x, summary_y, 98, 44, fill_color=(1, 1, 1), stroke_color=(0.82, 0.87, 0.94)))
        commands.append(_pdf_text(card_x + 8, summary_y + 27, label, size=8.5, font="F2", color=(0.34, 0.41, 0.53)))
        commands.append(_pdf_text(card_x + 8, summary_y + 11, value[:16], size=10.5, color=(0.09, 0.24, 0.45)))
        card_x += 106

    note_color = (0.60, 0.11, 0.11) if fee_summary["is_fee_alert"] else (0.09, 0.24, 0.45)
    note_fill = (0.99, 0.89, 0.89) if fee_summary["is_fee_alert"] else (0.93, 0.96, 1.0)
    commands.append(_pdf_rect(34, 610, 527, 38, fill_color=note_fill, stroke_color=(0.82, 0.87, 0.94)))
    commands.append(_pdf_text(42, 632, "Submit fee before 7th of every month.", size=10.5, font="F2", color=note_color))
    if fee_summary["is_fee_alert"]:
        commands.append(_pdf_text(42, 616, "Current month fee is still unpaid.", size=10, color=note_color))

    columns = [
        ("Month", 96),
        ("Amount", 60),
        ("Paid", 60),
        ("Balance", 60),
        ("Due Date", 72),
        ("Status", 58),
        ("Paid Date", 72),
        ("Receipt", 60),
        ("Remarks", 49),
    ]
    x_positions = [34]
    for _, width in columns[:-1]:
        x_positions.append(x_positions[-1] + width)

    table_y = 574
    for index, (title, width) in enumerate(columns):
        commands.append(
            _pdf_rect(
                x_positions[index],
                table_y,
                width,
                24,
                fill_color=(0.16, 0.38, 0.63),
                stroke_color=(0.12, 0.31, 0.52),
            )
        )
        commands.append(_pdf_text(x_positions[index] + 4, table_y + 8, title, size=8.5, font="F2", color=(1, 1, 1)))

    row_y = table_y - 24
    max_rows_first_page = 18
    visible_records = fee_records[:max_rows_first_page]
    for row_index, fee in enumerate(visible_records):
        fill = (1, 1, 1) if row_index % 2 == 0 else (0.97, 0.98, 1)
        values = [
            f"{fee.month_name} {fee.year}",
            str(fee.amount),
            str(fee.paid_amount),
            str(fee.balance_amount),
            str(fee.due_date),
            fee.get_status_display(),
            str(fee.paid_date or "-"),
            fee.receipt_number or "-",
            fee.remarks or "-",
        ]
        for index, value in enumerate(values):
            width = columns[index][1]
            commands.append(
                _pdf_rect(
                    x_positions[index],
                    row_y,
                    width,
                    22,
                    fill_color=fill,
                    stroke_color=(0.87, 0.91, 0.95),
                )
            )
            commands.append(_pdf_text(x_positions[index] + 4, row_y + 7, value[:18], size=8, color=(0.12, 0.18, 0.28)))
        row_y -= 22

    if len(fee_records) > max_rows_first_page:
        commands.append(_pdf_text(34, 126, "More fee rows exist in the dashboard than fit on one PDF page.", size=9, color=(0.60, 0.11, 0.11)))

    commands.append(_pdf_text(34, 96, f"Total Paid: {fee_summary['total_paid']}", size=10.5, font="F2", color=(0.09, 0.24, 0.45)))
    commands.append(_pdf_text(204, 96, f"Total Unpaid: {fee_summary['total_unpaid']}", size=10.5, font="F2", color=(0.09, 0.24, 0.45)))
    commands.append(_pdf_text(34, 74, "This report reflects the same student fee data shown in the portal fee section.", size=9, color=(0.38, 0.45, 0.56)))

    return _styled_pdf_response(
        ["\n".join(commands)],
        f"{student.name.replace(' ', '_').lower()}_fee_tracking.pdf",
        logo_path=logo_path,
    )


def _exam_term(exam_title):
    title = exam_title.lower()
    if "mid" in title:
        return "Mid Term"
    if "final" in title:
        return "Final Term"
    return "Class Test"


def _progress_card_pdf(
    student,
    progress_cards,
    overall_percentage,
    performance_band,
    subject_result_sections,
    attendance_summary,
    configured_subjects,
):
    exam_titles = []
    for section in subject_result_sections:
        for row in section["exam_rows"]:
            if row["exam_title"] not in exam_titles:
                exam_titles.append(row["exam_title"])

    exam_titles = exam_titles[:5]
    subject_lookup = {section["subject"]: section for section in subject_result_sections}
    page_streams = []
    rows_per_page = 14
    subject_chunks = [
        configured_subjects[index : index + rows_per_page]
        for index in range(0, max(len(configured_subjects), 1), rows_per_page)
    ] or [[]]

    def term_rows(term_name):
        rows = []
        for subject_name in configured_subjects:
            section = subject_lookup.get(subject_name)
            filtered_rows = [
                row for row in (section["exam_rows"] if section else []) if row["term"] == term_name
            ]
            latest_row = filtered_rows[-1] if filtered_rows else None
            rows.append((subject_name, latest_row))
        return rows

    def build_page(chunk, page_number, total_pages):
        commands = []
        commands.append(_pdf_rect(0, 760, 595, 82, fill_color=(0.09, 0.24, 0.45)))
        commands.append("q 44 0 0 34 34 782 cm /Im1 Do Q")
        commands.append(_pdf_text(96, 812, "DECENT MODEL SCHOOL", size=20, font="F2", color=(1, 1, 1)))
        commands.append(_pdf_text(96, 794, "Affiliated with B.I.S.E", size=10, color=(0.93, 0.96, 1)))
        commands.append(_pdf_text(96, 780, "Established since 1980", size=10, color=(0.93, 0.96, 1)))
        commands.append(_pdf_text(430, 812, "ANNUAL", size=11, font="F2", color=(1, 1, 1)))
        commands.append(_pdf_text(414, 796, "PROGRESS REPORT", size=11, font="F2", color=(1, 1, 1)))

        commands.append(_pdf_rect(34, 716, 527, 34, fill_color=(0.91, 0.95, 1)))
        commands.append(_pdf_text(42, 736, f"Student Name: {student.name}", size=11, font="F2"))
        commands.append(_pdf_text(42, 721, f"Class: {student.class_name}", size=10))
        commands.append(_pdf_text(220, 721, f"Roll Number: {student.roll_number}", size=10))
        commands.append(_pdf_text(390, 721, f"Attendance: {progress_cards['session']['attendance_percentage']}%", size=10))

        commands.append(_pdf_rect(34, 684, 527, 22, fill_color=(0.16, 0.38, 0.63)))
        commands.append(_pdf_text(42, 691, "Overall Academic Record", size=11, font="F2", color=(1, 1, 1)))

        x_positions = [34, 148]
        for _ in exam_titles:
            x_positions.append(x_positions[-1] + 66)
        x_positions.extend([x_positions[-1] + 66, x_positions[-1] + 122])
        col_widths = [114] + [66] * len(exam_titles) + [66, 56]
        y = 656

        header_titles = ["Subject"] + exam_titles + ["Total", "Avg %"]
        for index, title in enumerate(header_titles):
            commands.append(
                _pdf_rect(
                    x_positions[index],
                    y,
                    col_widths[index],
                    24,
                    fill_color=(0.84, 0.90, 0.98),
                    stroke_color=(0.74, 0.82, 0.93),
                )
            )
            commands.append(_pdf_text(x_positions[index] + 4, y + 8, title[:10], size=9, font="F2"))

        y -= 24
        for row_index, subject_name in enumerate(chunk):
            section = subject_lookup.get(subject_name)
            fill = (1, 1, 1) if row_index % 2 == 0 else (0.97, 0.98, 1)
            row_values = [subject_name[:18]]
            for exam_title in exam_titles:
                matching_row = next(
                    (
                        exam_row
                        for exam_row in (section["exam_rows"] if section else [])
                        if exam_row["exam_title"] == exam_title
                    ),
                    None,
                )
                row_values.append(
                    f"{matching_row['student_marks']}/{matching_row['total_marks']}"
                    if matching_row
                    else "-"
                )
            if section:
                row_values.append(f"{section['obtained']}/{section['total']}")
                row_values.append(f"{section['percentage']}%")
            else:
                row_values.extend(["-", "-"])

            for index, value in enumerate(row_values):
                commands.append(
                    _pdf_rect(
                        x_positions[index],
                        y,
                        col_widths[index],
                        24,
                        fill_color=fill,
                        stroke_color=(0.86, 0.89, 0.94),
                    )
                )
                commands.append(_pdf_text(x_positions[index] + 4, y + 8, str(value)[:16], size=8.5))
            y -= 24

        commands.append(_pdf_rect(34, 250, 255, 22, fill_color=(0.16, 0.38, 0.63)))
        commands.append(_pdf_text(42, 257, "Mid Term Summary", size=11, font="F2", color=(1, 1, 1)))
        commands.append(_pdf_rect(306, 250, 255, 22, fill_color=(0.90, 0.19, 0.16)))
        commands.append(_pdf_text(314, 257, "Final Term Summary", size=11, font="F2", color=(1, 1, 1)))

        left_y = 226
        for subject_name, row in term_rows("Mid Term")[:8]:
            commands.append(_pdf_text(42, left_y, f"{subject_name[:18]}", size=8.5, font="F2"))
            commands.append(
                _pdf_text(
                    150,
                    left_y,
                    f"{row['student_marks']}/{row['total_marks']} ({row['student_percentage']}%)" if row else "-",
                    size=8.5,
                )
            )
            left_y -= 16

        right_y = 226
        for subject_name, row in term_rows("Final Term")[:8]:
            commands.append(_pdf_text(314, right_y, f"{subject_name[:18]}", size=8.5, font="F2"))
            commands.append(
                _pdf_text(
                    422,
                    right_y,
                    f"{row['student_marks']}/{row['total_marks']} ({row['student_percentage']}%)" if row else "-",
                    size=8.5,
                )
            )
            right_y -= 16

        commands.append(_pdf_rect(34, 84, 527, 52, fill_color=(0.95, 0.97, 1), stroke_color=(0.84, 0.89, 0.94)))
        commands.append(_pdf_text(42, 116, f"Overall Percentage: {overall_percentage}%", size=11, font="F2"))
        commands.append(_pdf_text(220, 116, f"Performance Band: {performance_band}", size=11, font="F2"))
        commands.append(_pdf_text(42, 98, f"Present: {attendance_summary['present']}  Absent: {attendance_summary['absent']}  Late: {attendance_summary['late']}", size=9.5))
        commands.append(_pdf_text(420, 42, f"Page {page_number} of {total_pages}", size=8, color=(0.45, 0.51, 0.60)))
        return "\n".join(commands)

    total_pages = len(subject_chunks)
    for page_number, chunk in enumerate(subject_chunks, start=1):
        page_streams.append(build_page(chunk, page_number, total_pages))

    filename = f"progress-card-{student.class_name}-{student.roll_number}.pdf"
    logo_path = BASE_DIR / "core" / "static" / "core" / "images" / "logo.png"
    return _styled_pdf_response(page_streams, filename, logo_path=logo_path)


def _month_name(month_number):
    return date(2000, month_number, 1).strftime("%B")


def _current_fee_session(today):
    session_start_year = today.year if today.month >= 3 else today.year - 1
    session_slots = (
        [(session_start_year, month) for month in range(3, 13)]
        + [(session_start_year + 1, month) for month in (1, 2, 3)]
    )
    return session_start_year, session_slots


def login_view(request):
    if request.method == "POST":
        captcha_response = request.POST.get("g-recaptcha-response")
        secret_key = "6LenYZ4sAAAAABDYLJq9kq4DzTX4xk4jQ5Up2lvD"

        response = requests.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={"secret": secret_key, "response": captcha_response},
        )
        result = response.json()

        if not result["success"]:
            return render(request, "login.html", {"error": "Invalid CAPTCHA"})

        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            if _is_attendance_desk_user(user):
                return redirect("attendance_desk")
            if user.is_superuser or user.is_staff:
                return redirect("/admin/")
            if Teacher.objects.filter(user=user).exists():
                return redirect("teacher_dashboard")
            if Student.objects.filter(user_account=user).exists():
                return redirect("student_dashboard")
            logout(request)
            return render(
                request,
                "login.html",
                {"error": "This account is not linked to a teacher or student profile yet."},
            )

        return render(request, "login.html", {"error": "Invalid username or password."})

    return render(request, "login.html")


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def attendance_desk(request):
    if not _is_attendance_desk_user(request.user):
        if request.user.is_superuser or request.user.is_staff:
            return redirect("/admin/")
        if Teacher.objects.filter(user=request.user).exists():
            return redirect("teacher_dashboard")
        if Student.objects.filter(user_account=request.user).exists():
            return redirect("student_dashboard")
        return redirect("login")

    today = timezone.localdate()
    selected_year = int(request.GET.get("year", request.POST.get("year", today.year)))
    selected_month = int(request.GET.get("month", request.POST.get("month", today.month)))
    max_days = calendar.monthrange(selected_year, selected_month)[1]
    selected_day = int(request.GET.get("day", request.POST.get("day", min(today.day, max_days))))
    selected_day = min(max(selected_day, 1), max_days)
    selected_date = date(selected_year, selected_month, selected_day)
    now_time = timezone.localtime().time().replace(second=0, microsecond=0)

    if request.method == "POST":
        teacher_id = request.POST.get("teacher_id")
        action_name = request.POST.get("attendance_action")
        target_teacher = Teacher.objects.select_related("user").filter(pk=teacher_id).first()
        if target_teacher and action_name in {"mark_entry", "mark_exit"}:
            attendance_record, _ = TeacherAttendance.objects.get_or_create(
                teacher=target_teacher,
                date=selected_date,
                defaults={"status": "present"},
            )
            teacher_name = target_teacher.user.get_full_name() or target_teacher.user.username
            if action_name == "mark_entry":
                if attendance_record.entry_time:
                    messages.info(request, f"Entry time is already marked for {teacher_name}.")
                else:
                    attendance_record.entry_time = now_time
                    attendance_record.status = "present"
                    attendance_record.save()
                    messages.success(request, f"Entry time marked for {teacher_name}.")
            else:
                if not attendance_record.entry_time:
                    messages.error(request, f"Mark entry first for {teacher_name}.")
                elif attendance_record.exit_time:
                    messages.info(request, f"Exit time is already marked for {teacher_name}.")
                else:
                    attendance_record.exit_time = now_time
                    attendance_record.status = "present"
                    attendance_record.save()
                    messages.success(request, f"Exit time marked for {teacher_name}.")
        return redirect(
            f"{reverse('attendance_desk')}?year={selected_year}&month={selected_month}&day={selected_day}"
        )

    context = _attendance_desk_context(request, selected_date)
    return render(request, "attendance_desk.html", context)


def admissions_view(request):
    form = AdmissionApplicationForm(request.POST or None, request.FILES or None)
    selected_campus = request.POST.get("campus") or request.GET.get("campus") or Campus.GIRLS
    target_email = ADMISSION_EMAILS.get(selected_campus, "dmchool0077@gmail.com")
    email_status = ""

    if request.method == "POST" and form.is_valid():
        application = form.save()
        target_email = ADMISSION_EMAILS.get(application.campus, "dmchool0077@gmail.com")
        email_body = "\n".join(
            [
                "New admission application received.",
                "",
                f"Campus: {application.campus}",
                f"Class Applying For: {application.class_applying_for}",
                f"Student Name: {application.student_name}",
                f"Gender: {application.gender}",
                f"Date of Birth: {application.date_of_birth}",
                  f"B-Form Number: {application.b_form_number or '-'}",
                  f"Previous School: {application.previous_school or '-'}",
                  f"Religion: {application.religion or '-'}",
                  f"Father's Name: {application.guardian_name}",
                  f"Father's Education: {application.father_education or '-'}",
                  f"Office Phone No.: {application.office_phone_no or '-'}",
                  f"Relationship: {application.relationship}",
                  f"CNIC Number: {application.cnic_number}",
                  f"Occupation: {application.occupation or '-'}",
                  f"Father's Cell No.: {application.phone}",
                  f"Mother's Cell No.: {application.mother_cell_no or '-'}",
                  f"Land Line No.: {application.landline_no or '-'}",
                  f"WhatsApp: {application.whatsapp or '-'}",
                  f"Email: {application.email or '-'}",
                  f"Emergency Contact: {application.emergency_contact or '-'}",
                  f"Medium: {application.medium or '-'}",
                  f"Group: {application.academic_group or '-'}",
                  f"Subjects: {application.selected_subjects or '-'}",
                  f"City: {application.city}",
                  f"Transport Required: {application.transport_required or '-'}",
                "",
                "Address:",
                application.address,
                "",
                "Parent Note:",
                application.message or "-",
            ]
        )

        try:
            if not settings.EMAIL_HOST:
                raise RuntimeError("SMTP not configured")
            email = EmailMessage(
                subject=f"New Admission Application - {application.student_name} ({application.campus})",
                body=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[target_email],
            )
            for field_name in [
                "student_photo",
                "birth_certificate",
                "guardian_cnic",
                "previous_result",
                "transfer_certificate",
                "additional_document",
            ]:
                file_field = getattr(application, field_name)
                if file_field:
                    email.attach_file(file_field.path)
            email.send(fail_silently=False)
            application.email_sent = True
            application.save(update_fields=["email_sent"])
            email_status = f"Application submitted successfully and emailed to {target_email}."
        except Exception:
            email_status = (
                f"Application saved successfully. Email delivery to {target_email} "
                "is pending until SMTP settings are configured."
            )

        request.session["admission_status"] = email_status
        return redirect("admission_thank_you")

    return render(
        request,
        "admissions.html",
        {
            "form": form,
            "selected_campus": selected_campus,
            "target_email": target_email,
        },
    )


def admission_thank_you_view(request):
    admission_status = request.session.pop("admission_status", "")
    return render(
        request,
        "admission_thank_you.html",
        {"admission_status": admission_status},
    )


def careers_view(request):
    form = CareerApplicationForm(request.POST or None, request.FILES or None)
    selected_campus = request.POST.get("campus") or request.GET.get("campus") or Campus.GIRLS

    if request.method == "POST" and form.is_valid():
        application = form.save()
        email_body = "\n".join(
            [
                "New career application received.",
                "",
                 f"Campus Applied For: {application.campus}",
                 f"Full Name: {application.full_name}",
                 f"Email: {application.email}",
                 f"Phone: {application.phone}",
                  f"Date of Birth: {application.date_of_birth or '-'}",
                  f"Address: {application.address or '-'}",
                  f"CNIC Number: {application.cnic_number or '-'}",
                  f"Religion: {application.religion or '-'}",
                  f"Position Applied For: {application.position_applied_for}",
                  f"Highest Qualification: {application.highest_qualification}",
                  f"Organization Name: {application.organization_name or '-'}",
                  f"Job Post Name: {application.job_post_name or '-'}",
                  f"Years of Experience: {application.years_of_experience or '-'}",
                  "",
                  "Cover Letter:",
                  application.cover_letter or "-",
            ]
        )

        try:
            if not settings.EMAIL_HOST:
                raise RuntimeError("SMTP not configured")
            email = EmailMessage(
                subject=f"New Career Application - {application.full_name} ({application.campus})",
                body=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[CAREER_EMAIL],
            )
            if application.cv_file:
                email.attach_file(application.cv_file.path)
            email.send(fail_silently=False)
            application.email_sent = True
            application.save(update_fields=["email_sent"])
            request.session["career_status"] = (
                f"Career application submitted successfully and emailed to {CAREER_EMAIL}."
            )
        except Exception:
            request.session["career_status"] = (
                f"Career application saved successfully. Email delivery to {CAREER_EMAIL} "
                "is pending until SMTP settings are configured."
            )

        return redirect("career_thank_you")

    return render(
        request,
        "careers.html",
        {
            "form": form,
            "selected_campus": selected_campus,
            "career_email": CAREER_EMAIL,
        },
    )


def career_thank_you_view(request):
    career_status = request.session.pop("career_status", "")
    return render(
        request,
        "career_thank_you.html",
        {"career_status": career_status},
    )


@login_required
def teacher_dashboard(request):
    if _is_attendance_desk_user(request.user):
        return redirect("attendance_desk")
    teacher = Teacher.objects.get(user=request.user)
    selected_class_name = request.GET.get("class_name")
    selected_subject = request.GET.get("subject")
    panel = request.GET.get("panel", "students")
    selected_exam_id = request.GET.get("exam")
    attendance_date_query = request.GET.get("attendance_date")
    today_local = timezone.localdate()
    selected_teacher_year = int(request.GET.get("teacher_year", today_local.year))
    selected_teacher_month = int(request.GET.get("teacher_month", today_local.month))
    selected_remark_year = int(request.GET.get("remark_year", today_local.year))
    class_subjects, selected_class = _teacher_class_context(
        teacher, selected_class_name, selected_subject
    )

    if request.method == "POST":
        action = request.POST.get("action")
        selected_class_name = request.POST.get("class_name")
        selected_subject = request.POST.get("subject")
        panel = request.POST.get("panel", "students")
        selected_exam_id = request.POST.get("exam_id") or request.POST.get("exam")
        attendance_date_query = request.POST.get("attendance_date")
        selected_teacher_year = int(request.POST.get("teacher_year", selected_teacher_year))
        selected_teacher_month = int(request.POST.get("teacher_month", selected_teacher_month))
        class_subjects, selected_class = _teacher_class_context(
            teacher, selected_class_name, selected_subject
        )

        if panel != "teacher_attendance" and selected_class is None:
            messages.error(request, "Assign at least one class and subject to this teacher.")
            return redirect("teacher_dashboard")

        if selected_class is not None:
            selected_class_name = selected_class.class_name
            selected_subject = selected_class.subject

        if action == "add_homework":
            description = request.POST.get("description", "").strip()
            if description:
                Homework.objects.create(
                    class_name=selected_class_name,
                    subject=selected_subject,
                    description=description,
                    teacher=teacher,
                )
                messages.success(request, "Digital diary entry added successfully.")
            else:
                messages.error(request, "Digital diary note cannot be empty.")

        elif action == "save_attendance":
            attendance_date = request.POST.get("attendance_date")
            if not attendance_date:
                messages.error(request, "Please choose an attendance date.")
            else:
                attendance, _ = Attendance.objects.get_or_create(
                    teacher=teacher,
                    class_name=selected_class_name,
                    subject=selected_subject,
                    date=attendance_date,
                )
                students = Student.objects.filter(class_name=selected_class_name)
                for student in students:
                    status = request.POST.get(
                        f"attendance_{student.id}", AttendanceStatus.PRESENT
                    )
                    AttendanceRecord.objects.update_or_create(
                        attendance=attendance,
                        student=student,
                        defaults={"status": status},
                    )
                messages.success(request, "Attendance saved successfully.")

        elif action == "create_exam":
            title = request.POST.get("exam_title", "").strip()
            exam_date = request.POST.get("exam_date")
            total_marks = request.POST.get("total_marks")
            if not title or not exam_date or not total_marks:
                messages.error(request, "Exam title, date, and total marks are required.")
            else:
                exam = Exam.objects.create(
                    teacher=teacher,
                    class_name=selected_class_name,
                    subject=selected_subject,
                    title=title,
                    exam_date=exam_date,
                    total_marks=total_marks,
                )
                selected_exam_id = exam.id
                messages.success(request, "Exam created successfully.")

        elif action == "mark_diary_read":
            feedback = get_object_or_404(
                HomeworkFeedback,
                id=request.POST.get("feedback_id"),
                homework__teacher=teacher,
                homework__class_name=selected_class_name,
                homework__subject=selected_subject,
            )
            feedback.teacher_read = True
            feedback.teacher_read_at = timezone.now()
            feedback.save(update_fields=["teacher_read", "teacher_read_at"])
            messages.success(request, "Diary message marked as read.")

        elif action == "mark_notification_read":
            notification = get_object_or_404(
                Notification,
                id=request.POST.get("notification_id"),
                is_active=True,
            )
            NotificationRead.objects.get_or_create(
                notification=notification,
                user=request.user,
            )
            messages.success(request, "Notification marked as read.")

        elif action == "save_exam_results":
            exam = get_object_or_404(
                Exam,
                id=request.POST.get("exam_id"),
                teacher=teacher,
                class_name=selected_class_name,
                subject=selected_subject,
            )
            students = Student.objects.filter(class_name=selected_class_name)
            for student in students:
                marks = request.POST.get(f"marks_{student.id}", "").strip()
                if not marks:
                    ExamResult.objects.filter(exam=exam, student=student).delete()
                    continue
                ExamResult.objects.update_or_create(
                    exam=exam,
                    student=student,
                    defaults={"marks_obtained": marks},
                )
            selected_exam_id = exam.id
            messages.success(request, "Exam results saved successfully.")

        elif action == "save_yearly_remarks":
            target_year = int(request.POST.get("remark_year", selected_remark_year))
            students = Student.objects.filter(class_name=selected_class_name)
            for student in students:
                behavior_marks_raw = request.POST.get(f"behavior_marks_{student.id}", "").strip()
                participation_marks_raw = request.POST.get(f"participation_marks_{student.id}", "").strip()
                remarks_text = request.POST.get(f"remarks_{student.id}", "").strip()

                behavior_marks = max(0, min(10, int(behavior_marks_raw or "0")))
                participation_marks = max(0, min(10, int(participation_marks_raw or "0")))

                TeacherYearlyRemark.objects.update_or_create(
                    teacher=teacher,
                    student=student,
                    class_name=selected_class_name,
                    subject=selected_subject,
                    academic_year=target_year,
                    defaults={
                        "behavior_marks": behavior_marks,
                        "participation_marks": participation_marks,
                        "remarks": remarks_text,
                    },
                )
            selected_remark_year = target_year
            messages.success(request, "Yearly teacher remarks saved successfully.")

        redirect_url = (
            f"{request.path}?panel={panel}"
        )
        if selected_class_name and selected_subject:
            redirect_url += f"&class_name={selected_class_name}&subject={selected_subject}"
        if selected_exam_id:
            redirect_url += f"&exam={selected_exam_id}"
        if attendance_date_query and panel == "attendance":
            redirect_url += f"&attendance_date={attendance_date_query}"
        if panel == "teacher_attendance":
            redirect_url += f"&teacher_year={selected_teacher_year}&teacher_month={selected_teacher_month}"
        if panel == "remarks":
            redirect_url += f"&remark_year={selected_remark_year}"
        return redirect(redirect_url)

    students = (
        Student.objects.filter(class_name=selected_class.class_name)
        .select_related("user_account")
        .order_by("roll_number", "name")
        if selected_class
        else Student.objects.none()
    )
    homework_list = (
        Homework.objects.filter(
            class_name=selected_class.class_name,
            subject=selected_class.subject,
        ).prefetch_related("feedbacks__student", "teacher__user").order_by("-date", "-id")
        if selected_class
        else Homework.objects.none()
    )
    attendance_history = (
        Attendance.objects.filter(
            teacher=teacher,
            class_name=selected_class.class_name,
            subject=selected_class.subject,
        ).prefetch_related("records__student")
        if selected_class
        else Attendance.objects.none()
    )
    exams = (
        Exam.objects.filter(
            teacher=teacher,
            class_name=selected_class.class_name,
            subject=selected_class.subject,
        ).prefetch_related("results__student")
        if selected_class
        else Exam.objects.none()
    )

    selected_attendance = None
    selected_attendance_date = attendance_date_query or date.today().isoformat()
    if selected_class:
        selected_attendance = attendance_history.filter(date=selected_attendance_date).first()

    attendance_form_rows = []
    for student in students:
        row = {"student": student, "status": AttendanceStatus.PRESENT}
        if selected_attendance:
            record = selected_attendance.records.filter(student=student).first()
            if record:
                row["status"] = record.status
        attendance_form_rows.append(row)

    attendance_history_rows = []
    for attendance in attendance_history[:10]:
        counts = {
            AttendanceStatus.PRESENT: 0,
            AttendanceStatus.ABSENT: 0,
            AttendanceStatus.LATE: 0,
        }
        for record in attendance.records.all():
            counts[record.status] = counts.get(record.status, 0) + 1
        attendance_history_rows.append(
            {
                "attendance": attendance,
                "present": counts[AttendanceStatus.PRESENT],
                "absent": counts[AttendanceStatus.ABSENT],
                "late": counts[AttendanceStatus.LATE],
            }
        )

    selected_exam = None
    if selected_class and selected_exam_id:
        selected_exam = exams.filter(id=selected_exam_id).first()
    if selected_class and selected_exam is None:
        selected_exam = exams.first()

    student_exam_rows = []
    for student in students:
        row = {"student": student, "marks": ""}
        if selected_exam:
            result = selected_exam.results.filter(student=student).first()
            if result:
                row["marks"] = result.marks_obtained
        student_exam_rows.append(row)

    diary_entries = []
    for hw in homework_list:
        feedback_lookup = {feedback.student_id: feedback for feedback in hw.feedbacks.all()}
        done_count = 0
        not_done_count = 0
        pending_count = 0
        student_feedback_rows = []
        for student in students:
            feedback = feedback_lookup.get(student.id)
            status = DiaryStatus.PENDING
            message = ""
            updated_at = None
            if feedback:
                status = feedback.status
                message = feedback.message
                updated_at = feedback.updated_at
            if status == DiaryStatus.DONE:
                done_count += 1
            elif status == DiaryStatus.NOT_DONE:
                not_done_count += 1
            else:
                pending_count += 1
            student_feedback_rows.append(
                {
                    "student": student,
                    "status": status,
                    "message": message,
                    "updated_at": updated_at,
                    "feedback_id": feedback.id if feedback else None,
                    "teacher_read": feedback.teacher_read if feedback else False,
                    "teacher_read_at": feedback.teacher_read_at if feedback else None,
                }
            )
        diary_entries.append(
            {
                "homework": hw,
                "done_count": done_count,
                "not_done_count": not_done_count,
                "pending_count": pending_count,
                "student_feedback_rows": student_feedback_rows,
            }
        )

    remark_rows = []
    if selected_class:
        remark_lookup = {
            item.student_id: item
            for item in TeacherYearlyRemark.objects.filter(
                teacher=teacher,
                class_name=selected_class.class_name,
                subject=selected_class.subject,
                academic_year=selected_remark_year,
            )
        }
        for student in students:
            saved_remark = remark_lookup.get(student.id)
            remark_rows.append(
                {
                    "student": student,
                    "behavior_marks": saved_remark.behavior_marks if saved_remark else 0,
                    "participation_marks": saved_remark.participation_marks if saved_remark else 0,
                    "remarks": saved_remark.remarks if saved_remark else "",
                    "updated_at": saved_remark.updated_at if saved_remark else None,
                }
            )

    selected_teacher_month = min(max(selected_teacher_month, 1), 12)
    if selected_teacher_month == 1:
        teacher_previous_year = selected_teacher_year - 1
        teacher_previous_month = 12
    else:
        teacher_previous_year = selected_teacher_year
        teacher_previous_month = selected_teacher_month - 1
    if selected_teacher_month == 12:
        teacher_next_year = selected_teacher_year + 1
        teacher_next_month = 1
    else:
        teacher_next_year = selected_teacher_year
        teacher_next_month = selected_teacher_month + 1
    teacher_month_total_days = calendar.monthrange(selected_teacher_year, selected_teacher_month)[1]
    teacher_attendance_records = TeacherAttendance.objects.filter(
        teacher=teacher,
        date__year=selected_teacher_year,
        date__month=selected_teacher_month,
    ).order_by("date")
    teacher_attendance_lookup = {
        record.date.day: record for record in teacher_attendance_records
    }
    school_timing_settings = SchoolTimingSettings.get_solo()
    teacher_attendance_rows = []
    teacher_present_count = 0
    teacher_late_count = 0
    teacher_leave_count = 0
    teacher_absent_count = 0
    for day_number in range(1, teacher_month_total_days + 1):
        current_date = date(selected_teacher_year, selected_teacher_month, day_number)
        record = teacher_attendance_lookup.get(day_number)
        entry_time = record.entry_time if record else None
        exit_time = record.exit_time if record else None
        day_status = _teacher_day_status(
            entry_time,
            exit_time,
            school_timing_settings.late_after_time,
            school_timing_settings.leave_before_time,
            current_date,
        )
        if day_status == "present":
            teacher_present_count += 1
        elif day_status == "late":
            teacher_late_count += 1
        elif day_status == "leave":
            teacher_leave_count += 1
        elif day_status == "absent":
            teacher_absent_count += 1
        teacher_attendance_rows.append(
            {
                "date": current_date,
                "status": day_status,
                "entry_time": entry_time,
                "exit_time": exit_time,
                "remarks": record.remarks if record else "",
            }
        )

    return render(
        request,
        "teacher_dashboard.html",
        {
            "teacher": teacher,
            "class_subjects": class_subjects,
            "selected_class": selected_class,
            "panel": panel,
            "students": students,
            "homework_list": homework_list,
            "diary_entries": diary_entries,
            "diary_statuses": DiaryStatus.choices,
            "attendance_history_rows": attendance_history_rows,
            "attendance_statuses": AttendanceStatus.choices,
            "today": date.today().isoformat(),
            "selected_attendance_date": selected_attendance_date,
            "selected_attendance": selected_attendance,
            "attendance_form_rows": attendance_form_rows,
            "exams": exams,
            "selected_exam": selected_exam,
            "student_exam_rows": student_exam_rows,
            "notifications": _attach_notification_state(
                _notifications_for(request.user),
                request.user,
            ),
            "selected_teacher_year": selected_teacher_year,
            "selected_teacher_month": selected_teacher_month,
            "teacher_attendance_rows": teacher_attendance_rows,
            "teacher_attendance_summary": {
                "present": teacher_present_count,
                "late": teacher_late_count,
                "leave": teacher_leave_count,
                "absent": teacher_absent_count,
            },
            "teacher_attendance_month_label": f"{calendar.month_name[selected_teacher_month]} {selected_teacher_year}",
            "teacher_previous_month_url": f"{request.path}?panel=teacher_attendance&teacher_year={teacher_previous_year}&teacher_month={teacher_previous_month}",
            "teacher_next_month_url": f"{request.path}?panel=teacher_attendance&teacher_year={teacher_next_year}&teacher_month={teacher_next_month}",
            "school_timing_settings": school_timing_settings,
            "selected_remark_year": selected_remark_year,
            "remark_rows": remark_rows,
        },
    )


@login_required
def student_dashboard(request):
    if _is_attendance_desk_user(request.user):
        return redirect("attendance_desk")
    school_timing_settings = SchoolTimingSettings.get_solo()
    panel = request.GET.get("panel", "dashboard")
    selected_diary_subject = request.GET.get("diary_subject")
    performance_view = request.GET.get("performance_view", "subject_wise")
    linked_students = Student.objects.filter(user_account=request.user).order_by(
        "class_name", "roll_number", "name"
    )
    selected_student_id = request.GET.get("student_id")

    if request.method == "POST":
        panel = request.POST.get("panel", "digital_diary")
        selected_diary_subject = request.POST.get("diary_subject")
        performance_view = request.POST.get("performance_view", "subject_wise")
        selected_student_id = request.POST.get("student_id")
        linked_students = Student.objects.filter(user_account=request.user).order_by(
            "class_name", "roll_number", "name"
        )
        student = linked_students.filter(id=selected_student_id).first()
        if student is None:
            student = linked_students.first()
        if student is None:
            messages.error(request, "No student is linked to this account yet.")
            return redirect("student_dashboard")

        if request.POST.get("action") == "save_diary_feedback":
            homework = get_object_or_404(
                Homework,
                id=request.POST.get("homework_id"),
                class_name=student.class_name,
            )
            status = request.POST.get("status", DiaryStatus.PENDING)
            message_text = request.POST.get("message", "").strip()
            HomeworkFeedback.objects.update_or_create(
                homework=homework,
                student=student,
                defaults={
                    "status": status,
                    "message": message_text,
                    "teacher_read": False,
                    "teacher_read_at": None,
                },
            )
            messages.success(request, "Digital diary response saved successfully.")
        elif request.POST.get("action") == "mark_notification_read":
            notification = get_object_or_404(
                Notification,
                id=request.POST.get("notification_id"),
                is_active=True,
            )
            NotificationRead.objects.get_or_create(
                notification=notification,
                user=request.user,
            )
            messages.success(request, "Notification marked as read.")
        redirect_url = request.path
        if student:
            redirect_url += f"?student_id={student.id}&panel={panel}"
            if panel == "digital_diary" and selected_diary_subject:
                redirect_url += f"&diary_subject={selected_diary_subject}"
            if panel == "exam_results" and performance_view:
                redirect_url += f"&performance_view={performance_view}"
        return redirect(redirect_url)

    if not linked_students.exists():
        messages.error(request, "No student is linked to this account yet.")
        return render(
            request,
            "student_dashboard.html",
            {
                "student": None,
                "linked_students": linked_students,
                "show_student_switcher": False,
                "homework": [],
                "attendance_records": [],
                "attendance_summary": {"present": 0, "absent": 0, "late": 0},
                "exam_results": [],
                "latest_homework": [],
                "latest_results": [],
                "fee_records": [],
                "fee_summary": {
                    "total_paid": 0,
                    "total_unpaid": 0,
                    "current_month_status": "Not available",
                    "is_fee_alert": False,
                },
                "selected_diary_subject": None,
                "configured_subjects": [],
                "performance_view": performance_view,
                "school_timing_settings": school_timing_settings,
                "yearly_teacher_remarks": [],
            },
        )

    student = linked_students.filter(id=selected_student_id).first()
    if student is None:
        student = linked_students.first()

    student.ensure_fee_records()

    homework = Homework.objects.filter(class_name=student.class_name).select_related(
        "teacher__user"
    ).prefetch_related("feedbacks").order_by("-date", "-id")
    all_attendance_records = AttendanceRecord.objects.filter(student=student).select_related(
        "attendance"
    )
    attendance_records = all_attendance_records[:10]
    exam_results = ExamResult.objects.filter(student=student).select_related("exam").order_by(
        "-exam__exam_date", "-exam__id"
    )
    yearly_teacher_remarks = TeacherYearlyRemark.objects.filter(
        student=student
    ).select_related("teacher__user").order_by(
        "-academic_year",
        "teacher__user__first_name",
        "subject",
    )
    class_exam_averages = {
        item["exam_id"]: float(item["average_marks"])
        for item in ExamResult.objects.filter(exam__class_name=student.class_name)
        .values("exam_id")
        .annotate(average_marks=Avg("marks_obtained"))
    }
    attendance_summary = {
        "present": AttendanceRecord.objects.filter(
            student=student, status=AttendanceStatus.PRESENT
        ).count(),
        "absent": AttendanceRecord.objects.filter(
            student=student, status=AttendanceStatus.ABSENT
        ).count(),
        "late": AttendanceRecord.objects.filter(
            student=student, status=AttendanceStatus.LATE
        ).count(),
    }
    attendance_total = sum(attendance_summary.values())
    overall_attendance_percentage = (
        round((attendance_summary["present"] / attendance_total) * 100, 2)
        if attendance_total
        else 0
    )

    total_obtained_marks = sum(float(result.marks_obtained) for result in exam_results)
    total_possible_marks = sum(result.exam.total_marks for result in exam_results)
    exam_count = exam_results.count()
    average_marks = round(total_obtained_marks / exam_count, 2) if exam_count else 0
    overall_percentage = (
        round((total_obtained_marks / total_possible_marks) * 100, 2)
        if total_possible_marks
        else 0
    )

    subject_totals = {}
    for result in exam_results:
        subject_name = result.exam.subject
        if subject_name not in subject_totals:
            subject_totals[subject_name] = {"obtained": 0.0, "total": 0}
        subject_totals[subject_name]["obtained"] += float(result.marks_obtained)
        subject_totals[subject_name]["total"] += result.exam.total_marks

    subject_percentages = []
    for subject_name, values in subject_totals.items():
        percentage = round((values["obtained"] / values["total"]) * 100, 2) if values["total"] else 0
        subject_percentages.append(
            {
                "subject": subject_name,
                "obtained": round(values["obtained"], 2),
                "total": values["total"],
                "percentage": percentage,
            }
        )
    subject_percentages.sort(key=lambda item: item["percentage"], reverse=True)

    class_subject_totals = {}
    class_results = ExamResult.objects.filter(exam__class_name=student.class_name).select_related(
        "exam"
    )
    for result in class_results:
        subject_name = result.exam.subject
        if subject_name not in class_subject_totals:
            class_subject_totals[subject_name] = {"obtained": 0.0, "total": 0}
        class_subject_totals[subject_name]["obtained"] += float(result.marks_obtained)
        class_subject_totals[subject_name]["total"] += result.exam.total_marks

    class_subject_percentages = {}
    for subject_name, values in class_subject_totals.items():
        class_subject_percentages[subject_name] = (
            round((values["obtained"] / values["total"]) * 100, 2) if values["total"] else 0
        )

    subject_comparison_rows = []
    for item in subject_percentages:
        class_percentage = class_subject_percentages.get(item["subject"], 0)
        subject_comparison_rows.append(
            {
                "subject": item["subject"],
                "student_percentage": item["percentage"],
                "class_percentage": class_percentage,
                "difference": round(item["percentage"] - class_percentage, 2),
            }
        )

    configured_subjects = list(
        SchoolClassSubject.objects.filter(school_class__name=student.class_name)
        .select_related("subject")
        .values_list("subject__name", flat=True)
    )
    if not configured_subjects:
        configured_subjects = list(
            dict.fromkeys(
                list(subject_totals.keys()) + list(class_subject_percentages.keys())
            )
        )
    if not selected_diary_subject or selected_diary_subject not in configured_subjects:
        selected_diary_subject = configured_subjects[0] if configured_subjects else None

    best_subject = subject_percentages[0] if subject_percentages else None
    needs_attention_subject = subject_percentages[-1] if subject_percentages else None

    performance_band = "No exams yet"
    if exam_count:
        performance_band = _performance_band(overall_percentage)

    monthly_attendance = OrderedDict()
    for record in all_attendance_records.order_by("attendance__date"):
        month_label = record.attendance.date.strftime("%B %Y")
        if month_label not in monthly_attendance:
            monthly_attendance[month_label] = {
                "month": month_label,
                "present": 0,
                "absent": 0,
                "late": 0,
                "total": 0,
                "percentage": 0,
            }
        monthly_attendance[month_label][record.status] += 1
        monthly_attendance[month_label]["total"] += 1

    monthly_attendance_rows = []
    for item in monthly_attendance.values():
        item["percentage"] = (
            round((item["present"] / item["total"]) * 100, 2) if item["total"] else 0
        )
        item["band"] = _attendance_band(item["percentage"])
        monthly_attendance_rows.append(item)
    monthly_attendance_rows.reverse()

    exam_trend_points = []
    chronological_results = list(exam_results.order_by("exam__exam_date", "exam__id"))
    total_class_average_obtained = 0.0
    class_average_total_marks = 0
    class_average_rows = []
    for result in chronological_results:
        percentage = (
            round((float(result.marks_obtained) / result.exam.total_marks) * 100, 2)
            if result.exam.total_marks
            else 0
        )
        class_average_marks = round(class_exam_averages.get(result.exam_id, 0), 2)
        class_average_percentage = (
            round((class_average_marks / result.exam.total_marks) * 100, 2)
            if result.exam.total_marks
            else 0
        )
        difference = round(float(result.marks_obtained) - class_average_marks, 2)
        total_class_average_obtained += class_average_marks
        class_average_total_marks += result.exam.total_marks
        class_average_rows.append(
            {
                "exam_title": result.exam.title,
                "subject": result.exam.subject,
                "date": result.exam.exam_date,
                "student_marks": round(float(result.marks_obtained), 2),
                "student_percentage": percentage,
                "total_marks": result.exam.total_marks,
                "term": _exam_term(result.exam.title),
                "class_average_marks": class_average_marks,
                "class_average_percentage": class_average_percentage,
                "difference": difference,
                "comparison_label": "Above class average"
                if difference > 0
                else "Below class average"
                if difference < 0
                else "At class average",
            }
        )
        exam_trend_points.append(
            {
                "label": f"{result.exam.title} ({result.exam.subject})",
                "date": result.exam.exam_date,
                "percentage": percentage,
            }
        )

    marks_trend = "No exams yet"
    if len(exam_trend_points) == 1:
        marks_trend = "Only one exam recorded"
    elif len(exam_trend_points) >= 2:
        last_change = exam_trend_points[-1]["percentage"] - exam_trend_points[-2]["percentage"]
        if last_change > 3:
            marks_trend = "Improving"
        elif last_change < -3:
            marks_trend = "Dropping"
        else:
            marks_trend = "Stable"
    class_average_percentage = (
        round((total_class_average_obtained / class_average_total_marks) * 100, 2)
        if class_average_total_marks
        else 0
    )
    class_average_difference = round(overall_percentage - class_average_percentage, 2)
    subject_exam_lookup = {}
    for row in class_average_rows:
        subject_exam_lookup.setdefault(row["subject"], []).append(row)

    subject_result_sections = []
    for subject_name in configured_subjects:
        subject_exam_rows = list(reversed(subject_exam_lookup.get(subject_name, [])))
        subject_data = subject_totals.get(subject_name, {"obtained": 0.0, "total": 0})
        subject_percentage = (
            round((subject_data["obtained"] / subject_data["total"]) * 100, 2)
            if subject_data["total"]
            else 0
        )
        class_subject_percentage = class_subject_percentages.get(subject_name, 0)
        subject_result_sections.append(
            {
                "subject": subject_name,
                "exam_count": len(subject_exam_rows),
                "obtained": round(subject_data["obtained"], 2),
                "total": subject_data["total"],
                "percentage": subject_percentage,
                "class_percentage": class_subject_percentage,
                "difference": round(subject_percentage - class_subject_percentage, 2),
                "exam_rows": subject_exam_rows,
            }
        )

    def build_term_summary(term_name):
        summary_rows = []
        for subject_name in configured_subjects:
            section = next(
                (
                    item
                    for item in subject_result_sections
                    if item["subject"] == subject_name
                ),
                None,
            )
            term_rows = [
                row
                for row in (section["exam_rows"] if section else [])
                if row["term"] == term_name
            ]
            latest_row = term_rows[-1] if term_rows else None
            summary_rows.append(
                {
                    "subject": subject_name,
                    "marks_text": (
                        f"{latest_row['student_marks']} / {latest_row['total_marks']}"
                        if latest_row
                        else "-"
                    ),
                    "percentage": latest_row["student_percentage"] if latest_row else None,
                    "class_percentage": latest_row["class_average_percentage"] if latest_row else None,
                }
            )
        return summary_rows

    mid_term_summary = build_term_summary("Mid Term")
    final_term_summary = build_term_summary("Final Term")

    dashboard_graph_metrics = [
        {
            "label": "Your Marks",
            "value": overall_percentage,
            "color": "#1d4ed8",
        },
        {
            "label": "Class Average",
            "value": class_average_percentage,
            "color": "#f59e0b",
        },
        {
            "label": "Attendance",
            "value": overall_attendance_percentage,
            "color": "#16a34a",
        },
    ]

    diary_entries = []
    for hw in homework:
        feedback = hw.feedbacks.filter(student=student).first()
        diary_entries.append(
            {
                "homework": hw,
                "status": feedback.status if feedback else DiaryStatus.PENDING,
                "message": feedback.message if feedback else "",
                "updated_at": feedback.updated_at if feedback else None,
                "teacher_read": feedback.teacher_read if feedback else False,
                "teacher_read_at": feedback.teacher_read_at if feedback else None,
            }
        )
    filtered_diary_entries = [
        item for item in diary_entries if item["homework"].subject == selected_diary_subject
    ]

    today = timezone.localdate()
    current_month_homework_count = homework.filter(
        date__year=today.year, date__month=today.month
    ).count()
    current_month_exam_count = exam_results.filter(
        exam__exam_date__year=today.year,
        exam__exam_date__month=today.month,
    ).count()
    current_month_attendance = next(
        (
            row
            for row in monthly_attendance_rows
            if row["month"] == today.strftime("%B %Y")
        ),
        None,
    )
    progress_cards = {
        "monthly": {
            "title": f"Progress Card - {today.strftime('%B %Y')}",
            "attendance_percentage": current_month_attendance["percentage"]
            if current_month_attendance
            else 0,
            "attendance_total": current_month_attendance["total"]
            if current_month_attendance
            else 0,
            "diary_count": current_month_homework_count,
            "exam_count": current_month_exam_count,
            "overall_percentage": overall_percentage,
            "attendance_band": _attendance_band(
                current_month_attendance["percentage"] if current_month_attendance else 0
            ),
        },
        "session": {
            "title": "Progress Card - Full Session",
            "attendance_percentage": overall_attendance_percentage,
            "attendance_total": attendance_total,
            "diary_count": homework.count(),
            "exam_count": exam_count,
            "overall_percentage": overall_percentage,
            "attendance_band": _attendance_band(overall_attendance_percentage),
        },
    }

    student_id_card = {
        "card_number": _student_id_number(student),
        "campus_info": ID_CARD_CAMPUS_INFO.get(student.campus, ID_CARD_CAMPUS_INFO[Campus.GIRLS]),
    }

    if request.GET.get("download") == "progress_card":
        return _progress_card_pdf(
            student,
            progress_cards,
            overall_percentage,
            performance_band,
            subject_result_sections,
            attendance_summary,
            configured_subjects,
        )
    if request.GET.get("download") == "id_card":
        return _id_card_pdf(student)

    weekdays = [
        Weekday.MONDAY,
        Weekday.TUESDAY,
        Weekday.WEDNESDAY,
        Weekday.THURSDAY,
        Weekday.FRIDAY,
        Weekday.SATURDAY,
    ]
    timetable_entries = TimetableEntry.objects.filter(class_name=student.class_name)
    timetable_lookup = {
        (entry.day, entry.lecture_number): entry.subject for entry in timetable_entries
    }
    timetable_rows = []
    for day in weekdays:
        lectures = []
        for lecture_number in range(1, 8):
            lectures.append(timetable_lookup.get((day, lecture_number), "-"))
        timetable_rows.append({"day": day, "lectures": lectures})

    session_start_year, session_slots = _current_fee_session(today)
    session_years = [session_start_year, session_start_year + 1]
    fee_records = list(
        StudentFee.objects.filter(student=student, year__in=session_years)
    )
    slot_order = {slot: index for index, slot in enumerate(session_slots)}
    fee_records = [
        record
        for record in fee_records
        if (record.year, record.month) in slot_order
    ]
    fee_records.sort(key=lambda record: slot_order[(record.year, record.month)])
    fee_records.reverse()
    for record in fee_records:
        record.month_name = _month_name(record.month)
    current_month_fee = next(
        (record for record in fee_records if record.month == today.month),
        None,
    )
    is_fee_alert = bool(
        current_month_fee
        and current_month_fee.balance_amount > 0
        and today.day > 6
    )
    total_paid = round(
        sum(float(record.paid_amount) for record in fee_records),
        2,
    )
    total_unpaid = round(
        sum(float(record.balance_amount) for record in fee_records),
        2,
    )

    fee_summary = {
        "total_paid": total_paid,
        "total_unpaid": total_unpaid,
        "current_month_status": current_month_fee.get_status_display()
        if current_month_fee
        else "Not available",
        "current_month_name": _month_name(today.month),
        "current_month_amount": current_month_fee.amount if current_month_fee else 0,
        "current_month_paid": current_month_fee.paid_amount if current_month_fee else 0,
        "current_month_balance": current_month_fee.balance_amount if current_month_fee else 0,
        "is_fee_alert": is_fee_alert,
    }

    if request.GET.get("download") == "fee_tracker":
        return _student_fee_tracker_pdf(student, fee_records, fee_summary)

    return render(
        request,
        "student_dashboard.html",
        {
            "student": student,
            "linked_students": linked_students,
            "show_student_switcher": linked_students.count() > 1,
            "panel": panel,
            "performance_view": performance_view,
            "configured_subjects": configured_subjects,
            "selected_diary_subject": selected_diary_subject,
            "homework": homework,
            "diary_entries": filtered_diary_entries,
            "attendance_records": attendance_records,
            "attendance_summary": attendance_summary,
            "exam_results": exam_results,
            "latest_homework": homework[:5],
            "latest_results": exam_results[:5],
            "timetable_rows": timetable_rows,
            "fee_records": fee_records,
            "fee_summary": fee_summary,
            "notifications": _attach_notification_state(
                _notifications_for(request.user, student=student),
                request.user,
            ),
            "school_timing_settings": school_timing_settings,
            "progress_cards": progress_cards,
            "student_id_card": student_id_card,
            "yearly_teacher_remarks": yearly_teacher_remarks,
            "analytics": {
                "exam_count": exam_count,
                "total_obtained_marks": round(total_obtained_marks, 2),
                "total_possible_marks": total_possible_marks,
                "average_marks": average_marks,
                "overall_percentage": overall_percentage,
                "overall_attendance_percentage": overall_attendance_percentage,
                "performance_band": performance_band,
                "class_average_percentage": class_average_percentage,
                "class_average_difference": class_average_difference,
                "class_average_rows": list(reversed(class_average_rows)),
                "dashboard_graph_metrics": dashboard_graph_metrics,
                "subject_result_sections": subject_result_sections,
                "mid_term_summary": mid_term_summary,
                "final_term_summary": final_term_summary,
                "best_subject": best_subject,
                "needs_attention_subject": needs_attention_subject,
                "subject_percentages": subject_percentages,
                "subject_comparison_rows": subject_comparison_rows,
                "monthly_attendance_rows": monthly_attendance_rows,
                "exam_trend_points": list(reversed(exam_trend_points)),
                "marks_trend": marks_trend,
            },
        },
    )
