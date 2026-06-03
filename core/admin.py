from django.contrib import admin
from .models import *


admin.site.register(Profile)
admin.site.register(LastFace)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]


@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = [
        "profile",
        "subject",
        "day_of_week",
        "start_time",
        "end_time",
        "grace_period_minutes",
    ]
    list_filter = ["day_of_week", "subject"]
    search_fields = ["profile__first_name", "profile__last_name", "subject__name"]


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ["profile", "schedule", "date", "scan_time", "status"]
    list_filter = ["status", "date"]
    search_fields = ["profile__first_name", "profile__last_name"]
