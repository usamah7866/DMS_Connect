from django import forms

from .models import AdmissionApplication, CareerApplication


class DateInput(forms.DateInput):
    input_type = "date"


class AdmissionApplicationForm(forms.ModelForm):
    class Meta:
        model = AdmissionApplication
        fields = [
            "campus",
            "class_applying_for",
            "student_name",
            "gender",
            "date_of_birth",
            "b_form_number",
            "previous_school",
            "religion",
            "guardian_name",
            "father_education",
            "office_phone_no",
            "relationship",
            "cnic_number",
            "occupation",
            "phone",
            "landline_no",
            "mother_cell_no",
            "whatsapp",
            "email",
            "emergency_contact",
            "medium",
            "academic_group",
            "selected_subjects",
            "address",
            "city",
            "message",
            "transport_required",
            "student_photo",
            "birth_certificate",
            "guardian_cnic",
            "previous_result",
            "transfer_certificate",
            "additional_document",
        ]
        widgets = {
            "date_of_birth": DateInput(),
            "address": forms.Textarea(attrs={"rows": 4}),
            "message": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["class_applying_for"].widget = forms.Select(
            choices=[
                ("", "Select class"),
                ("Nursery", "Nursery"),
                ("KG I", "KG I"),
                ("KG II", "KG II"),
                ("Class I", "Class I"),
                ("Class II", "Class II"),
                ("Class III", "Class III"),
                ("Class IV", "Class IV"),
                ("Class V", "Class V"),
                ("Class VI", "Class VI"),
                ("Class VII", "Class VII"),
                ("Class VIII", "Class VIII"),
                ("Class IX", "Class IX"),
                ("Class X", "Class X"),
            ]
        )
        self.fields["gender"].widget = forms.Select(
            choices=[("", "Select gender"), ("Male", "Male"), ("Female", "Female")]
        )
        self.fields["religion"].widget = forms.Select(
            choices=[("", "Select religion"), ("Muslim", "Muslim"), ("Non-Muslim", "Non-Muslim")]
        )
        self.fields["medium"].widget = forms.Select(
            choices=[("", "Select medium"), ("English", "English"), ("Urdu", "Urdu")]
        )
        self.fields["academic_group"].widget = forms.Select(
            choices=[
                ("", "Select group"),
                ("Science with Biology", "Science with Biology"),
                ("Science and Computer Science", "Science and Computer Science"),
                ("Humanities", "Humanities"),
            ]
        )
        self.fields["transport_required"].widget = forms.Select(
            choices=[("", "Select option"), ("Yes", "Yes"), ("No", "No")]
        )

        labels = {
            "class_applying_for": "Admission Required For",
            "student_name": "Child's Name",
            "guardian_name": "Father's Name",
            "father_education": "Father's Education",
            "office_phone_no": "Office Phone No.",
            "phone": "Father's Cell No.",
            "mother_cell_no": "Mother's Cell No.",
            "landline_no": "Land Line No.",
            "medium": "Medium",
            "academic_group": "Group (for 9th & 10th only)",
            "selected_subjects": "Subjects",
            "student_photo": "Student Photograph",
            "message": "Note / Additional Information",
        }
        for field_name, label in labels.items():
            self.fields[field_name].label = label


class CareerApplicationForm(forms.ModelForm):
    class Meta:
        model = CareerApplication
        fields = [
            "campus",
            "full_name",
            "email",
            "phone",
            "date_of_birth",
            "address",
            "cnic_number",
            "religion",
            "position_applied_for",
            "highest_qualification",
            "organization_name",
            "job_post_name",
            "years_of_experience",
            "cover_letter",
            "cv_file",
        ]
        widgets = {
            "date_of_birth": DateInput(),
            "cover_letter": forms.Textarea(attrs={"rows": 5}),
            "address": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["religion"].widget = forms.Select(
            choices=[("", "Select religion"), ("Muslim", "Muslim"), ("Non-Muslim", "Non-Muslim")]
        )
        self.fields["organization_name"].label = "Organization Name"
        self.fields["job_post_name"].label = "Job Post Name"
        self.fields["cnic_number"].label = "CNIC Number"
        self.fields["date_of_birth"].label = "Date of Birth"
