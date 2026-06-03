from django import forms
from .models import *


class DateInput(forms.DateInput):
    input_type = "date"


class TimeInput(forms.TimeInput):
    input_type = "time"


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = "__all__"
        widgets = {
            "date": DateInput(),
            "shift": TimeInput()
        }
        exclude = ["present", "updated", "shift_end"]

    def __init__(self, *args, **kwargs):
        super(ProfileForm, self).__init__(*args, **kwargs)
        self.fields["first_name"].widget.attrs["class"] = "form-control"
        self.fields["last_name"].widget.attrs["class"] = "form-control"
        self.fields["date"].widget.attrs["class"] = "form-control"
        self.fields["phone"].widget.attrs["class"] = "form-control"
        self.fields["email"].widget.attrs["class"] = "form-control"
        self.fields["ranking"].widget.attrs["class"] = "form-control"
        self.fields["profession"].widget.attrs["class"] = "form-control"
        self.fields["status"].widget.attrs["class"] = "form-control"
        # self.fields['image'].widget.attrs['class'] = 'form-control'
        self.fields["shift"].widget.attrs["class"] = "form-control"
        self.fields["shift"].label = "Shift Start Time"
        self.fields["working_hours"].widget.attrs["class"] = "form-control"
        self.fields["working_hours"].label = "Hours of Work"
        self.fields["department"].widget.attrs["class"] = "form-control"
        self.fields["department"].label = "Department"


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super(SubjectForm, self).__init__(*args, **kwargs)
        self.fields["name"].widget.attrs["class"] = "form-control"
        self.fields["name"].label = "Shift / Department Name"


class ScheduleForm(forms.ModelForm):
    class Meta:
        model = Schedule
        fields = "__all__"
        widgets = {"start_time": TimeInput(), "end_time": TimeInput()}

    def __init__(self, *args, **kwargs):
        super(ScheduleForm, self).__init__(*args, **kwargs)
        self.fields["profile"].widget.attrs["class"] = "form-control"
        self.fields["profile"].label = "Employee"
        self.fields["subject"].widget.attrs["class"] = "form-control"
        self.fields["subject"].label = "Shift / Department"
        self.fields["day_of_week"].widget.attrs["class"] = "form-control"
        self.fields["start_time"].widget.attrs["class"] = "form-control"
        self.fields["end_time"].widget.attrs["class"] = "form-control"
        self.fields["grace_period_minutes"].widget.attrs["class"] = "form-control"

