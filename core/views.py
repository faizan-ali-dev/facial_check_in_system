from django.shortcuts import render, HttpResponse, redirect, get_object_or_404
from .models import *
from .forms import *
try:
    import face_recognition
    import cv2
    import numpy as np
    import winsound
    from playsound import playsound
except ImportError:
    face_recognition = None
    cv2 = None
    np = None
    winsound = None
    playsound = None
from django.db.models import Q
import os
from datetime import datetime, timedelta
import base64
import io
from PIL import Image
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt


last_face = "no_face"
current_path = os.path.dirname(__file__)
sound_folder = os.path.join(current_path, "sound/")
face_list_file = os.path.join(current_path, "face_list.txt")
sound = os.path.join(sound_folder, "beep.wav")


def index(request):
    scanned = LastFace.objects.all().order_by("-date")[:50]
    present = list(Profile.objects.filter(present=True).order_by("-updated"))
    absent = list(Profile.objects.filter(present=False).order_by("shift"))

    # Get today's attendance records and annotate profiles with arrival status
    today = datetime.now().date()
    today_records = AttendanceRecord.objects.filter(date=today).select_related(
        "profile", "schedule", "schedule__subject"
    )

    # Build a lookup dict: profile_id -> latest attendance record status
    attendance_lookup = {}
    for record in today_records:
        if record.profile_id not in attendance_lookup:
            attendance_lookup[record.profile_id] = record.status

    # Annotate each present profile with their arrival status
    for profile in present:
        profile.arrival_status = attendance_lookup.get(profile.id, "")

    # Calculate SaaS metrics
    total_employees = Profile.objects.count()
    present_count = len(present)
    absent_count = len(absent)
    late_count = today_records.filter(status="late").count()

    context = {
        "scanned": scanned,
        "present": present,
        "absent": absent,
        "total_employees": total_employees,
        "present_count": present_count,
        "absent_count": absent_count,
        "late_count": late_count,
    }
    return render(request, "core/index.html", context)


def ajax(request):
    last_face = LastFace.objects.last()
    context = {"last_face": last_face}
    return render(request, "core/ajax.html", context)


def get_known_face_encodings():
    known_face_encodings = []
    known_face_names = []
    profiles = Profile.objects.all()
    for profile in profiles:
        if not profile.image:
            continue
        
        # If encoding is not cached in the DB, calculate and save it now
        if not profile.face_encoding:
            try:
                from PIL import Image
                img = Image.open(profile.image.path)
                rgb_img = np.array(img.convert("RGB"))
                encodings = face_recognition.face_encodings(rgb_img)
                if len(encodings) > 0:
                    profile.face_encoding = list(encodings[0])
                    profile.save(update_fields=["face_encoding"])
                    print(f"[Caching] Generated and cached face encoding for {profile.first_name}")
            except Exception as e:
                print(f"[Caching] Error calculating encoding for {profile.first_name}: {e}")
                continue
                
        if profile.face_encoding:
            known_face_encodings.append(np.array(profile.face_encoding))
            name_key = f"{profile.image}"[:-4]
            known_face_names.append(name_key)
            
    return known_face_encodings, known_face_names


def find_shift_checkin(profile, now_dt):
    """
    Finds if the employee is checking in within a valid shift window.
    Returns (schedule_obj_or_default, status, shift_date) if inside a window,
    otherwise (None, None, None).
    """
    day_abbr = now_dt.strftime("%a").lower()[:3]
    is_weekday = day_abbr in ["mon", "tue", "wed", "thu", "fri"]
    
    day_query = [day_abbr]
    if is_weekday:
        day_query.append("mon_fri")
        
    schedules = Schedule.objects.filter(profile=profile, day_of_week__in=day_query)
    
    today = now_dt.date()
    
    def check_window(s, start_date):
        start_time = s.start_time if isinstance(s, Schedule) else profile.shift
        end_time = s.end_time if isinstance(s, Schedule) else profile.shift_end
        grace_mins = s.grace_period_minutes if isinstance(s, Schedule) else 15
        
        start_dt = datetime.combine(start_date, start_time)
        if start_time > end_time:
            end_dt = datetime.combine(start_date, end_time) + timedelta(days=1)
        else:
            end_dt = datetime.combine(start_date, end_time)
            
        checkin_start = start_dt - timedelta(minutes=15)
        
        if checkin_start <= now_dt <= end_dt:
            # We are inside! Calculate status:
            grace_cutoff = start_dt + timedelta(minutes=grace_mins)
            status = "on_time" if now_dt <= grace_cutoff else "late"
            return True, status, start_date
            
        return False, None, None

    for s in schedules:
        ok, status, s_date = check_window(s, today)
        if ok:
            return s, status, s_date
            
        if s.start_time > s.end_time:
            ok, status, s_date = check_window(s, today - timedelta(days=1))
            if ok:
                return s, status, s_date

    if not schedules.exists() and profile.shift and profile.shift_end:
        ok, status, s_date = check_window("profile_default", today)
        if ok:
            return "profile_default", status, s_date
            
        if profile.shift > profile.shift_end:
            ok, status, s_date = check_window("profile_default", today - timedelta(days=1))
            if ok:
                return "profile_default", status, s_date

    return None, None, None


def scan(request):
    global last_face

    print(f"\n[Scanner] Loading profile encodings from database...")
    known_face_encodings, known_face_names = get_known_face_encodings()
    print(f"[Scanner] Total profiles successfully loaded for scanning: {len(known_face_encodings)}")


    video_capture = cv2.VideoCapture(0)
    if not video_capture.isOpened():
        print("[Scanner] Error: Could not open webcam.")
        return HttpResponse("Error: Could not open webcam. Make sure it is connected and not used by another application.")

    face_locations = []
    face_encodings = []
    face_names = []
    process_this_frame = True

    print("[Scanner] Scanner started! Press 'Enter' key on the video window to exit.")

    while True:
        ret, frame = video_capture.read()
        if not ret:
            print("[Scanner] Error: Failed to capture image from camera.")
            break

        # Resize frame of video to 1/4 size for faster face recognition processing
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        # Convert the image from BGR color (which OpenCV uses) to RGB color (which face_recognition uses)
        rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

        if process_this_frame:
            face_locations = face_recognition.face_locations(rgb_small_frame)
            face_encodings = face_recognition.face_encodings(
                rgb_small_frame, face_locations
            )

            face_names = []
            for face_encoding in face_encodings:
                name = "Unknown"
                display_name = "Unknown"

                if len(known_face_encodings) > 0:
                    # Calculate face distances to all known profiles
                    face_distances = face_recognition.face_distance(
                        known_face_encodings, face_encoding
                    )
                    best_match_index = np.argmin(face_distances)
                    min_distance = face_distances[best_match_index]

                    # Standard threshold is 0.6. Under 0.6 is a match.
                    is_match = min_distance <= 0.6

                    # Print matching metrics to terminal console for debugging
                    try:
                        profile_temp = Profile.objects.get(Q(image__icontains=known_face_names[best_match_index]))
                        closest_name = f"{profile_temp.first_name} {profile_temp.last_name}"
                    except Exception:
                        closest_name = known_face_names[best_match_index]

                    print(f"[Scanner] Face detected! Closest profile: '{closest_name}' | Distance: {min_distance:.3f} | Match: {is_match}")

                    if is_match:
                        name = known_face_names[best_match_index]

                        try:
                            profile = Profile.objects.get(Q(image__icontains=name))
                            display_name = f"{profile.first_name} {profile.last_name} ({min_distance:.2f})"
                            
                            if not profile.present:
                                profile.present = True
                                profile.save()
                                print(f"[Scanner] Marked '{profile.first_name} {profile.last_name}' as PRESENT!")

                            # --- Schedule-based check-in window ---
                            matched_schedule, status, shift_date = find_shift_checkin(profile, now)

                            if matched_schedule:
                                db_schedule = matched_schedule if isinstance(matched_schedule, Schedule) else None
                                if not profile.present:
                                    profile.present = True
                                    profile.save()
                                    print(f"[Scanner] Marked '{profile.first_name} {profile.last_name}' as PRESENT!")

                                AttendanceRecord.objects.get_or_create(
                                    profile=profile,
                                    schedule=db_schedule,
                                    date=now.date(),
                                    defaults={
                                        "scan_time": now.time(),
                                        "status": status,
                                    },
                                )
                                print(f"[Scanner] Attendance record updated for '{profile.first_name}' (status: {status})")
                            else:
                                print(f"[Scanner] Scanned '{profile.first_name}' outside scheduled shift hours. Skipping attendance.")
                            # --- End schedule-based late detection ---

                            if last_face != name:
                                last_face_obj = LastFace(last_face=name)
                                last_face_obj.save()
                                last_face = name
                                if winsound and sound:
                                    try:
                                        winsound.PlaySound(sound, winsound.SND_ASYNC)
                                    except Exception as sound_err:
                                        print(f"[Scanner] Sound playback error: {sound_err}")
                        except Exception as db_err:
                            print(f"[Scanner] Error querying database for profile '{name}': {db_err}")
                            display_name = f"{name} ({min_distance:.2f})"
                    else:
                        display_name = f"Unknown ({min_distance:.2f})"
                else:
                    display_name = "No Profiles"

                face_names.append(display_name)

        process_this_frame = not process_this_frame

        # Display the results
        for (top, right, bottom, left), name in zip(face_locations, face_names):
            # Scale back up face locations since the frame we detected in was scaled to 1/4 size
            top *= 4
            right *= 4
            bottom *= 4
            left *= 4

            # Draw a box around the face
            # Use Green for recognized, Red for Unknown
            box_color = (0, 255, 0) if "Unknown" not in name and "No Profiles" not in name else (0, 0, 255)
            cv2.rectangle(frame, (left, top), (right, bottom), box_color, 2)

            # Draw a label with a name below the face
            cv2.rectangle(
                frame, (left, bottom - 35), (right, bottom), box_color, cv2.FILLED
            )
            font = cv2.FONT_HERSHEY_DUPLEX
            cv2.putText(
                frame, name, (left + 6, bottom - 6), font, 0.5, (255, 255, 255), 1
            )

        # Display the resulting image
        cv2.imshow("Video", frame)

        # Hit Enter on the keyboard to stop! (13 is Enter key)
        if cv2.waitKey(1) & 0xFF == 13:
            break

    video_capture.release()
    cv2.destroyAllWindows()
    return HttpResponse("Scanner closed")


def profiles(request):
    profiles = Profile.objects.all()
    context = {"profiles": profiles}
    return render(request, "core/profiles.html", context)


def details(request):
    context = {"profile": None, "last_face": None}
    return render(request, "core/details.html", context)


def add_profile(request):
    form = ProfileForm
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect("profiles")
    context = {"form": form}
    return render(request, "core/add_profile.html", context)


def edit_profile(request, id):
    profile = Profile.objects.get(id=id)
    form = ProfileForm(instance=profile)
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=profile)
        if form.is_valid():
            form.save()
            return redirect("profiles")
    context = {"form": form}
    return render(request, "core/add_profile.html", context)


def delete_profile(request, id):
    profile = Profile.objects.get(id=id)
    profile.delete()
    return redirect("profiles")


def clear_history(request):
    history = LastFace.objects.all()
    history.delete()
    return redirect("index")


def reset(request):
    # Delete today's attendance records
    today = datetime.now().date()
    AttendanceRecord.objects.filter(date=today).delete()

    profiles = Profile.objects.all()
    for profile in profiles:
        if profile.present == True:
            profile.present = False
            profile.save()
    return redirect("index")



# =============================================
# Schedule Management Views
# =============================================


def schedules(request):
    """List all schedule entries, grouped by day."""
    all_schedules = Schedule.objects.select_related("profile", "subject").all()

    # Group schedules by day
    day_order = ["mon_fri", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    day_labels = dict(Schedule.DAY_CHOICES)
    grouped = {}
    for day in day_order:
        day_schedules = [s for s in all_schedules if s.day_of_week == day]
        if day_schedules:
            grouped[day_labels[day]] = day_schedules

    context = {"grouped_schedules": grouped}
    return render(request, "core/schedules.html", context)


def add_schedule(request):
    """Add a new schedule slot."""
    form = ScheduleForm()
    if request.method == "POST":
        form = ScheduleForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("schedules")
    context = {"form": form, "title": "Add Schedule"}
    return render(request, "core/add_schedule.html", context)


def edit_schedule(request, id):
    """Edit an existing schedule slot."""
    schedule = get_object_or_404(Schedule, id=id)
    form = ScheduleForm(instance=schedule)
    if request.method == "POST":
        form = ScheduleForm(request.POST, instance=schedule)
        if form.is_valid():
            form.save()
            return redirect("schedules")
    context = {"form": form, "title": "Edit Schedule"}
    return render(request, "core/add_schedule.html", context)


def delete_schedule(request, id):
    """Delete a schedule slot."""
    schedule = get_object_or_404(Schedule, id=id)
    schedule.delete()
    return redirect("schedules")


def add_subject(request):
    """Add a new subject."""
    form = SubjectForm()
    if request.method == "POST":
        form = SubjectForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("schedules")
    subjects = Subject.objects.all()
    context = {"form": form, "subjects": subjects}
    return render(request, "core/add_subject.html", context)


def attendance_report(request):
    """View attendance records with filtering."""
    records = AttendanceRecord.objects.select_related(
        "profile", "schedule", "schedule__subject"
    ).all()

    # Optional filters
    status_filter = request.GET.get("status", "")
    date_filter = request.GET.get("date", "")
    profile_filter = request.GET.get("profile", "")

    if status_filter:
        records = records.filter(status=status_filter)
    if date_filter:
        records = records.filter(date=date_filter)
    if profile_filter:
        records = records.filter(
            Q(profile__first_name__icontains=profile_filter)
            | Q(profile__last_name__icontains=profile_filter)
        )

    # Stats
    total = records.count()
    on_time_count = records.filter(status="on_time").count()
    late_count = records.filter(status="late").count()
    absent_count = records.filter(status="absent").count()

    all_profiles = Profile.objects.all()

    context = {
        "records": records[:100],  # Limit to 100 most recent
        "total": total,
        "on_time_count": on_time_count,
        "late_count": late_count,
        "absent_count": absent_count,
        "status_filter": status_filter,
        "date_filter": date_filter,
        "profile_filter": profile_filter,
        "all_profiles": all_profiles,
    }
    return render(request, "core/attendance_report.html", context)


@csrf_exempt
def scan_frame(request):
    """
    Receives base64 image frame from the browser, runs face recognition,
    updates attendance/schedule status, and returns JSON.
    """
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "Only POST allowed"}, status=400)
    
    try:
        data = json.loads(request.body)
        image_data = data.get("image", "")
        if not image_data:
            return JsonResponse({"success": False, "error": "No image data"}, status=400)
            
        header, encoded = image_data.split(",", 1)
        decoded = base64.b64decode(encoded)
        image_file = io.BytesIO(decoded)
        img = Image.open(image_file)
        frame = np.array(img.convert("RGB"))
        
        # Load known faces from database (pre-computed/cached)
        known_face_encodings, known_face_names = get_known_face_encodings()
        
        # Resize frame of video to 1/4 size for faster face recognition processing
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        
        # Detect faces in the uploaded frame
        face_locations = face_recognition.face_locations(small_frame)
        face_encodings = face_recognition.face_encodings(small_frame, face_locations)
        
        results = []
        for face_location, face_encoding in zip(face_locations, face_encodings):
            name = "Unknown"
            display_name = "Unknown"
            distance = 1.0
            matched = False
            status = ""
            profile = None
            
            if len(known_face_encodings) > 0:
                face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)
                best_match_index = np.argmin(face_distances)
                distance = float(face_distances[best_match_index])
                
                # Standard threshold is 0.6. Under 0.6 is a match.
                is_match = distance <= 0.6
                
                if is_match:
                    matched = True
                    name = known_face_names[best_match_index]
                    
                    try:
                        profile = Profile.objects.get(Q(image__icontains=name))
                        display_name = f"{profile.first_name} {profile.last_name}"
                        
                        # --- 1. Already Checked-in Check ---
                        now = datetime.now()
                        today = now.date()
                        existing_record = AttendanceRecord.objects.filter(profile=profile, date=today).first()
                        
                        if existing_record:
                            scan_time_str = existing_record.scan_time.strftime("%I:%M %p") if existing_record.scan_time else ""
                            results.append({
                                "matched": True,
                                "name": display_name,
                                "distance": round(distance, 3),
                                "status": existing_record.status,
                                "already_checked_in": True,
                                "scan_time": scan_time_str,
                                "profile_id": profile.id,
                                "box": {
                                    "top": face_location[0] * 4,
                                    "right": face_location[1] * 4,
                                    "bottom": face_location[2] * 4,
                                    "left": face_location[3] * 4
                                }
                            })
                            continue
                        
                        # --- 2. If not already checked in today ---
                        if not profile.present:
                            profile.present = True
                            profile.save()
                            print(f"[scan_frame] Marked {display_name} as PRESENT!")
                            
                        # --- Schedule-based check-in window ---
                        matched_schedule, status, shift_date = find_shift_checkin(profile, now)
                        
                        if not matched_schedule:
                            results.append({
                                "matched": True,
                                "name": display_name,
                                "distance": round(distance, 3),
                                "status": "outside_shift",
                                "already_checked_in": False,
                                "outside_shift": True,
                                "profile_id": profile.id,
                                "box": {
                                    "top": face_location[0] * 4,
                                    "right": face_location[1] * 4,
                                    "bottom": face_location[2] * 4,
                                    "left": face_location[3] * 4
                                }
                            })
                            continue
                            
                        db_schedule = matched_schedule if isinstance(matched_schedule, Schedule) else None
                        
                        if not profile.present:
                            profile.present = True
                            profile.save()
                            print(f"[scan_frame] Marked {display_name} as PRESENT!")
                            
                        AttendanceRecord.objects.get_or_create(
                            profile=profile,
                            schedule=db_schedule,
                            date=now.date(),
                            defaults={
                                "scan_time": now.time(),
                                "status": status,
                            },
                        )
                        print(f"[scan_frame] Attendance record: {status}")
                        # --- End schedule-based late detection ---
                        
                        # Play beep sound
                        global last_face
                        if last_face != name:
                            last_face = name
                            # Save last face to DB so index view shows it
                            LastFace.objects.create(last_face=name)
                            if winsound and sound:
                                try:
                                    winsound.PlaySound(sound, winsound.SND_ASYNC)
                                except Exception as sound_err:
                                    print(f"[scan_frame] Sound playback error: {sound_err}")
                                    
                    except Exception as db_err:
                        print(f"[scan_frame] Error querying DB for '{name}': {db_err}")
                        display_name = f"DB Error ({name})"
            
            # Convert face_location coordinates (top, right, bottom, left) to JS-friendly format (scaled back up)
            results.append({
                "matched": matched,
                "name": display_name,
                "distance": round(distance, 3),
                "status": status,
                "already_checked_in": False,
                "profile_id": profile.id if profile else None,
                "box": {
                    "top": face_location[0] * 4,
                    "right": face_location[1] * 4,
                    "bottom": face_location[2] * 4,
                    "left": face_location[3] * 4
                }
            })
            
        return JsonResponse({"success": True, "results": results})
        
    except Exception as err:
        print(f"[scan_frame] Exception: {err}")
        return JsonResponse({"success": False, "error": str(err)}, status=500)


def profile_detail(request, id):
    """
    Displays a single employee's profile page with their details,
    full check-in logs, and dynamic evaluation rating.
    """
    p = get_object_or_404(Profile.objects.select_related("department"), id=id)
    
    # Get all attendance records for this profile
    records = AttendanceRecord.objects.filter(profile=p).order_by("-date", "-scan_time")
    
    # Calculate dynamic rating
    total_records = records.count()
    if total_records > 0:
        on_time_count = records.filter(status="on_time").count()
        late_count = records.filter(status="late").count()
        
        # Formula: (On Time + 0.5 * Late) / Total * 10
        rating = ((on_time_count + 0.5 * late_count) / total_records) * 10
        rating = round(rating, 1)
    else:
        rating = float(p.ranking or 0)
        
    p.evaluation_rating = rating
    p.rating_percentage = int(rating * 10)
    p.checkin_history = records
    
    # Fetch active Monday-Friday schedule start and end times for detail display
    schedule_slot = p.schedules.filter(day_of_week="mon_fri").first()
    
    context = {
        "profile": p,
        "schedule_slot": schedule_slot,
    }
    return render(request, "core/profile_detail.html", context)
