from django.urls import path, include
from .views import *


urlpatterns = [
    path("", index, name="index"),
    path("ajax/", ajax, name="ajax"),
    path("scan/", scan, name="scan"),
    path("profiles/", profiles, name="profiles"),
    path("details/", details, name="details"),
    path("add_profile/", add_profile, name="add_profile"),
    path("edit_profile/<int:id>/", edit_profile, name="edit_profile"),
    path("delete_profile/<int:id>/", delete_profile, name="delete_profile"),
    path("clear_history/", clear_history, name="clear_history"),
    path("reset/", reset, name="reset"),
    # Schedule management
    path("schedules/", schedules, name="schedules"),
    path("add_schedule/", add_schedule, name="add_schedule"),
    path("edit_schedule/<int:id>/", edit_schedule, name="edit_schedule"),
    path("delete_schedule/<int:id>/", delete_schedule, name="delete_schedule"),
    path("add_subject/", add_subject, name="add_subject"),
    # Attendance report
    path("attendance_report/", attendance_report, name="attendance_report"),
    # Browser-side frame upload scanning
    path("scan_frame/", scan_frame, name="scan_frame"),
    # Employee profile detail and performance ratings page
    path("profile/<int:id>/", profile_detail, name="profile_detail"),
]
