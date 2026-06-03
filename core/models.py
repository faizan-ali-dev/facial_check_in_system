import datetime
from time import time

from django.db import models


types = [("employee", "employee"), ("visitor", "visitor")]


class Profile(models.Model):
    first_name = models.CharField(max_length=70)
    last_name = models.CharField(max_length=70)
    date = models.DateField()
    phone = models.BigIntegerField()
    email = models.EmailField()
    ranking = models.IntegerField(default=0)
    profession = models.CharField(max_length=200)
    status = models.CharField(
        choices=types, max_length=20, null=True, blank=False, default="employee"
    )
    present = models.BooleanField(default=False)
    image = models.ImageField()
    updated = models.DateTimeField(auto_now=True)
    shift = models.TimeField()
    shift_end = models.TimeField(null=True, blank=True)
    working_hours = models.DecimalField(max_digits=4, decimal_places=2, default=8.00)
    department = models.ForeignKey(
        "Subject", on_delete=models.SET_NULL, null=True, blank=True
    )
    face_encoding = models.JSONField(null=True, blank=True)

    def __str__(self):
        return self.first_name + " " + self.last_name

    def save(self, *args, **kwargs):
        # Calculate shift_end based on shift and working_hours
        if self.shift and self.working_hours:
            hours = int(self.working_hours)
            minutes = int((float(self.working_hours) - hours) * 60)
            dt = datetime.datetime.combine(datetime.date.today(), self.shift) + datetime.timedelta(hours=hours, minutes=minutes)
            self.shift_end = dt.time()

        # Detect if image is changing
        image_changed = False
        if self.pk:
            orig = Profile.objects.filter(pk=self.pk).first()
            if orig and orig.image != self.image:
                image_changed = True
                self.face_encoding = None

        super(Profile, self).save(*args, **kwargs)

        # After save, generate face encoding if it's missing or image changed
        if self.image and (not self.face_encoding or image_changed):
            try:
                import face_recognition
                import numpy as np
                from PIL import Image
                img = Image.open(self.image.path)
                rgb_img = np.array(img.convert("RGB"))
                encodings = face_recognition.face_encodings(rgb_img)
                if len(encodings) > 0:
                    self.face_encoding = list(encodings[0])
                    Profile.objects.filter(pk=self.pk).update(face_encoding=self.face_encoding)
                    print(f"[Profile.save] Auto-calculated and updated face encoding for {self.first_name}")
            except Exception as e:
                print(f"[Profile.save] Error auto-calculating face encoding: {e}")

        # Automatically assign Monday-Friday schedule
        if self.shift and self.shift_end:
            dept = self.department
            if not dept:
                # Find first or create default
                dept = Subject.objects.first()
                if not dept:
                    dept = Subject.objects.create(name="General Department")
                    
            schedule_obj, created = Schedule.objects.get_or_create(
                profile=self,
                day_of_week="mon_fri",
                defaults={
                    "subject": dept,
                    "start_time": self.shift,
                    "end_time": self.shift_end,
                    "grace_period_minutes": 15
                }
            )
            if not created:
                schedule_obj.subject = dept
                schedule_obj.start_time = self.shift
                schedule_obj.end_time = self.shift_end
                schedule_obj.save()



class LastFace(models.Model):
    last_face = models.CharField(max_length=200)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.last_face


class Subject(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class Schedule(models.Model):
    DAY_CHOICES = [
        ("mon_fri", "Monday to Friday"),
        ("mon", "Monday"),
        ("tue", "Tuesday"),
        ("wed", "Wednesday"),
        ("thu", "Thursday"),
        ("fri", "Friday"),
        ("sat", "Saturday"),
        ("sun", "Sunday"),
    ]
    profile = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="schedules"
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    day_of_week = models.CharField(max_length=10, choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_period_minutes = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ["day_of_week", "start_time"]

    def __str__(self):
        return f"{self.profile} — {self.subject} ({self.get_day_of_week_display()} {self.start_time:%H:%M}-{self.end_time:%H:%M})"


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [
        ("on_time", "On Time"),
        ("late", "Late"),
        ("absent", "Absent"),
    ]
    profile = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="attendance_records"
    )
    schedule = models.ForeignKey(
        Schedule, on_delete=models.SET_NULL, null=True, blank=True
    )
    date = models.DateField()
    scan_time = models.TimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="absent")

    class Meta:
        unique_together = ["profile", "schedule", "date"]
        ordering = ["-date", "-scan_time"]

    def __str__(self):
        return f"{self.profile} — {self.status} ({self.date})"


from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

@receiver(post_save, sender=AttendanceRecord)
def update_profile_present_on_save(sender, instance, **kwargs):
    if instance.date == datetime.date.today():
        profile = instance.profile
        if not profile.present:
            profile.present = True
            Profile.objects.filter(pk=profile.pk).update(present=True)

@receiver(post_delete, sender=AttendanceRecord)
def update_profile_present_on_delete(sender, instance, **kwargs):
    if instance.date == datetime.date.today():
        profile = instance.profile
        exists = AttendanceRecord.objects.filter(profile=profile, date=datetime.date.today()).exists()
        if not exists:
            profile.present = False
            Profile.objects.filter(pk=profile.pk).update(present=False)


