from django.shortcuts import render, redirect
from django.db import connection
from django.http import HttpResponse, HttpResponseForbidden
from django.db.utils import OperationalError
from datetime import date
from django.core.files.storage import FileSystemStorage
from django.conf import settings
from django.http import JsonResponse
from django.contrib import messages
import random
from datetime import datetime, timedelta
import openpyxl
from django.utils import timezone
from django.core.mail import send_mail
import pandas as pd
# =========================
# AUTH & SESSION
# =========================

def splash_view(request):
    return render(request, 'splash.html')
    
def register_request_view(request):
    if request.method == 'POST':
        name = request.POST['name']
        email = request.POST['email']
        role = request.POST['role']
        department_id = request.POST['department_id']
        class_id = request.POST.get('class_id') or None
        semester_id = request.POST.get('semester_id') or None

        with connection.cursor() as cursor:
            cursor.callproc(
                'submit_registration_request',
                [name, email, role, department_id, class_id, semester_id]
            )

        return render(request, 'register_success.html')

    with connection.cursor() as cursor:
        cursor.execute("SELECT department_id, department_name FROM departments")
        departments = cursor.fetchall()

        cursor.execute("SELECT class_id, class_name FROM classes")
        classes = cursor.fetchall()

        cursor.execute("SELECT semester_id, semester_number FROM semesters")
        semesters = cursor.fetchall()

    return render(request, 'register.html', {
        'departments': departments,
        'classes': classes,
        'semesters': semesters
    })

def admin_registration_requests_view(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    role_filter = request.GET.get('role', '')
    sort_order = request.GET.get('sort', 'desc')  # default newest first

    query = """
        SELECT r.request_id,
               r.name,
               r.email,
               r.role,
               d.department_name,
               c.class_name,
               s.semester_number,
               r.status,
               r.requested_at
        FROM registration_requests r
        LEFT JOIN departments d ON r.department_id = d.department_id
        LEFT JOIN classes c ON r.class_id = c.class_id
        LEFT JOIN semesters s ON r.semester_id = s.semester_id
        WHERE r.status = 'PENDING'
    """

    params = []

    if role_filter in ('STUDENT', 'FACULTY'):
        query += " AND r.role = %s"
        params.append(role_filter)

    # 🔥 Safe sorting logic
    if sort_order == 'asc':
        query += " ORDER BY r.requested_at ASC"
    else:
        query += " ORDER BY r.requested_at DESC"

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        requests_list = cursor.fetchall()

    return render(request, 'admin_registration_requests.html', {
        'requests': requests_list,
        'selected_role': role_filter,
        'selected_sort': sort_order
    })


def approve_registration_view(request, request_id):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    with connection.cursor() as cursor:
        # 1️⃣ Get email first (needed to fetch user_id later)
        cursor.execute("""
            SELECT email
            FROM registration_requests
            WHERE request_id = %s AND status = 'PENDING'
        """, [request_id])

        row = cursor.fetchone()
        if not row:
            return redirect('admin_registration_requests')

        email = row[0]

        # 2️⃣ Call existing procedure (creates user + updates request)
        cursor.callproc('approve_registration_request', [request_id])

        # 3️⃣ Fetch newly created user_id
        cursor.execute("""
            SELECT user_id
            FROM users
            WHERE email = %s
        """, [email])

        user_row = cursor.fetchone()
        if not user_row:
            return redirect('admin_registration_requests')

        user_id = user_row[0]

        # 4️⃣ Create profile (SAFE – no duplicates)
        cursor.execute("""
            INSERT IGNORE INTO user_profiles (user_id)
            VALUES (%s)
        """, [user_id])

    return redirect('admin_registration_requests') 

def profile_view(request):
    if 'user_id' not in request.session:
        return redirect('login')

    user_id = request.session['user_id']

    with connection.cursor() as cursor:
        # 🔹 USER CORE DETAILS
        cursor.execute("""
            SELECT name, email, role
            FROM users
            WHERE user_id = %s
        """, [user_id])
        user = cursor.fetchone()

        # 🔹 PROFILE DETAILS
        cursor.execute("""
            SELECT profile_photo, phone, address, bio
            FROM user_profiles
            WHERE user_id = %s
        """, [user_id])
        profile = cursor.fetchone()

        # 🔹 EMERGENCY CONTACTS
        cursor.execute("""
            SELECT emergency_contact_id, contact_name, contact_phone
            FROM emergency_contacts
            WHERE user_id = %s
        """, [user_id])
        emergency_contacts = cursor.fetchall()

    return render(request, 'profile.html', {
        'user': user,
        'profile': profile,
        'emergency_contacts': emergency_contacts,
        'can_add_contact': len(emergency_contacts) < 2
    })

def view_student_profile(request, student_id):
    if 'user_id' not in request.session:
        return redirect('login')

    if request.session.get('role') != 'ADMIN':
        return redirect('admin_dashboard')

    with connection.cursor() as cursor:

        # 🔹 CORE USER + STUDENT DETAILS
        cursor.execute("""
            SELECT 
                u.user_id,
                u.name,
                u.email,
                u.role,
                u.is_active,
                u.created_at,
                d.department_name,
                c.class_name,
                u.semester_id
            FROM users u
            LEFT JOIN departments d ON u.department_id = d.department_id
            LEFT JOIN classes c ON u.class_id = c.class_id
            WHERE u.user_id = %s AND u.role = 'STUDENT'
        """, [student_id])

        user = cursor.fetchone()

        if not user:
            return redirect('admin_students_list')

        # 🔹 PROFILE DETAILS
        cursor.execute("""
            SELECT profile_photo, phone, address, bio
            FROM user_profiles
            WHERE user_id = %s
        """, [student_id])

        profile = cursor.fetchone()

        # 🔹 EMERGENCY CONTACTS
        cursor.execute("""
            SELECT emergency_contact_id, contact_name, contact_phone
            FROM emergency_contacts
            WHERE user_id = %s
        """, [student_id])

        emergency_contacts = cursor.fetchall()

    return render(request, 'view_user_profile.html', {
        'user': user,
        'profile': profile,
        'emergency_contacts': emergency_contacts,
        'user_type': 'Student',
        'is_admin_view': True
    })
    

def view_faculty_profile(request, faculty_id):
    if 'user_id' not in request.session:
        return redirect('login')

    if request.session.get('role') != 'ADMIN':
        return redirect('admin_dashboard')

    with connection.cursor() as cursor:

        # 🔹 CORE USER + FACULTY DETAILS
        cursor.execute("""
            SELECT 
                u.user_id,
                u.name,
                u.email,
                u.role,
                u.is_active,
                u.created_at,
                d.department_name
            FROM users u
            LEFT JOIN departments d ON u.department_id = d.department_id
            WHERE u.user_id = %s AND u.role = 'FACULTY'
        """, [faculty_id])

        user = cursor.fetchone()

        if not user:
            return redirect('admin_all_faculty')

        # 🔹 PROFILE DETAILS
        cursor.execute("""
            SELECT profile_photo, phone, address, bio
            FROM user_profiles
            WHERE user_id = %s
        """, [faculty_id])

        profile = cursor.fetchone()

        # 🔹 EMERGENCY CONTACTS
        cursor.execute("""
            SELECT emergency_contact_id, contact_name, contact_phone
            FROM emergency_contacts
            WHERE user_id = %s
        """, [faculty_id])

        emergency_contacts = cursor.fetchall()

    return render(request, 'view_user_profile.html', {
        'user': user,
        'profile': profile,
        'emergency_contacts': emergency_contacts,
        'user_type': 'Faculty',
        'is_admin_view': True
    })

#add emergency contacts view
from django.contrib import messages

def add_emergency_contact_view(request):
    if 'user_id' not in request.session:
        return redirect('login')

    user_id = request.session['user_id']

    # Check count
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM emergency_contacts
            WHERE user_id = %s
        """, [user_id])
        count = cursor.fetchone()[0]

    if count >= 2:
        messages.error(request, "You can add maximum 2 emergency contacts.")
        return redirect('profile')

    if request.method == 'POST':
        name = request.POST.get('contact_name', '').strip()
        phone = request.POST.get('contact_phone', '').strip()

        # ✅ Validation
        if not phone.isdigit() or len(phone) != 10:
            messages.error(request, "Emergency contact must be exactly 10 digits.")
            return redirect('add_emergency_contact')

        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO emergency_contacts (user_id, contact_name, contact_phone)
                VALUES (%s, %s, %s)
            """, [user_id, name, phone])

        messages.success(request, "Emergency contact added.")
        return redirect('profile')

    return render(request, 'add_emergency_contact.html')


# delete emergency contact
def delete_emergency_contact_view(request, contact_id):
    if 'user_id' not in request.session:
        return redirect('login')

    user_id = request.session['user_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            DELETE FROM emergency_contacts
            WHERE emergency_contact_id = %s
              AND user_id = %s
        """, [contact_id, user_id])

    messages.success(request, "Emergency contact removed.")
    return redirect('profile')

def edit_profile_view(request):
    if 'user_id' not in request.session:
        return redirect('login')

    user_id = request.session['user_id']
    role = request.session['role']

    # 🔹 Fetch existing profile
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT profile_photo, phone, address, bio
            FROM user_profiles
            WHERE user_id = %s
        """, [user_id])
        profile = cursor.fetchone()

    if request.method == 'POST':
        phone = request.POST.get('phone', '').strip()
        address = request.POST.get('address', '').strip()
        bio = request.POST.get('bio', '').strip()

        # ✅ PHONE VALIDATION (only if provided)
        if phone and (not phone.isdigit() or len(phone) != 10):
            messages.error(request, "Phone number must contain exactly 10 digits.")
            return redirect('edit_profile')

        # 📸 Profile photo
        photo = request.FILES.get('profile_photo')
        photo_path = profile[0] if profile else None

        if photo:
            fs = FileSystemStorage(location='media/profiles')
            filename = fs.save(photo.name, photo)
            photo_path = f'profiles/{filename}'

        # 🧠 Preserve existing values if field left empty
        final_phone = phone if phone else (profile[1] if profile else None)
        final_address = address if address else (profile[2] if profile else None)
        final_bio = bio if bio else (profile[3] if profile else None)

        # 🔄 Insert / Update
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO user_profiles
                    (user_id, profile_photo, phone, address, bio)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    profile_photo = VALUES(profile_photo),
                    phone = VALUES(phone),
                    address = VALUES(address),
                    bio = VALUES(bio)
            """, [
                user_id,
                photo_path,
                final_phone,
                final_address,
                final_bio
            ])

        messages.success(request, "Profile updated successfully.")
        return redirect('profile')

    return render(request, 'edit_profile.html', {
        'profile': profile,
        'role': role
    })

def reject_registration_view(request, request_id):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    with connection.cursor() as cursor:
        cursor.callproc('reject_registration_request', [request_id])

    return redirect('admin_registration_requests')


def generate_otp():
    return str(random.randint(100000, 999999))

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')

        with connection.cursor() as cursor:
            # 1️⃣ Check user exists & active
            cursor.execute("""
                SELECT user_id, role, department_id, is_active
                FROM users
                WHERE email = %s
            """, [email])
            user = cursor.fetchone()

            if not user:
                return render(request, 'login.html', {
                    'error': 'User does not exist'
                })

            user_id, role, department_id, is_active = user

            if not is_active:
                return render(request, 'login.html', {
                    'error': 'User is deactivated'
                })

            # ==============================
            # 🔐 ADMIN → NO OTP
            # ==============================
            if role == 'ADMIN':
                request.session.flush()
                request.session['user_id'] = user_id
                request.session['role'] = role
                request.session['department_id'] = department_id

                return redirect('admin_dashboard')

            # ==============================
            # 🔐 FACULTY / STUDENT → OTP
            # ==============================

            # generate OTP
            otp_code = str(random.randint(100000, 999999))
            expires_at = timezone.now() + timedelta(minutes=5)

            # invalidate old OTPs
            cursor.execute("""
                UPDATE login_otps
                SET is_used = 1
                WHERE user_id = %s
            """, [user_id])

            # insert new OTP
            cursor.execute("""
                INSERT INTO login_otps (user_id, otp_code, expires_at)
                VALUES (%s, %s, %s)
            """, [user_id, otp_code, expires_at])

        # ✉ Send OTP email
        send_mail(
            subject='CampusOne Login OTP',
            message=f'Your OTP is {otp_code}. It is valid for 5 minutes.',
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
            fail_silently=False
        )

        # store email temporarily
        request.session['otp_email'] = email

        return redirect('verify_otp')

    return render(request, 'login.html')

def verify_otp_view(request):
    email = request.session.get('otp_email')

    if not email:
        return redirect('login')

    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '').strip()

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    u.user_id,
                    u.role,
                    u.department_id,
                    o.otp_id,
                    o.expires_at
                FROM login_otps o
                JOIN users u ON o.user_id = u.user_id
                WHERE u.email = %s
                  AND o.otp_code = %s
                  AND o.is_used = 0
                ORDER BY o.otp_id DESC
                LIMIT 1
            """, [email, entered_otp])

            row = cursor.fetchone()

        if not row:
            return render(request, 'verify_otp.html', {
                'error': 'Invalid OTP'
            })

        user_id, role, department_id, otp_id, expires_at = row

        # 🕒 FIX: make DB datetime timezone-aware
        expires_at = timezone.make_aware(expires_at)

        if timezone.now() > expires_at:
            return render(request, 'verify_otp.html', {
                'error': 'OTP expired. Please login again.'
            })

        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE login_otps
                SET is_used = 1
                WHERE otp_id = %s
            """, [otp_id])

        request.session.flush()
        request.session['user_id'] = user_id
        request.session['role'] = role
        request.session['department_id'] = department_id

        if role == 'FACULTY':
            return redirect('faculty_dashboard')
        else:
            return redirect('student_dashboard')

    return render(request, 'verify_otp.html')

def resend_otp_view(request):
    email = request.session.get('otp_email')

    if not email:
        messages.error(request, 'Session expired. Please login again.')
        return redirect('login')

    # Generate new OTP
    new_otp = str(random.randint(100000, 999999))
    expires_at = timezone.now() + timedelta(minutes=5)

    with connection.cursor() as cursor:
        # Mark all previous OTPs for this user as used/expired
        cursor.execute("""
            UPDATE login_otps
            SET is_used = 1
            WHERE user_id = (SELECT user_id FROM users WHERE email = %s)
        """, [email])

        # Insert new OTP
        cursor.execute("""
            INSERT INTO login_otps (user_id, otp_code, expires_at)
            SELECT user_id, %s, %s
            FROM users
            WHERE email = %s
        """, [new_otp, expires_at, email])

    # Send email
    try:
        send_mail(
            subject='New OTP for CampusOne Login',
            message=f'Your new OTP is: {new_otp}\n\nThis code will expire in 5 minutes.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
        messages.success(request, 'New OTP sent to your email!')
    except Exception as e:
        messages.error(request, 'Failed to send OTP. Please try again.')
        print(f"Email error: {e}")

    return redirect('verify_otp')


def logout_view(request):
    request.session.flush()
    return redirect('login')

def bulk_user_upload_view(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    if request.method == 'POST':
        excel_file = request.FILES.get('file')

        if not excel_file:
            return render(request, 'bulk_user_upload.html', {
                'error': 'Please upload an Excel file'
            })

        try:
            df = pd.read_excel(excel_file)
        except Exception:
            return render(request, 'bulk_user_upload.html', {
                'error': 'Invalid Excel file'
            })

        # Counters
        total_rows = 0
        inserted = 0
        duplicates = 0
        invalid = 0

        for _, row in df.iterrows():
            total_rows += 1

            name = str(row.get('name', '')).strip()
            email = str(row.get('email', '')).strip()
            role = str(row.get('role', '')).strip().upper()

            department_id = row.get('department_id')
            class_id = row.get('class_id')
            semester_id = row.get('semester_id')

            # 🔴 Basic validation
            if not name or not email or role not in ['STUDENT', 'FACULTY']:
                invalid += 1
                continue

            if not department_id:
                invalid += 1
                continue

            if role == 'STUDENT' and (pd.isna(class_id) or pd.isna(semester_id)):
                invalid += 1
                continue

            with connection.cursor() as cursor:
                # 🔁 Duplicate check
                cursor.execute(
                    "SELECT 1 FROM users WHERE email = %s",
                    [email]
                )
                if cursor.fetchone():
                    duplicates += 1
                    continue

                # ✅ Insert user
                cursor.execute("""
                    INSERT INTO users
                    (name, email, role, department_id, class_id, semester_id, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, 1)
                """, [
                    name,
                    email,
                    role,
                    department_id,
                    class_id if role == 'STUDENT' else None,
                    semester_id if role == 'STUDENT' else None
                ])

                inserted += 1

        return render(request, 'bulk_upload_result.html', {
            'total': total_rows,
            'inserted': inserted,
            'duplicates': duplicates,
            'invalid': invalid
        })

    return render(request, 'bulk_user_upload.html')

#notification helper
def create_notification(user_id, title, message, link=None):
    with connection.cursor() as cursor:
        cursor.execute("""
            INSERT INTO notifications (user_id, title, message, link)
            VALUES (%s, %s, %s, %s)
        """, [user_id, title, message, link])


def get_unread_notification_count(user_id):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM notifications
            WHERE user_id = %s AND is_read = 0
        """, [user_id])
        return cursor.fetchone()[0]

def get_user_notifications(user_id):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                notification_id,
                title,
                message,
                link,
                is_read,
                created_at
            FROM notifications
            WHERE user_id = %s
            ORDER BY created_at DESC
        """, [user_id])
        return cursor.fetchall()



def mark_all_notifications_read(request):
    if not request.session.get('user_id'):
        return redirect('login')

    user_id = request.session['user_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            UPDATE notifications
            SET is_read = 1
            WHERE user_id = %s
        """, [user_id])

    return redirect('notifications')


def delete_notification(request, notification_id):
    if not request.session.get('user_id'):
        return redirect('login')

    user_id = request.session['user_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            DELETE FROM notifications
            WHERE notification_id = %s
              AND user_id = %s
        """, [notification_id, user_id])

    return redirect('notifications')

def get_event_notification_users(event_id):
    with connection.cursor() as cursor:
        # Get event scope
        cursor.execute("""
            SELECT department_id, semester_id, faculty_incharge_id
            FROM events
            WHERE event_id = %s
        """, [event_id])

        event = cursor.fetchone()
        if not event:
            return []

        department_id, semester_id, faculty_incharge_id = event

        users = set()

        # ✅ ADMINS (always)
        cursor.execute("""
            SELECT user_id FROM users WHERE role = 'ADMIN' AND is_active = 1
        """)
        users.update(uid for (uid,) in cursor.fetchall())

        # ✅ FACULTY IN-CHARGE
        if faculty_incharge_id:
            users.add(faculty_incharge_id)

        # ✅ STUDENT COORDINATORS
        cursor.execute("""
            SELECT student_id
            FROM event_coordinators
            WHERE event_id = %s
        """, [event_id])
        users.update(uid for (uid,) in cursor.fetchall())

        # ✅ SCOPE USERS
        if department_id is None:
            # GLOBAL
            cursor.execute("""
                SELECT user_id FROM users
                WHERE is_active = 1 AND role IN ('STUDENT','FACULTY')
            """)
        elif semester_id is None:
            # DEPARTMENT
            cursor.execute("""
                SELECT user_id FROM users
                WHERE is_active = 1
                  AND department_id = %s
            """, [department_id])
        else:
            # DEPT + SEM
            cursor.execute("""
                SELECT user_id FROM users
                WHERE is_active = 1
                  AND department_id = %s
                  AND semester_id = %s
            """, [department_id, semester_id])

        users.update(uid for (uid,) in cursor.fetchall())

        return list(users)

def get_assignment_notification_users(assignment_id, event='CREATE'):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT department_id, semester_id, faculty_id
            FROM assignments
            WHERE assignment_id = %s
        """, [assignment_id])

        row = cursor.fetchone()
        if not row:
            return []

        department_id, semester_id, faculty_id = row
        users = set()

        # ✅ ADMINS
        cursor.execute("""
            SELECT user_id FROM users
            WHERE role = 'ADMIN' AND is_active = 1
        """)
        users.update(uid for (uid,) in cursor.fetchall())

        if event == 'CREATE':
            # 🎓 STUDENTS
            if department_id is None:
                cursor.execute("""
                    SELECT user_id FROM users
                    WHERE role = 'STUDENT' AND is_active = 1
                """)
            elif semester_id is None:
                cursor.execute("""
                    SELECT user_id FROM users
                    WHERE role = 'STUDENT'
                      AND department_id = %s
                      AND is_active = 1
                """, [department_id])
            else:
                cursor.execute("""
                    SELECT user_id FROM users
                    WHERE role = 'STUDENT'
                      AND department_id = %s
                      AND semester_id = %s
                      AND is_active = 1
                """, [department_id, semester_id])

            users.update(uid for (uid,) in cursor.fetchall())

        elif event == 'SUBMIT':
            # 👨‍🏫 FACULTY
            if faculty_id:
                users.add(faculty_id)

        return list(users)

def get_notice_users(notice_id):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT department_id, semester_id
            FROM notices
            WHERE notice_id = %s
        """, [notice_id])

        row = cursor.fetchone()
        if not row:
            return []

        department_id, semester_id = row
        users = set()

        # 👑 ADMINS always
        cursor.execute("""
            SELECT user_id
            FROM users
            WHERE role = 'ADMIN' AND is_active = 1
        """)
        users.update(uid for (uid,) in cursor.fetchall())

        # 🌍 GLOBAL
        if department_id is None:
            cursor.execute("""
                SELECT user_id
                FROM users
                WHERE is_active = 1
            """)
        # 🏫 DEPARTMENT
        elif semester_id is None:
            cursor.execute("""
                SELECT user_id
                FROM users
                WHERE is_active = 1
                  AND department_id = %s
            """, [department_id])
        # 🎓 DEPT + SEM
        else:
            cursor.execute("""
                SELECT user_id
                FROM users
                WHERE is_active = 1
                  AND department_id = %s
                  AND semester_id = %s
            """, [department_id, semester_id])

        users.update(uid for (uid,) in cursor.fetchall())
        return list(users)

#notification view

def notifications_view(request):
    if 'user_id' not in request.session:
        return redirect('login')

    user_id = request.session['user_id']

    notifications = get_user_notifications(user_id)

    # 🔧 FIX: ensure created_at is datetime (not string)
    fixed_notifications = []
    for n in notifications:
        n = list(n)

        # assuming created_at is at index 5
        if isinstance(n[5], str):
            n[5] = datetime.strptime(n[5], "%Y-%m-%d %H:%M:%S")

        fixed_notifications.append(tuple(n))

    # 🔁 Handle redirect-after-read flow
    redirect_link = request.session.pop('redirect_after_notice', None)
    if redirect_link:
        return redirect(redirect_link)

    return render(request, 'notifications.html', {
        'notifications': fixed_notifications
    })

def mark_notification_read(request, notification_id):
    if 'user_id' not in request.session:
        return redirect('login')

    user_id = request.session['user_id']

    with connection.cursor() as cursor:
        # Mark as read
        cursor.execute("""
            UPDATE notifications
            SET is_read = 1
            WHERE notification_id = %s AND user_id = %s
        """, [notification_id, user_id])

        # Get redirect link
        cursor.execute("""
            SELECT link
            FROM notifications
            WHERE notification_id = %s
        """, [notification_id])

        row = cursor.fetchone()

    # 🔁 Redirect to ACTUAL content
    if row and row[0]:
        return redirect(row[0])

    return redirect('notifications')


from django.http import JsonResponse

def unread_notification_count_view(request):
    if 'user_id' not in request.session:
        return JsonResponse({'count': 0})

    user_id = request.session['user_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM notifications
            WHERE user_id = %s AND is_read = 0
        """, [user_id])

        count = cursor.fetchone()[0]

    return JsonResponse({'count': count})

# =========================
# DASHBOARDS
# =========================
def admin_dashboard(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    admin_id = request.session['user_id']

    with connection.cursor() as cursor:
        # 🔢 COUNTS
        cursor.execute("""
            SELECT COUNT(*) FROM users
            WHERE role = 'STUDENT' AND is_active = 1
        """)
        total_students = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM users
            WHERE role = 'FACULTY' AND is_active = 1
        """)
        total_faculty = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM events
            WHERE is_active = 1
        """)
        active_events = cursor.fetchone()[0]

        cursor.execute("""
            SELECT COUNT(*) FROM registration_requests
            WHERE status = 'PENDING'
        """)
        pending_requests = cursor.fetchone()[0]

        # 🔔 Notifications
        cursor.execute("""
            SELECT COUNT(*)
            FROM notifications
            WHERE user_id = %s AND is_read = 0
        """, [admin_id])
        unread_count = cursor.fetchone()[0]

        # 📰 Recent Notices
        cursor.execute("""
            SELECT notice_id, title, created_at
            FROM notices
            ORDER BY created_at DESC
            LIMIT 5
        """)
        recent_notices = cursor.fetchall()

        # 🎉 Recent Events
        cursor.execute("""
            SELECT event_id, title, event_date
            FROM events
            WHERE is_active = 1
            ORDER BY created_at DESC
            LIMIT 5
        """)
        recent_events = cursor.fetchall()

    return render(request, 'admin.html', {
        'total_students': total_students,
        'total_faculty': total_faculty,
        'active_events': active_events,
        'pending_requests': pending_requests,
        'unread_count': unread_count,
        'recent_notices': recent_notices,
        'recent_events': recent_events
    })

def faculty_dashboard(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
            'message': 'Faculty Only.'
        }, status=403)

    faculty_id = request.session['user_id']

    with connection.cursor() as cursor:

        # 👤 Fetch Faculty Name
        cursor.execute("""
            SELECT name
            FROM users
            WHERE user_id = %s
        """, [faculty_id])
        faculty_name = cursor.fetchone()[0]

        # 🔔 Unread notifications
        cursor.execute("""
            SELECT COUNT(*)
            FROM notifications
            WHERE user_id = %s AND is_read = 0
        """, [faculty_id])
        unread_count = cursor.fetchone()[0]

        # 📝 Assignments created by faculty
        cursor.execute("""
            SELECT COUNT(*)
            FROM assignments
            WHERE created_by = %s
        """, [faculty_id])
        total_assignments = cursor.fetchone()[0]

        # 🎉 Events where faculty is in-charge
        cursor.execute("""
            SELECT COUNT(*)
            FROM events
            WHERE faculty_incharge_id = %s
              AND is_active = 1
        """, [faculty_id])
        total_events = cursor.fetchone()[0]

        # 📚 Subjects handled
        cursor.execute("""
            SELECT COUNT(DISTINCT subject_id)
            FROM faculty_subjects
            WHERE faculty_id = %s
        """, [faculty_id])
        total_subjects = cursor.fetchone()[0]

        # 📰 Notices visible to faculty
        cursor.execute("""
            SELECT COUNT(DISTINCT n.notice_id)
            FROM notices n
            JOIN users u ON u.user_id = %s
            WHERE
                n.created_by = %s
                OR n.department_id IS NULL
                OR (
                    n.department_id = u.department_id
                    AND (n.semester_id IS NULL OR n.semester_id = u.semester_id)
                )
        """, [faculty_id, faculty_id])
        total_notices = cursor.fetchone()[0]

        # 🚨 Pending submissions
        cursor.execute("""
            SELECT COALESCE(SUM(pending_count), 0)
            FROM (
                SELECT
                    a.assignment_id,
                    (
                        SELECT COUNT(*)
                        FROM users u
                        WHERE u.role = 'STUDENT'
                          AND u.semester_id = a.semester_id
                    ) -
                    (
                        SELECT COUNT(DISTINCT s.student_id)
                        FROM assignment_submissions s
                        WHERE s.assignment_id = a.assignment_id
                    ) AS pending_count
                FROM assignments a
                WHERE a.created_by = %s
            ) AS pending_table
        """, [faculty_id])
        pending_submissions = cursor.fetchone()[0]

        # 📝 Recent assignments
        cursor.execute("""
            SELECT assignment_id, title, due_date
            FROM assignments
            WHERE created_by = %s
            ORDER BY assignment_id DESC
            LIMIT 5
        """, [faculty_id])
        recent_assignments = cursor.fetchall()

        # 🎊 Upcoming events
        cursor.execute("""
            SELECT event_id, title, event_date
            FROM events
            WHERE faculty_incharge_id = %s
              AND is_active = 1
            ORDER BY event_date ASC
            LIMIT 5
        """, [faculty_id])
        upcoming_events = cursor.fetchall()

    return render(request, 'faculty.html', {
        'faculty_name': faculty_name,   # 👈 added
        'unread_count': unread_count,
        'total_assignments': total_assignments,
        'total_events': total_events,
        'total_subjects': total_subjects,
        'total_notices': total_notices,
        'pending_submissions': pending_submissions,
        'recent_assignments': recent_assignments,
        'upcoming_events': upcoming_events
    })

def student_dashboard(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)
    student_id = request.session['user_id']

    with connection.cursor() as cursor:

        # 🔔 unread notifications
        cursor.execute("""
            SELECT COUNT(*)
            FROM notifications
            WHERE user_id = %s AND is_read = 0
        """, [student_id])
        unread_count = cursor.fetchone()[0]

        # 📚 student info
        cursor.execute("""
            SELECT name, semester_id, department_id
            FROM users
            WHERE user_id = %s
        """, [student_id])
        name, semester_id, department_id = cursor.fetchone()

        # 📘 total subjects (FIXED LOGIC)
        cursor.execute("""
            SELECT COUNT(*)
            FROM subjects
            WHERE semester_id = %s
        """, [semester_id])
        total_subjects = cursor.fetchone()[0]

        # 📝 pending assignments count
        cursor.execute("""
            SELECT COUNT(*)
            FROM assignments a
            WHERE a.semester_id = %s
              AND a.assignment_id NOT IN (
                  SELECT assignment_id
                  FROM assignment_submissions
                  WHERE student_id = %s
              )
        """, [semester_id, student_id])
        pending_assignments_count = cursor.fetchone()[0]

        # 📝 pending assignments list
        cursor.execute("""
            SELECT a.assignment_id, a.title, a.due_date
            FROM assignments a
            WHERE a.semester_id = %s
              AND a.assignment_id NOT IN (
                  SELECT assignment_id
                  FROM assignment_submissions
                  WHERE student_id = %s
              )
            ORDER BY a.due_date ASC
            LIMIT 5
        """, [semester_id, student_id])
        pending_assignments = cursor.fetchall()

        # 📊 attendance percentage (SAFE)
        cursor.execute("""
            SELECT
    ROUND(
        (SUM(CASE WHEN status = 1 THEN 1 ELSE 0 END)
         / NULLIF(COUNT(*), 0)) * 100,
    1
)
FROM attendance
WHERE student_id = %s;

        """, [student_id])
        attendance_percentage = cursor.fetchone()[0]

        # 📢 notices count
        cursor.execute("""
            SELECT COUNT(*)
            FROM notices
            WHERE department_id IS NULL
               OR department_id = %s
               OR (department_id = %s AND semester_id = %s)
        """, [department_id, department_id, semester_id])
        notices_count = cursor.fetchone()[0]

        # 🎉 upcoming events
        cursor.execute("""
            SELECT event_id, title, event_date
            FROM events
            WHERE is_active = 1
              AND (
                    department_id IS NULL
                    OR department_id = %s
                    OR (department_id = %s AND semester_id = %s)
              )
              AND event_date >= CURDATE()
            ORDER BY event_date ASC
            LIMIT 5
        """, [department_id, department_id, semester_id])
        upcoming_events = cursor.fetchall()

        # 🎯 EVENT COORDINATOR COUNT
        cursor.execute("""
    SELECT COUNT(*)
    FROM event_coordinators ec
    JOIN events e ON ec.event_id = e.event_id
    WHERE ec.student_id = %s
      AND e.is_active = 1
      AND e.event_date >= CURDATE()
""", [student_id])

        coordinator_events_count = cursor.fetchone()[0]

    return render(request, 'student.html', {
        'name':name,
        'unread_count': unread_count,
        'total_subjects': total_subjects,
        'pending_assignments_count': pending_assignments_count,
        'attendance_percentage': attendance_percentage,
        'notices_count': notices_count,
        'pending_assignments': pending_assignments,
        'upcoming_events': upcoming_events,
        'coordinator_events_count': coordinator_events_count,
    })

def student_subjects_view(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session['user_id']

    with connection.cursor() as cursor:

        # get student's semester
        cursor.execute("""
            SELECT semester_id
            FROM users
            WHERE user_id = %s
        """, [student_id])
        semester_id = cursor.fetchone()[0]

        # subjects + grouped faculty
        cursor.execute("""
            SELECT
                s.subject_id,
                s.subject_name,
                GROUP_CONCAT(u.name SEPARATOR ', ') AS faculty_names
            FROM faculty_subjects fs
            JOIN subjects s
                ON s.subject_id = fs.subject_id
            JOIN users u
                ON u.user_id = fs.faculty_id
            WHERE fs.semester_id = %s
            GROUP BY s.subject_id, s.subject_name
            ORDER BY s.subject_name
        """, [semester_id])

        subjects = cursor.fetchall()

    return render(request, 'student_subjects.html', {
        'subjects': subjects
    })

def student_attendance_detail_view(request, subject_id):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session['user_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                s.subject_name,
                a.lecture_date,
                t.day_of_week,
                t.start_time,
                t.end_time,
                a.status
            FROM attendance a
            JOIN timetable t
                ON t.timetable_id = a.timetable_id
            JOIN faculty_subjects fs
                ON fs.faculty_subject_id = t.faculty_subject_id
            JOIN subjects s
                ON s.subject_id = fs.subject_id
            WHERE a.student_id = %s
              AND s.subject_id = %s
            ORDER BY a.lecture_date DESC, t.start_time
        """, [student_id, subject_id])

        attendance = cursor.fetchall()

    return render(request, 'student_attendance_detail.html', {
        'attendance': attendance
    })


def student_pending_assignments_view(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session['user_id']

    with connection.cursor() as cursor:

        # Student semester
        cursor.execute("""
            SELECT semester_id
            FROM users
            WHERE user_id = %s
        """, [student_id])
        semester_id = cursor.fetchone()[0]

        # Pending assignments list
        cursor.execute("""
            SELECT
                a.assignment_id,
                a.title,
                a.due_date,
                s.subject_name
            FROM assignments a
            JOIN subjects s ON a.subject_id = s.subject_id
            WHERE a.semester_id = %s
            AND a.assignment_id NOT IN (
                SELECT assignment_id
                FROM assignment_submissions
                WHERE student_id = %s
            )
            ORDER BY a.due_date ASC
        """, [semester_id, student_id])

        assignments = cursor.fetchall()

    return render(request, 'student_pending_assignments.html', {
        'assignments': assignments
    })

# =========================
# ATTENDANCE (FACULTY)
# =========================

from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.db import connection, transaction


def mark_attendance(request):
    if request.session.get('role') != 'FACULTY':
        return HttpResponseForbidden("Faculty Only")

    faculty_id = request.session.get('user_id')

    # -----------------------------
    # 🔹 Fetch Faculty Data
    # -----------------------------
    with connection.cursor() as cursor:

        # ✅ Classes assigned to this faculty
        cursor.execute("""
            SELECT DISTINCT c.class_id, c.class_name
            FROM faculty_subjects fs
            JOIN semesters sem ON fs.semester_id = sem.semester_id
            JOIN classes c ON sem.class_id = c.class_id
            WHERE fs.faculty_id = %s
        """, [faculty_id])
        classes = cursor.fetchall()

        # ✅ Subjects assigned to this faculty
        cursor.execute("""
            SELECT s.subject_id, s.subject_name
            FROM faculty_subjects fs
            JOIN subjects s ON fs.subject_id = s.subject_id
            WHERE fs.faculty_id = %s
        """, [faculty_id])
        subjects = cursor.fetchall()

        # ✅ Timetable slots assigned to this faculty
        cursor.execute("""
            SELECT t.timetable_id, t.day_of_week, t.start_time, t.end_time
            FROM timetable t
            JOIN faculty_subjects fs
                ON t.faculty_subject_id = fs.faculty_subject_id
            WHERE fs.faculty_id = %s
        """, [faculty_id])
        timetable_slots = cursor.fetchall()

    students = []
    selected_class_id = None
    selected_subject_id = None
    selected_date = None
    selected_timetable_id = None

    # -----------------------------
    # 🔁 HANDLE POST
    # -----------------------------
    if request.method == 'POST':

        selected_class_id = request.POST.get('class_id')
        selected_subject_id = request.POST.get('subject_id')
        selected_date = request.POST.get('lecture_date')
        selected_timetable_id = request.POST.get('timetable_id')

        # =============================
        # STEP 1 → Load Students
        # =============================
        if 'load_students' in request.POST:

            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT user_id, name
                    FROM users
                    WHERE role = 'STUDENT'
                      AND class_id = %s
                      AND is_active = 1
                    ORDER BY name
                """, [selected_class_id])

                students = cursor.fetchall()

        # =============================
        # STEP 2 → Submit Attendance
        # =============================
        else:

            present_students = request.POST.getlist('present_students')

            # Fetch all students of class
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT user_id
                    FROM users
                    WHERE role = 'STUDENT'
                      AND class_id = %s
                      AND is_active = 1
                """, [selected_class_id])

                all_students = [row[0] for row in cursor.fetchall()]

            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:

                        for student_id in all_students:
                            status = 1 if str(student_id) in present_students else 0

                            # 🔒 Prevent duplicate attendance
                            cursor.execute("""
                                INSERT INTO attendance
                                (student_id, timetable_id, lecture_date, status)
                                VALUES (%s, %s, %s, %s)
                                ON DUPLICATE KEY UPDATE status = VALUES(status)
                            """, [
                                student_id,
                                selected_timetable_id,
                                selected_date,
                                status
                            ])

                messages.success(
                    request,
                    f"Attendance marked successfully. "
                    f"{len(present_students)} Present, "
                    f"{len(all_students) - len(present_students)} Absent."
                )

                return redirect('faculty_dashboard')

            except Exception as e:
                messages.error(request, f"Error occurred: {str(e)}")

    # -----------------------------
    # 🔹 Render Page
    # -----------------------------
    return render(request, 'faculty_mark_attendance.html', {
        'classes': classes,
        'subjects': subjects,
        'timetable_slots': timetable_slots,
        'students': students,
        'selected_class_id': selected_class_id,
        'selected_subject_id': selected_subject_id,
        'selected_date': selected_date,
        'selected_timetable_id': selected_timetable_id,
    })


# =========================
# ATTENDANCE VIEW (STUDENT)
# =========================

def view_attendance(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
  s.subject_name,
  a.lecture_date,
  t.day_of_week,
  t.start_time,
  t.end_time,
  a.status
            FROM attendance a
            JOIN timetable t ON a.timetable_id = t.timetable_id
            JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
            JOIN subjects s ON fs.subject_id = s.subject_id
            WHERE a.student_id = %s
            ORDER BY t.day_of_week, t.start_time
        """, [student_id])

        records = cursor.fetchall()

    return render(request, 'student_view_attendance.html', {
        'attendance': records
    })

def student_attendance_report(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.callproc('get_subject_wise_attendance_summary', [student_id])
        report = cursor.fetchall()

    return render(request, 'student_attendance_report.html', {
        'report': report
    })



def student_attendance_detail_view(request, subject_id):

    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
            'message': 'Students Only.'
        }, status=403)

    student_id = request.session.get('user_id')

    with connection.cursor() as cursor:

        # ✅ Validate subject exists
        cursor.execute("""
            SELECT subject_name
            FROM subjects
            WHERE subject_id = %s
        """, [subject_id])

        subject_row = cursor.fetchone()

        if not subject_row:
            return render(request, '403.html', {
            'message': 'Invalid Subject.'
        }, status=403)

        subject_name = subject_row[0]

        # ✅ Get detailed attendance records properly
        cursor.execute("""
            SELECT 
                a.lecture_date,
                a.status,
                t.day_of_week,
                t.start_time,
                t.end_time
            FROM attendance a
            JOIN timetable t ON a.timetable_id = t.timetable_id
            JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
            WHERE a.student_id = %s
              AND fs.subject_id = %s
            ORDER BY a.lecture_date DESC
        """, [student_id, subject_id])

        attendance_records = cursor.fetchall()

        # ✅ Calculate stats correctly
        cursor.execute("""
            SELECT 
                COUNT(*) AS total,
                SUM(CASE WHEN a.status = 1 THEN 1 ELSE 0 END) AS present
            FROM attendance a
            JOIN timetable t ON a.timetable_id = t.timetable_id
            JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
            WHERE a.student_id = %s
              AND fs.subject_id = %s
        """, [student_id, subject_id])

        stats = cursor.fetchone()

        total = stats[0] or 0
        present = stats[1] or 0
        percentage = round((present / total) * 100) if total > 0 else 0

    return render(request, 'student_attendance_detail.html', {
        'subject_name': subject_name,
        'subject_id': subject_id,
        'attendance_records': attendance_records,
        'total': total,
        'present': present,
        'absent': total - present,
        'percentage': percentage
    })

def student_attendance_view(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)
    student_id = request.session['user_id']

    with connection.cursor() as cursor:

        # get student's semester
        cursor.execute("""
            SELECT semester_id
            FROM users
            WHERE user_id = %s
        """, [student_id])
        semester_id = cursor.fetchone()[0]

        cursor.execute("""
            SELECT
                s.subject_id,
                s.subject_name,
                COUNT(a.attendance_id) AS total_classes,
                SUM(CASE WHEN a.status = 1 THEN 1 ELSE 0 END) AS present_classes
            FROM subjects s
            LEFT JOIN faculty_subjects fs
                ON fs.subject_id = s.subject_id
            LEFT JOIN timetable t
                ON t.faculty_subject_id = fs.faculty_subject_id
            LEFT JOIN attendance a
                ON a.timetable_id = t.timetable_id
               AND a.student_id = %s
            WHERE s.semester_id = %s
            GROUP BY s.subject_id, s.subject_name
            ORDER BY s.subject_name
        """, [student_id, semester_id])

        rows = cursor.fetchall()

    attendance_data = []

    for subject_id, subject_name, total, present in rows:
        total = total or 0
        present = present or 0

        percentage = round((present / total) * 100, 1) if total > 0 else 0

        attendance_data.append({
            'subject_id': subject_id,
            'subject_name': subject_name,
            'total': total,
            'present': present,
            'percentage': percentage
        })

    return render(request, 'student_attendance.html', {
        'attendance_data': attendance_data
    })

def student_timetable_view(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        # get student's semester
        cursor.execute("""
            SELECT semester_id
            FROM users
            WHERE user_id = %s
        """, [student_id])
        semester_id = cursor.fetchone()[0]

        # fetch raw timetable
        cursor.execute("""
            SELECT
                t.day_of_week,
                t.start_time,
                t.end_time,
                s.subject_name,
                f.name AS faculty_name
            FROM timetable t
            JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
            JOIN subjects s ON fs.subject_id = s.subject_id
            JOIN users f ON fs.faculty_id = f.user_id
            WHERE fs.semester_id = %s
            ORDER BY
                FIELD(t.day_of_week,
                    'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'),
                t.start_time
        """, [semester_id])

        rows = cursor.fetchall()

    # ---------- GRID TRANSFORMATION ----------
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    timetable = {}
    time_slots = []

    # Build timetable map
    for day, start, end, subject, faculty in rows:
        slot = f"{start}-{end}"

        if slot not in timetable:
            timetable[slot] = {}
            time_slots.append(slot)

        timetable[slot][day] = f"{subject} ({faculty})"

    # Build grid for template (Django-safe)
    grid = []
    for slot in time_slots:
        row = {
            'time': slot,
            'cells': []
        }
        for day in days:
            row['cells'].append(
                timetable.get(slot, {}).get(day, '---')
            )
        grid.append(row)


    return render(request, 'student_timetable.html', {
    'days': days,
    'grid': grid
})

#student assignments view
def student_assignments_view(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                a.assignment_id,        -- 0
                s.subject_name,         -- 1
                a.title,                -- 2
                a.description,          -- 3
                a.due_date,             -- 4
                u.name AS created_by,   -- 5
                a.question_file,        -- 6
                CASE
                    WHEN sub.submission_id IS NOT NULL THEN 1
                    ELSE 0
                END AS is_submitted      -- 7 ✅
            FROM assignments a
            JOIN subjects s ON a.subject_id = s.subject_id
            JOIN users u ON a.created_by = u.user_id
            LEFT JOIN assignment_submissions sub
                ON sub.assignment_id = a.assignment_id
               AND sub.student_id = %s
            WHERE a.semester_id = (
                SELECT semester_id
                FROM users
                WHERE user_id = %s
            )
            ORDER BY a.due_date
        """, [student_id, student_id])

        assignments = cursor.fetchall()

    return render(request, 'student_assignments.html', {
        'assignments': assignments,
        'today': date.today(),
        'MEDIA_URL': settings.MEDIA_URL
    })


#submit assignment

from django.core.files.storage import FileSystemStorage

def submit_assignment_view(request, assignment_id):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session.get('user_id')
    message = None

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                a.assignment_id,
                s.subject_name,
                a.title,
                a.description,
                a.due_date,
                a.question_file,
                a.created_by
            FROM assignments a
            JOIN subjects s ON a.subject_id = s.subject_id
            WHERE a.assignment_id = %s
        """, [assignment_id])

        assignment = cursor.fetchone()

    if not assignment:
        return HttpResponse("Assignment not found")

    if request.method == 'POST':
        submission_file = request.FILES['submission_file']

        fs = FileSystemStorage(location='media/assignments/submissions')
        filename = fs.save(submission_file.name, submission_file)
        file_path = f'assignments/submissions/{filename}'

        try:
            with connection.cursor() as cursor:
                cursor.callproc(
                    'submit_assignment',
                    [assignment_id, student_id, file_path]
                )

            # 🔔 NOTIFY FACULTY
            faculty_id = assignment[6]
            assignment_title = assignment[2]

            create_notification(
                user_id=faculty_id,
                title="Assignment Submitted",
                message=f"📝 A student submitted: {assignment_title}",
                link=f"/faculty/assignments/submissions/?assignment_id={assignment_id}"
            )

            message = "Assignment submitted successfully"

        except Exception as e:
            message = str(e)

    return render(request, 'student_submit_assignment.html', {
        'assignment': assignment,
        'message': message
    })

def faculty_pending_submissions_view(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    faculty_id = request.session['user_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                a.assignment_id,
                a.title,
                COUNT(u.user_id) AS pending_count
            FROM assignments a
            JOIN users u
                ON u.role = 'STUDENT'
               AND u.semester_id = a.semester_id
            JOIN faculty_subjects fs
                ON fs.subject_id = a.subject_id
               AND fs.faculty_id = a.created_by
            LEFT JOIN assignment_submissions s
                ON s.assignment_id = a.assignment_id
               AND s.student_id = u.user_id
            WHERE a.created_by = %s
              AND s.submission_id IS NULL
            GROUP BY a.assignment_id, a.title
        """, [faculty_id])

        pending_assignments = cursor.fetchall()

    return render(request, 'faculty_pending_submissions.html', {
        'pending_assignments': pending_assignments
    })

def student_notices(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        # get student's dept + semester
        cursor.execute("""
            SELECT department_id, semester_id
            FROM users
            WHERE user_id = %s
        """, [student_id])

        row = cursor.fetchone()
        department_id = row[0]
        semester_id = row[1]

        # fetch notices
        cursor.execute("""
            SELECT 
                n.title,
                n.content,
                u.name AS created_by,
                n.created_at,
                n.attachment
            FROM notices n
            JOIN users u ON n.created_by = u.user_id
            WHERE
            (
                n.department_id IS NULL 
                AND n.semester_id IS NULL
            )
            OR
            (
                n.department_id = %s 
                AND n.semester_id IS NULL
            )
            OR
            (
                n.department_id = %s 
                AND n.semester_id = %s
            )
            ORDER BY n.created_at DESC
        """, [department_id, department_id, semester_id])

        notices = cursor.fetchall()

    return render(request, 'student_notices.html', {
        'notices': notices
    })


# student view for events
def student_events_view(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        # fetch student dept & semester
        cursor.execute("""
            SELECT department_id, semester_id
            FROM users
            WHERE user_id = %s
        """, [student_id])
        department_id, semester_id = cursor.fetchone()

        # fetch relevant events
        cursor.execute("""
            SELECT
                e.event_id,
                e.title,
                e.description,
                e.event_date,
                e.start_time,
                e.end_time,
                e.venue,
                e.poster_path,
                u.name
            FROM events e
            LEFT JOIN users u ON e.faculty_incharge_id = u.user_id
            WHERE e.is_active = 1
            AND (
                (e.department_id IS NULL AND e.semester_id IS NULL)
                OR
                (
                    e.department_id = %s
                    AND (e.semester_id IS NULL OR e.semester_id = %s)
                )
            )
            ORDER BY e.event_date, e.start_time
        """, [department_id, semester_id])

        events = cursor.fetchall()

    return render(request, 'student_events.html', {
        'events': events
    })

def event_detail_view(request, event_id):
    if request.session.get('role') not in ['STUDENT', 'FACULTY', 'ADMIN']:
        return render(request, '403.html', {
        'message': 'Not Allowed.'
    }, status=403)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                e.event_id,
                e.title,
                e.description,
                e.event_date,
                e.start_time,
                e.end_time,
                e.venue,
                e.poster_path,
                e.google_form_link,
                u.name AS faculty_incharge
            FROM events e
            LEFT JOIN users u ON e.faculty_incharge_id = u.user_id
            WHERE e.event_id = %s
            AND e.is_active = 1
        """, [event_id])

        event = cursor.fetchone()

    if not event:
        return HttpResponse("Event not found")

    return render(request, 'event_detail.html', {
        'event': event
    })

def faculty_events_only_view(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    user_id = request.session.get('user_id')
    role = request.session.get('role')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                e.event_id,              -- 0
                e.title,                 -- 1
                e.event_date,            -- 2
                e.start_time,            -- 3
                e.end_time,              -- 4
                e.venue,                 -- 5
                e.poster_path,           -- 6
                d.department_name,       -- 7
                s.semester_number,       -- 8
                e.created_by,            -- 9
                e.faculty_incharge_id    -- 10
            FROM events e
            LEFT JOIN departments d ON e.department_id = d.department_id
            LEFT JOIN semesters s ON e.semester_id = s.semester_id
            WHERE e.is_active = 1
              AND (
                    e.created_by = %s
                    OR e.faculty_incharge_id = %s
                  )
            ORDER BY e.event_date ASC, e.start_time ASC
        """, [user_id, user_id])

        events = cursor.fetchall()

    # 🔐 Permissions (since these are ONLY own events, all allowed)
    events_with_permissions = []

    for e in events:
        events_with_permissions.append({
            'event': e,
            'can_edit': True,
            'can_delete': True,
            'can_assign': True
        })

    return render(request, 'faculty_events.html', {
        'events': events_with_permissions,
        'readonly': False   # important
    })

def faculty_events_view(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    user_id = request.session.get('user_id')
    role = request.session.get('role')

    # 👇 detect mode from query param
    readonly = request.GET.get("mode") == "view_all"

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT department_id, semester_id
            FROM users
            WHERE user_id = %s
        """, [user_id])
        row = cursor.fetchone()

        if not row:
            return HttpResponse("Faculty not found")

        faculty_dept, faculty_sem = row

        cursor.execute("""
            SELECT
                e.event_id,
                e.title,
                e.event_date,
                e.start_time,
                e.end_time,
                e.venue,
                e.poster_path,
                d.department_name,
                s.semester_number,
                e.created_by,
                e.faculty_incharge_id
            FROM events e
            LEFT JOIN departments d ON e.department_id = d.department_id
            LEFT JOIN semesters s ON e.semester_id = s.semester_id
            WHERE e.is_active = 1
              AND (
                    e.created_by = %s
                    OR e.faculty_incharge_id = %s
                    OR (
                        e.department_id = %s
                        AND (
                            e.semester_id IS NULL
                            OR e.semester_id = %s
                        )
                    )
                    OR (
                        e.department_id IS NULL
                        AND e.semester_id IS NULL
                    )
                )
            ORDER BY e.event_date, e.start_time
        """, [user_id, user_id, faculty_dept, faculty_sem])

        events = cursor.fetchall()

    events_with_permissions = []
    for e in events:
        event_id = e[0]
        created_by = e[9]
        faculty_incharge = e[10]
    

        events_with_permissions.append({
        'event': e,
        'can_edit': can_edit_event(role, user_id, event_id),
        'can_delete': can_delete_event(role, user_id, event_id),
        'can_assign': (
            int(created_by) == int(user_id) or
            int(faculty_incharge) == int(user_id)
        )
    })

    return render(request, 'faculty_events.html', {
        'events': events_with_permissions,
        'readonly': readonly
    }) 

from datetime import date, datetime

def admin_events_view(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    user_id = request.session.get('user_id')

    # --- GET filter params ---
    search       = request.GET.get('search', '').strip()
    scope        = request.GET.get('scope', '')        # global / dept / semester
    created_by_me = request.GET.get('created_by_me', '') # '1' = only mine
    status       = request.GET.get('status', '')       # upcoming / ongoing / completed

    # --- Base query ---
    query = """
        SELECT
            e.event_id,
            e.title,
            e.event_date,
            e.start_time,
            e.end_time,
            e.venue,
            e.poster_path,
            d.department_name,
            s.semester_number,
            u1.name AS created_by,
            u2.name AS faculty_incharge,
            e.created_by AS created_by_id
        FROM events e
        LEFT JOIN departments d ON e.department_id = d.department_id
        LEFT JOIN semesters s ON e.semester_id = s.semester_id
        LEFT JOIN users u1 ON e.created_by = u1.user_id
        LEFT JOIN users u2 ON e.faculty_incharge_id = u2.user_id
        WHERE e.is_active = 1
    """

    params = []

    # --- Search filter ---
    if search:
        query += " AND e.title LIKE %s"
        params.append(f'%{search}%')

    # --- Scope filter ---
    if scope == 'global':
        # Global = no department and no semester
        query += " AND e.department_id IS NULL AND e.semester_id IS NULL"
    elif scope == 'dept':
        # Dept scoped = has department but no semester
        query += " AND e.department_id IS NOT NULL AND e.semester_id IS NULL"
    elif scope == 'semester':
        # Semester scoped = has both department and semester
        query += " AND e.department_id IS NOT NULL AND e.semester_id IS NOT NULL"

    # --- Created by me filter ---
    if created_by_me == '1':
        query += " AND e.created_by = %s"
        params.append(user_id)

    query += " ORDER BY e.event_date DESC, e.start_time"

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        events = cursor.fetchall()

    # --- Status filter (done in Python using today's date) ---
    today = date.today()
    now   = datetime.now().time()

    filtered_events = []
    for e in events:
        event_date  = e[2]   # date object from DB
        start_time  = e[3]   # time object from DB
        end_time    = e[4]   # time object from DB

        # Normalize to date if datetime
        if hasattr(event_date, 'date'):
            event_date = event_date.date()

        if status == 'upcoming':
            # Upcoming: event date is in the future
            # OR it's today but hasn't started yet
            if event_date > today:
                pass  # include
            elif event_date == today and start_time and start_time > now:
                pass  # include
            else:
                continue  # skip

        elif status == 'ongoing':
            # Ongoing: today is the event date AND
            # current time is between start and end
            if event_date == today and start_time and end_time:
                if start_time <= now <= end_time:
                    pass  # include
                else:
                    continue  # skip
            else:
                continue  # skip

        elif status == 'completed':
            # Completed: event date is in the past
            # OR it's today but end time has passed
            if event_date < today:
                pass  # include
            elif event_date == today and end_time and end_time < now:
                pass  # include
            else:
                continue  # skip

        filtered_events.append(e)

    events_with_permissions = []
    for e in filtered_events:
        events_with_permissions.append({
            'event': e,
            'can_edit': True,
            'can_delete': True,
        })

    return render(request, 'admin_events.html', {
        'events': events_with_permissions,
    })
from django.shortcuts import render, redirect
from django.http import HttpResponseForbidden
from django.db import connection, transaction
def assign_event_coordinator_view(request, event_id):

    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    error = None

    with connection.cursor() as cursor:

        # ==============================
        # 🔹 HANDLE REMOVE FIRST
        # ==============================
        if request.method == "POST" and request.POST.get("remove_id"):
            remove_id = request.POST.get("remove_id")

            cursor.execute("""
                DELETE FROM event_coordinators
                WHERE event_id = %s AND student_id = %s
            """, [event_id, remove_id])

            return redirect(request.path)

        # ==============================
        # 🔹 HANDLE ASSIGN
        # ==============================
        if request.method == "POST" and request.POST.get("student_id"):
            student_id = request.POST.get("student_id")

            # 🔸 Get current assigned count
            cursor.execute("""
                SELECT COUNT(*)
                FROM event_coordinators
                WHERE event_id = %s
            """, [event_id])

            assigned_count = cursor.fetchone()[0]

            if assigned_count >= 2:
                error = "Maximum 2 coordinators allowed."

            else:
                # 🔸 Check duplicate
                cursor.execute("""
                    SELECT 1
                    FROM event_coordinators
                    WHERE event_id = %s AND student_id = %s
                """, [event_id, student_id])

                if cursor.fetchone():
                    error = "Student already assigned."
                else:
                    cursor.execute("""
                        INSERT INTO event_coordinators (event_id, student_id)
                        VALUES (%s, %s)
                    """, [event_id, student_id])

                    return redirect(request.path + "?success=1")

        # ==============================
        # 🔹 FETCH UPDATED DATA
        # ==============================

        # Assigned coordinators
        cursor.execute("""
            SELECT ec.student_id, u.name
            FROM event_coordinators ec
            JOIN users u ON ec.student_id = u.user_id
            WHERE ec.event_id = %s
        """, [event_id])

        assigned = cursor.fetchall()
        assigned_count = len(assigned)
        remaining_slots = 2 - assigned_count

        # Fetch students (exclude already assigned)
        cursor.execute("""
            SELECT user_id, name
            FROM users
            WHERE role = 'STUDENT'
              AND user_id NOT IN (
                  SELECT student_id
                  FROM event_coordinators
                  WHERE event_id = %s
              )
        """, [event_id])

        students = cursor.fetchall()

    return render(request, 'assign_event_coordinators.html', {
        'assigned': assigned,
        'students': students,
        'error': error,
        'assigned_count': assigned_count,
        'remaining_slots': remaining_slots
    })

def can_edit_event(role, user_id, event_id):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT faculty_incharge_id
            FROM events
            WHERE event_id = %s
        """, [event_id])
        row = cursor.fetchone()

    if not row:
        return False

    faculty_incharge_id = row[0]

    if role == 'ADMIN':
        return True

    if role == 'FACULTY' and user_id == faculty_incharge_id:
        return True

    # coordinator
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 1
            FROM event_coordinators
            WHERE event_id = %s AND student_id = %s
        """, [event_id, user_id])
        return cursor.fetchone() is not None


def can_delete_event(role, user_id, event_id):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT faculty_incharge_id
            FROM events
            WHERE event_id = %s
        """, [event_id])
        row = cursor.fetchone()

    if not row:
        return False

    faculty_incharge_id = row[0]

    return role == 'ADMIN' or (
        role == 'FACULTY' and user_id == faculty_incharge_id
    )

def edit_event_view(request, event_id):
    role = request.session.get('role')
    user_id = request.session.get('user_id')

    if not can_edit_event(role, user_id, event_id):
        return render(request, '403.html', {
        'message': 'You are not allowed to edit this event.'
    }, status=403)

    if request.method == 'POST':
        title = request.POST['title']
        description = request.POST['description']
        event_date = request.POST['event_date']
        start_time = request.POST['start_time']
        end_time = request.POST['end_time']
        venue = request.POST['venue']
        google_form_link = request.POST['google_form_link']

        poster = request.FILES.get('poster')
        poster_path = None
        if poster:
            from django.core.files.storage import FileSystemStorage
            fs = FileSystemStorage(location='media/events/posters')
            filename = fs.save(poster.name, poster)
            poster_path = f'events/posters/{filename}'

        with connection.cursor() as cursor:
            cursor.callproc(
                'update_event',
                [
                    event_id, title, description, event_date,
                    start_time, end_time, venue,
                    poster_path, google_form_link
                ]
            )

        # 🔔 NOTIFICATIONS
        users = get_event_notification_users(event_id)
        for uid in users:
            create_notification(
                user_id=uid,
                title="Event Updated",
                message=f"✏️ Event Updated: {title}",
                link=f"/events/{event_id}/"
            )

        return redirect('event_detail', event_id=event_id)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT title, description, event_date, start_time, end_time,
                   venue, google_form_link
            FROM events WHERE event_id = %s
        """, [event_id])
        event = cursor.fetchone()

    return render(request, 'edit_event.html', {
        'event': event,
        'event_id': event_id
    })
def delete_event_view(request, event_id):
    role = request.session.get('role')
    user_id = request.session.get('user_id')

    if not can_delete_event(role, user_id, event_id):
        return render(request, '403.html', {
        'message': 'You are not allowed to delete this event.'
    }, status=403)

    if request.method == 'POST':
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE events SET is_active = 0 WHERE event_id = %s",
                [event_id]
            )

        # 🔔 NOTIFICATIONS
        users = get_event_notification_users(event_id)
        for uid in users:
            create_notification(
                user_id=uid,
                title="Event Cancelled",
                message="❌ An event has been cancelled",
                link="/student/events/"
            )

        return redirect('admin_events' if role == 'ADMIN' else 'faculty_events')

    return render(request, 'confirm_delete_event.html', {
        'event_id': event_id
    })

# =========================
# ATTENDANCE VIEW (FACULTY)
# =========================

def faculty_view_attendance(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    faculty_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                u.name AS student_name,
                s.subject_name,
                a.lecture_date,
                t.day_of_week,
                t.start_time,
                t.end_time,
                a.status
            FROM attendance a
            JOIN users u ON a.student_id = u.user_id
            JOIN timetable t ON a.timetable_id = t.timetable_id
            JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
            JOIN subjects s ON fs.subject_id = s.subject_id
            WHERE fs.faculty_id = %s
            ORDER BY t.day_of_week, t.start_time
        """, [faculty_id])

        records = cursor.fetchall()

    return render(request, 'faculty_view_attendance.html', {
        'records': records
    })

def faculty_attendance_report(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    faculty_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                u.user_id,
                u.name AS student_name,
                c.class_name,
                s.subject_name,
                calculate_attendance_percentage(u.user_id, s.subject_id) AS attendance_percentage
            FROM faculty_subjects fs
            JOIN timetable t ON fs.faculty_subject_id = t.faculty_subject_id
            JOIN attendance a ON a.timetable_id = t.timetable_id
            JOIN users u ON a.student_id = u.user_id
            JOIN subjects s ON fs.subject_id = s.subject_id
            JOIN classes c ON u.class_id = c.class_id
            WHERE fs.faculty_id = %s
            GROUP BY u.user_id, s.subject_id
            ORDER BY s.subject_name, attendance_percentage ASC
        """, [faculty_id])

        report = cursor.fetchall()

    return render(request, 'faculty_attendance_report.html', {
        'report': report
    })


# =========================
# ATTENDANCE CORRECTION (FACULTY)
# =========================

def request_attendance_correction(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    faculty_id = request.session.get('user_id')
    message = None
    error = None

    with connection.cursor() as cursor:

        # 🔹 Fetch attendance only for THIS faculty's timetable
        cursor.execute("""
            SELECT 
                a.attendance_id,
                u.name,
                s.subject_name,
                a.lecture_date,
                CASE 
                    WHEN a.status = 1 THEN 'Present'
                    ELSE 'Absent'
                END
            FROM attendance a
            JOIN users u ON a.student_id = u.user_id
            JOIN timetable t ON a.timetable_id = t.timetable_id
            JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
            JOIN subjects s ON fs.subject_id = s.subject_id
            WHERE fs.faculty_id = %s
            ORDER BY a.lecture_date DESC
        """, [faculty_id])

        attendance_records = cursor.fetchall()

    # ======================
    # 🔁 HANDLE POST
    # ======================
    if request.method == 'POST':
        attendance_id = request.POST.get('attendance_id')
        new_status = request.POST.get('new_status') == '1'
        reason = request.POST.get('reason')

        if not attendance_id or not reason:
            error = "Please select a record and provide reason."
        else:
            try:
                with connection.cursor() as cursor:
                    cursor.callproc(
                        'request_attendance_correction',
                        [attendance_id, new_status, reason, faculty_id]
                    )

                message = "Correction request submitted successfully"

            except Exception as e:
                error = str(e)

    return render(request, 'faculty_request_correction.html', {
        'attendance_records': attendance_records,
        'message': message,
        'error': error
    })

from django.shortcuts import redirect
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.db import connection

def reject_attendance_request(request, request_id):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    # 🔹 Check if request exists
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT request_id, attendance_id
            FROM attendance_correction_requests
            WHERE request_id = %s
              AND status = 'PENDING'
        """, [request_id])

        req = cursor.fetchone()

    if not req:
        return HttpResponse("Request not found or already processed")

    # ======================
    # 🔁 HANDLE POST
    # ======================
    if request.method == "POST":
        remark = request.POST.get("remark")

        if not remark:
            return render(request, "admin_reject_attendance.html", {
                "error": "Please provide rejection reason.",
                "request_data": req
            })

        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE attendance_correction_requests
                SET status = 'REJECTED',
                    admin_remark = %s
                WHERE request_id = %s
            """, [remark, request_id])

        return redirect("attendance_corrections_admin")

    return render(request, "admin_reject_attendance.html", {
        "request_data": req
    })



def faculty_timetable_view(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    faculty_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                t.day_of_week,
                t.start_time,
                t.end_time,
                s.subject_name,
                c.class_name
            FROM timetable t
            JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
            JOIN subjects s ON fs.subject_id = s.subject_id
            JOIN semesters sem ON fs.semester_id = sem.semester_id
            JOIN classes c ON sem.class_id = c.class_id
            WHERE fs.faculty_id = %s
            ORDER BY
                FIELD(t.day_of_week,
                    'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'),
                t.start_time
        """, [faculty_id])

        rows = cursor.fetchall()

    # ---------- GRID TRANSFORMATION ----------
    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    timetable = {}
    time_slots = []

    # build timetable map
    for day, start, end, subject, class_name in rows:
        slot = f"{start}-{end}"

        if slot not in timetable:
            timetable[slot] = {}
            time_slots.append(slot)

        timetable[slot][day] = f"{subject} ({class_name})"

    # build grid (template-safe)
    grid = []
    for slot in time_slots:
        row = {
            'time': slot,
            'cells': []
        }
        for day in days:
            row['cells'].append(
                timetable.get(slot, {}).get(day, '---')
            )
        grid.append(row)

    return render(request, 'faculty_timetable.html', {
        'days': days,
        'grid': grid
    })


#faculty creates assignments

from django.core.files.storage import FileSystemStorage
from datetime import date
from django.contrib import messages
from django.shortcuts import render, redirect

def create_assignment_view(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
            'message': 'Faculty Only.'
        }, status=403)

    faculty_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                fs.subject_id,
                s.subject_name,
                fs.semester_id
            FROM faculty_subjects fs
            JOIN subjects s ON fs.subject_id = s.subject_id
            WHERE fs.faculty_id = %s
        """, [faculty_id])

        subjects = cursor.fetchall()

    if request.method == 'POST':
        subject_id = request.POST['subject_id']
        semester_id = request.POST['semester_id']
        title = request.POST['title']
        description = request.POST['description']
        due_date = request.POST['due_date']
        question_file = request.FILES['question_file']

        fs = FileSystemStorage(location='media/assignments/questions')
        filename = fs.save(question_file.name, question_file)
        file_path = f'assignments/questions/{filename}'

        try:
            with connection.cursor() as cursor:
                cursor.callproc(
                    'create_assignment',
                    [
                        subject_id,
                        semester_id,
                        title,
                        description,
                        due_date,
                        faculty_id,
                        file_path
                    ]
                )

                cursor.execute("SELECT LAST_INSERT_ID()")
                assignment_id = cursor.fetchone()[0]

                # 🔔 FETCH STUDENTS OF THAT SEMESTER
                cursor.execute("""
                    SELECT user_id
                    FROM users
                    WHERE role = 'STUDENT'
                      AND is_active = 1
                      AND semester_id = %s
                """, [semester_id])

                students = cursor.fetchall()

            # 🔔 CREATE NOTIFICATIONS
            for (student_id,) in students:
                create_notification(
                    user_id=student_id,
                    title="New Assignment",
                    message=f"📘 New Assignment: {title}",
                    link="/student/assignments/"
                )

            # ✅ SUCCESS - redirect to assignments list
            messages.success(request, f'✅ Assignment "{title}" created successfully!')
            return redirect('faculty_assignments')

        except Exception as e:
            # ❌ ERROR - show error message but stay on form
            messages.error(request, f'Error creating assignment: {str(e)}')

    return render(request, 'faculty_create_assignment.html', {
        'subjects': subjects,
        'today': date.today()
    })
def faculty_assignments_view(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    faculty_id = request.session['user_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                a.assignment_id,
                a.title,
                a.due_date,
                s.subject_name,
                sem.semester_number,
                a.question_file
            FROM assignments a
            JOIN subjects s ON a.subject_id = s.subject_id
            JOIN semesters sem ON a.semester_id = sem.semester_id
            WHERE a.created_by = %s
            ORDER BY a.due_date ASC
        """, [faculty_id])

        assignments = cursor.fetchall()

    return render(request, 'faculty_assignments.html', {
        'assignments': assignments,
        'today': date.today()
    })


def faculty_assignment_submissions_view(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    faculty_id = request.session.get('user_id')
    selected_assignment_id = request.GET.get('assignment_id')

    assignments = []
    submissions = []
    pending_students = []
    total_students = 0

    with connection.cursor() as cursor:

        # 🔹 1. Fetch assignments created by this faculty
        cursor.execute("""
            SELECT
                a.assignment_id,
                s.subject_name,
                a.title,
                a.due_date
            FROM assignments a
            JOIN subjects s ON a.subject_id = s.subject_id
            WHERE a.created_by = %s
            ORDER BY a.due_date DESC
        """, [faculty_id])

        assignments = cursor.fetchall()

        # 🔹 2. If assignment selected
        if selected_assignment_id:

            # --- Get assignment semester ---
            cursor.execute("""
                SELECT semester_id
                FROM assignments
                WHERE assignment_id = %s
            """, [selected_assignment_id])

            result = cursor.fetchone()
            if not result:
                return render(request, 'faculty_assignment_submissions.html', {
                    'assignments': assignments,
                    'submissions': [],
                    'pending_students': [],
                    'selected_assignment_id': selected_assignment_id,
                    'total_students': 0
                })

            semester_id = result[0]

            # --- Fetch submissions via procedure ---
            cursor.callproc(
                'get_assignment_submissions',
                [selected_assignment_id]
            )
            submissions = cursor.fetchall()

            # --- Get all students of that semester ---
            cursor.execute("""
                SELECT user_id, name
                FROM users
                WHERE role = 'STUDENT'
                  AND semester_id = %s
            """, [semester_id])

            all_students = cursor.fetchall()
            total_students = len(all_students)

            # --- Extract submitted student IDs ---
            submitted_ids = [s[1] for s in submissions]  # s.1 = student_id

            # --- Build pending list ---
            pending_students = [
                student for student in all_students
                if student[0] not in submitted_ids
            ]

    return render(request, 'faculty_assignment_submissions.html', {
        'assignments': assignments,
        'submissions': submissions,
        'pending_students': pending_students,
        'selected_assignment_id': selected_assignment_id,
        'total_students': total_students
    })

def delete_assignment_view(request, assignment_id):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    faculty_id = request.session['user_id']

    # Check ownership
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT assignment_id
            FROM assignments
            WHERE assignment_id = %s
              AND created_by = %s
        """, [assignment_id, faculty_id])

        assignment = cursor.fetchone()

    if not assignment:
        return render(request, '403.html', {
        'message': 'You are not allowed to delete this assignment.'
    }, status=403)

    if request.method == 'POST':
        with connection.cursor() as cursor:
            cursor.execute("""
                DELETE FROM assignment_submissions
                WHERE assignment_id = %s
            """, [assignment_id])

            cursor.execute("""
                DELETE FROM assignments
                WHERE assignment_id = %s
            """, [assignment_id])

        return redirect('faculty_assignments')

    return render(request, 'confirm_delete_assignment.html', {
        'assignment_id': assignment_id
    })

def get_semesters_by_department(request):
    dept_id = request.GET.get('department_id')

    if not dept_id:
        return JsonResponse([], safe=False)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT s.semester_id, s.semester_number
            FROM semesters s
            JOIN classes c ON s.class_id = c.class_id
            WHERE c.department_id = %s
            ORDER BY s.semester_number
        """, [dept_id])

        rows = cursor.fetchall()

    data = [
        {
            'id': r[0],
            'number': r[1]
        }
        for r in rows
    ]

    return JsonResponse(data, safe=False)

def get_semesters_by_class(request):
    class_id = request.GET.get('class_id')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT semester_id, semester_number
            FROM semesters
            WHERE class_id = %s
        """, [class_id])

        semesters = cursor.fetchall()

    return JsonResponse({'semesters': semesters})


def get_classes_by_department(request):
    department_id = request.GET.get('department_id')

    if not department_id:
        return JsonResponse({'classes': []})

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT class_id, class_name
            FROM classes
            WHERE department_id = %s
        """, [department_id])

        classes = cursor.fetchall()

    return JsonResponse({
        'classes': classes
    })

from django.http import JsonResponse
from django.db import connection


def get_subjects_by_semester(request):
    semester_id = request.GET.get('semester_id')

    if not semester_id:
        return JsonResponse({'subjects': []})

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT subject_id, subject_name
            FROM subjects
            WHERE semester_id = %s
        """, [semester_id])

        subjects = cursor.fetchall()

    return JsonResponse({
        'subjects': subjects
    })
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import connection
from django.core.files.storage import FileSystemStorage


def create_notice(request):
    
    # 🔐 Role check
    role = request.session.get('role')
    user_id = request.session.get('user_id')

    if role not in ['ADMIN', 'FACULTY']:
        return render(request, '403.html', {
        'message': 'Admins or Faculty Only.'
    }, status=403)

    # =========================
    # 📩 POST → CREATE NOTICE
    # =========================
    if request.method == 'POST':

        title = request.POST.get('title')
        content = request.POST.get('content')
        scope = request.POST.get('scope')
        attachment = request.FILES.get('attachment')

        department_id = None
        semester_id = None
        attachment_path = None

        # -----------------------
        # Scope Handling
        # -----------------------
        if scope == 'DEPARTMENT':
            department_id = request.POST.get('department_id') or None
            semester_id = request.POST.get('semester_id') or None

            if not department_id:
                messages.error(request, "Department is required for Department scope.")
                return redirect(request.path)

        # -----------------------
        # Attachment Upload
        # -----------------------
        if attachment:
            fs = FileSystemStorage(location='media/notices')
            filename = fs.save(attachment.name, attachment)
            attachment_path = f'notices/{filename}'

        try:
            with connection.cursor() as cursor:

                # ✅ Create Notice via procedure
                cursor.callproc(
                    'create_notice',
                    [
                        title,
                        content,
                        user_id,
                        department_id,
                        semester_id,
                        attachment_path
                    ]
                )

                # Get inserted notice id
                cursor.execute("SELECT LAST_INSERT_ID()")
                notice_id = cursor.fetchone()[0]

                # -----------------------
                # 🔔 Fetch Users To Notify
                # -----------------------
                if department_id is None:
                    # 🌍 GLOBAL → All active users
                    cursor.execute("""
                        SELECT user_id
                        FROM users
                        WHERE is_active = 1
                    """)
                else:
                    # 🏢 Department / Semester + Admin always
                    cursor.execute("""
                        SELECT user_id
                        FROM users
                        WHERE is_active = 1
                          AND (
                                role = 'ADMIN'
                                OR (
                                    department_id = %s
                                    AND (%s IS NULL OR semester_id = %s)
                                )
                              )
                    """, [department_id, semester_id, semester_id])

                users_to_notify = cursor.fetchall()

            # -----------------------
            # 🔔 Insert Notifications
            # -----------------------
            for (uid,) in users_to_notify:
                create_notification(
                    user_id=uid,
                    title="New Notice",
                    message=f"📢 {title}",
                    link=f"/notices/{notice_id}/"
                )

            messages.success(request, "Notice posted successfully ✅")

            return redirect(
                'admin_dashboard' if role == 'ADMIN'
                else 'faculty_dashboard'
            )

        except Exception as e:
            messages.error(request, str(e))
            return redirect(request.path)

    # =========================
    # 📄 GET → LOAD FORM
    # =========================

    with connection.cursor() as cursor:

        # Admin → All departments
        if role == 'ADMIN':
            cursor.execute("""
                SELECT department_id, department_name
                FROM departments
            """)
        else:
            # Faculty → Only own department
            cursor.execute("""
                SELECT d.department_id, d.department_name
                FROM departments d
                JOIN users u ON u.department_id = d.department_id
                WHERE u.user_id = %s
            """, [user_id])

        departments = cursor.fetchall()

        # Optional: if you need semesters initially
        cursor.execute("""
            SELECT semester_id, semester_number
            FROM semesters
        """)
        semesters = cursor.fetchall()

    return render(request, 'create_notice.html', {
        'departments': departments,
        'semesters': semesters
    })


def notice_detail_view(request, notice_id):
    if request.session.get('role') not in ['ADMIN', 'FACULTY', 'STUDENT']:
        return render(request, '403.html', {
        'message': 'Not Allowed.'
    }, status=403)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                n.notice_id,
                n.title,
                n.content,
                n.attachment,
                n.created_at,
                u.name,
                d.department_name,
                s.semester_number
            FROM notices n
            JOIN users u ON n.created_by = u.user_id
            LEFT JOIN departments d ON n.department_id = d.department_id
            LEFT JOIN semesters s ON n.semester_id = s.semester_id
            WHERE n.notice_id = %s
        """, [notice_id])

        notice = cursor.fetchone()

    if not notice:
        return HttpResponse("Notice not found")

    return render(request, 'notice_detail.html', {
        'notice': notice
    })

def edit_notice(request, notice_id):
    role = request.session.get('role')
    user_id = request.session.get('user_id')

    if role not in ['ADMIN', 'FACULTY']:
        return render(request, '403.html', {
        'message': 'Not Allowed.'
    }, status=403)

    # 🔍 Fetch existing notice
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                notice_id,
                title,
                content,
                created_by,
                department_id,
                semester_id,
                attachment
            FROM notices
            WHERE notice_id = %s
        """, [notice_id])
        notice = cursor.fetchone()

    if not notice:
        return HttpResponse("Notice not found")

    (
        _nid,
        old_title,
        old_content,
        created_by,
        department_id,
        semester_id,
        old_attachment
    ) = notice

    # 🔐 Permission check
    if role == 'FACULTY' and int(created_by) != int(user_id):
        return render(request, '403.html', {
        'message': 'You can only edit your own notices.'
    }, status=403)

    # =======================
    # ✏️ POST → UPDATE NOTICE
    # =======================
    if request.method == 'POST':
        title = request.POST.get('title')
        content = request.POST.get('content')
        remove_attachment = request.POST.get('remove_attachment')
        new_attachment = request.FILES.get('attachment')

        attachment_path = old_attachment  # default = keep old

        # 🗑 Remove attachment if checkbox selected
        if remove_attachment:
            attachment_path = None

        # 📎 Replace with new attachment if uploaded
        if new_attachment:
            from django.core.files.storage import FileSystemStorage
            fs = FileSystemStorage(location='media/notices')
            filename = fs.save(new_attachment.name, new_attachment)
            attachment_path = f'notices/{filename}'

        # 📝 Update notice
        with connection.cursor() as cursor:
            cursor.execute("""
                UPDATE notices
                SET title = %s,
                    content = %s,
                    attachment = %s
                WHERE notice_id = %s
            """, [title, content, attachment_path, notice_id])

        # ==========================
        # 🔔 NOTIFICATIONS — EDIT
        # ==========================
        users_to_notify = get_notice_users(notice_id)

        for uid in users_to_notify:
            create_notification(
                user_id=uid,
                title="Notice Updated",
                message=f"✏️ Notice updated: {title}",
                link=f"/notices/{notice_id}/"
            )

        return redirect(
            'admin_notices' if role == 'ADMIN' else 'faculty_notices'
        )

    # =======================
    # 📄 GET → LOAD FORM
    # =======================
    return render(request, 'edit_notice.html', {
        'notice': {
            'notice_id': notice_id,
            'title': old_title,
            'content': old_content,
            'attachment': old_attachment
        }
    })

def delete_notice(request, notice_id):
    role = request.session.get('role')
    user_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT created_by, title
            FROM notices
            WHERE notice_id=%s
        """, [notice_id])
        row = cursor.fetchone()

    if not row:
        return HttpResponse("Notice not found")

    created_by, title = row

    if role == 'FACULTY' and created_by != user_id:
        return render(request, '403.html', {
        'message': 'You can only delete your own notices.'
    }, status=403)

    # 🔔 Get users BEFORE delete
    users = get_notice_users(notice_id)

    with connection.cursor() as cursor:
        cursor.execute("""
            DELETE FROM notices WHERE notice_id=%s
        """, [notice_id])

    # 🔔 Send notifications
    for uid in users:
        create_notification(
            user_id=uid,
            title="Notice Deleted",
            message=f"🗑️ Notice removed: {title}",
            link="/notifications/"
        )

    return redirect('admin_notices' if role == 'ADMIN' else 'faculty_notices')



def faculty_notices_view(request):
    if request.session.get('role') != 'FACULTY':
        return render(request, '403.html', {
        'message': 'Faculty Only.'
    }, status=403)

    faculty_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        # get faculty dept & sem
        cursor.execute("""
            SELECT department_id, semester_id
            FROM users
            WHERE user_id = %s
        """, [faculty_id])
        faculty_dept, faculty_sem = cursor.fetchone()

        cursor.execute("""
            SELECT
                n.notice_id,
                n.title,
                n.content,
                d.department_name,
                s.semester_number,
                n.created_at,
                n.attachment,
                u.name
            FROM notices n
            LEFT JOIN departments d ON n.department_id = d.department_id
            LEFT JOIN semesters s ON n.semester_id = s.semester_id
            JOIN users u ON n.created_by=u.user_id
            WHERE
                -- created by faculty
                n.created_by = %s

                -- global notices
                OR (n.department_id IS NULL AND n.semester_id IS NULL)

                -- department notices
                OR (n.department_id = %s AND n.semester_id IS NULL)

                -- department + semester notices
                OR (n.department_id = %s AND n.semester_id = %s)
            ORDER BY n.created_at DESC
        """, [
            faculty_id,
            faculty_dept,
            faculty_dept, faculty_sem
        ])

        notices = cursor.fetchall()

    return render(request, 'faculty_notices.html', {
        'notices': notices
    })

def create_event_view(request):
    role = request.session.get('role')
    user_id = request.session.get('user_id')

    if role not in ['ADMIN', 'FACULTY']:
        return render(request, '403.html', {
        'message': 'Only Admin or Faculty can create events.'
    }, status=403)

    if request.method == 'POST':
        title = request.POST['title']
        description = request.POST['description']
        event_date = request.POST['event_date']
        start_time = request.POST['start_time']
        end_time = request.POST['end_time']
        venue = request.POST['venue']
        google_form_link = request.POST['google_form_link']

        department_id = request.POST.get('department_id') or None
        semester_id = request.POST.get('semester_id') or None

        if role == 'FACULTY':
            faculty_incharge_id = user_id
            created_by = user_id
        else:
            faculty_incharge_id = request.POST['faculty_incharge_id']
            created_by = user_id

        poster = request.FILES.get('poster')
        poster_path = None
        if poster:
            from django.core.files.storage import FileSystemStorage
            fs = FileSystemStorage(location='media/events/posters')
            filename = fs.save(poster.name, poster)
            poster_path = f'events/posters/{filename}'

        with connection.cursor() as cursor:
            cursor.callproc(
                'create_event',
                [
                    title, description, event_date, start_time, end_time,
                    venue, poster_path, google_form_link,
                    created_by, faculty_incharge_id,
                    department_id, semester_id
                ]
            )
            cursor.execute("SELECT LAST_INSERT_ID()")
            event_id = cursor.fetchone()[0]

        # 🔔 NOTIFICATIONS
        users = get_event_notification_users(event_id)
        for uid in users:
            create_notification(
                user_id=uid,
                title="New Event",
                message=f"📅 New Event: {title}",
                link=f"/events/{event_id}/"
            )

        return redirect('/faculty/?event_created=1' if role == 'FACULTY' else '/admin/?event_created=1')

    # GET
    with connection.cursor() as cursor:
        cursor.execute("SELECT department_id, department_name FROM departments")
        departments = cursor.fetchall()

        cursor.execute("SELECT semester_id, semester_number FROM semesters")
        semesters = cursor.fetchall()

        faculties = []
        if role == 'ADMIN':
            cursor.execute("""
                SELECT user_id, name FROM users WHERE role = 'FACULTY'
            """)
            faculties = cursor.fetchall()

    return render(request, 'create_event.html', {
        'role': role,
        'departments': departments,
        'semesters': semesters,
        'faculties': faculties
    })
#create events

# =========================
# ADMIN – VIEW & APPROVE CORRECTIONS
# =========================

def attendance_corrections_admin(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
                r.request_id,
                r.attendance_id,
                r.requested_status,
                r.reason,
                r.requested_at,
                f.name AS faculty_name,
                s.name AS student_name,
                sub.subject_name,
                a.lecture_date
            FROM attendance_correction_requests r
            JOIN users f ON r.faculty_id = f.user_id
            JOIN attendance a ON r.attendance_id = a.attendance_id
            JOIN users s ON a.student_id = s.user_id
            JOIN timetable t ON a.timetable_id = t.timetable_id
            JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
            JOIN subjects sub ON fs.subject_id = sub.subject_id
            WHERE r.status = 'PENDING'
            ORDER BY r.requested_at DESC
        """)
        requests = cursor.fetchall()

    return render(request, 'admin_attendance_corrections.html', {
        'requests': requests
    })


def approve_attendance_request(request, request_id):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    admin_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.callproc(
            'approve_attendance_correction',
            [request_id, admin_id]
        )

    return redirect('attendance_corrections_admin')

def admin_attendance_report(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    dept = request.GET.get('department')
    sem = request.GET.get('semester')
    subject = request.GET.get('subject')
    class_id = request.GET.get('class')
    status = request.GET.get('status')

    query = """
        SELECT
            u.user_id,
            u.name,
            c.class_name,
            s.subject_name,
            calculate_attendance_percentage(u.user_id, s.subject_id) AS attendance_percentage,
            d.department_name,
            sems.semester_number
        FROM users u
        JOIN attendance a ON a.student_id = u.user_id
        JOIN timetable t ON a.timetable_id = t.timetable_id
        JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
        JOIN subjects s ON fs.subject_id = s.subject_id
        JOIN classes c ON u.class_id = c.class_id
        JOIN departments d ON u.department_id = d.department_id
        JOIN semesters sems ON u.semester_id = sems.semester_id
        WHERE u.role = 'STUDENT'
    """

    filters = []
    params = []

    if dept:
        filters.append("u.department_id = %s")
        params.append(dept)

    if sem:
        filters.append("u.semester_id = %s")
        params.append(sem)

    if class_id:
        filters.append("u.class_id = %s")
        params.append(class_id)

    if subject:
        filters.append("s.subject_id = %s")
        params.append(subject)

    if filters:
        query += " AND " + " AND ".join(filters)

    query += " GROUP BY u.user_id, s.subject_id"

    # ✅ Only 2 Status Filters
    if status == "short":
        query += " HAVING attendance_percentage < 75"
    elif status == "good":
        query += " HAVING attendance_percentage >= 75"

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        report = cursor.fetchall()

        cursor.execute("SELECT department_id, department_name FROM departments")
        departments = cursor.fetchall()

        cursor.execute("SELECT semester_id, semester_number FROM semesters")
        semesters = cursor.fetchall()

        cursor.execute("SELECT subject_id, subject_name FROM subjects")
        subjects = cursor.fetchall()

        cursor.execute("SELECT class_id, class_name FROM classes")
        classes = cursor.fetchall()

    return render(request, 'admin_attendance_report.html', {
        'report': report,
        'departments': departments,
        'semesters': semesters,
        'subjects': subjects,
        'classes': classes
    })


def admin_timetable_view(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                t.day_of_week,
                t.start_time,
                t.end_time,
                s.subject_name,
                c.class_name,
                sem.semester_number,
                f.name AS faculty_name
            FROM timetable t
            JOIN faculty_subjects fs ON t.faculty_subject_id = fs.faculty_subject_id
            JOIN subjects s ON fs.subject_id = s.subject_id
            JOIN semesters sem ON fs.semester_id = sem.semester_id
            JOIN classes c ON sem.class_id = c.class_id
            JOIN users f ON fs.faculty_id = f.user_id
            ORDER BY
                FIELD(t.day_of_week,
                    'Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'),
                t.start_time
        """)

        rows = cursor.fetchall()

    days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    timetable = {}
    time_slots = []

    for day, start, end, subject, class_name, semester, faculty in rows:
        slot = f"{start}-{end}"

        if slot not in timetable:
            timetable[slot] = {}
            time_slots.append(slot)

        if day not in timetable[slot]:
            timetable[slot][day] = []

        timetable[slot][day].append({
            "subject": subject,
            "class": class_name,
            "semester": semester,
            "faculty": faculty,
        })

    grid = []

    for slot in time_slots:
        row = {
            'time': slot,
            'cells': []
        }

        for day in days:
            row['cells'].append(
                timetable.get(slot, {}).get(day, [])
            )

        grid.append(row)

    return render(request, 'admin_timetable.html', {
        'days': days,
        'grid': grid
    })


def admin_notices_view(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT
                n.notice_id,
                n.title,
                n.content,
                u.name AS created_by,
                d.department_name,
                s.semester_number,
                n.created_at,
                n.attachment
            FROM notices n
            JOIN users u ON n.created_by = u.user_id
            LEFT JOIN departments d ON n.department_id = d.department_id
            LEFT JOIN semesters s ON n.semester_id = s.semester_id
            ORDER BY n.created_at DESC
        """)

        notices = cursor.fetchall()

    return render(request, 'admin_notices.html', {
        'notices': notices
    })

def admin_students_list_view(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    search = request.GET.get('search')
    department = request.GET.get('department')
    class_id = request.GET.get('class')
    semester = request.GET.get('semester')

    query = """
        SELECT
            u.user_id,
            u.name,
            u.email,
            d.department_name,
            c.class_name,
            sem.semester_number,
            u.is_active
        FROM users u
        LEFT JOIN departments d ON u.department_id = d.department_id
        LEFT JOIN classes c ON u.class_id = c.class_id
        LEFT JOIN semesters sem ON u.semester_id = sem.semester_id
        WHERE u.role = 'STUDENT'
    """

    filters = []
    params = []

    if search:
        filters.append("(u.name LIKE %s OR u.email LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    if department:
        filters.append("u.department_id = %s")
        params.append(department)

    if class_id:
        filters.append("u.class_id = %s")
        params.append(class_id)

    if semester:
        filters.append("u.semester_id = %s")
        params.append(semester)

    if filters:
        query += " AND " + " AND ".join(filters)

    query += " ORDER BY u.name"

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        students = cursor.fetchall()

        # Dropdown data
        cursor.execute("SELECT department_id, department_name FROM departments")
        departments = cursor.fetchall()

        cursor.execute("SELECT class_id, class_name FROM classes")
        classes = cursor.fetchall()

        cursor.execute("SELECT semester_id, semester_number FROM semesters")
        semesters = cursor.fetchall()

    return render(request, 'admin_all_students.html', {
        'students': students,
        'departments': departments,
        'classes': classes,
        'semesters': semesters
    })

def admin_all_faculty_view(request):
    if request.session.get('role') != 'ADMIN':
        return render(request, '403.html', {
        'message': 'Admins Only.'
    }, status=403)

    search = request.GET.get('search')
    department = request.GET.get('department')
    status = request.GET.get('status')

    query = """
        SELECT
            u.user_id,
            u.name,
            u.email,
            d.department_name,
            u.is_active
        FROM users u
        LEFT JOIN departments d ON u.department_id = d.department_id
        WHERE u.role = 'FACULTY'
    """

    filters = []
    params = []

    if search:
        filters.append("(u.name LIKE %s OR u.email LIKE %s)")
        params.extend([f"%{search}%", f"%{search}%"])

    if department:
        filters.append("u.department_id = %s")
        params.append(department)

    if status == "active":
        filters.append("u.is_active = 1")
    elif status == "inactive":
        filters.append("u.is_active = 0")

    if filters:
        query += " AND " + " AND ".join(filters)

    query += " ORDER BY u.name"

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        faculty = cursor.fetchall()

        cursor.execute("SELECT department_id, department_name FROM departments")
        departments = cursor.fetchall()

    return render(request, 'admin_all_faculty.html', {
        'faculty': faculty,
        'departments': departments
    })    

def student_coordinator_events_view(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session['user_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT 
    e.event_id,
    e.title,
    e.event_date,
    e.start_time,
    e.end_time,
    e.venue,
    e.poster_path,
    e.google_form_link
FROM event_coordinators ec
JOIN events e ON ec.event_id = e.event_id
WHERE ec.student_id = %s
  AND e.is_active = 1
  AND e.event_date >= CURDATE()
ORDER BY e.event_date ASC
        """, [student_id])

        events = cursor.fetchall()

    return render(request, 'student_coordinator_events.html', {
        'events': events
    })

def student_past_coordinator_events_view(request):
    if request.session.get('role') != 'STUDENT':
        return render(request, '403.html', {
        'message': 'Students Only.'
    }, status=403)

    student_id = request.session['user_id']

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT e.event_id,
    e.title,
    e.event_date,
    e.start_time,
    e.end_time,
    e.venue,
    e.poster_path,
    e.google_form_link
            FROM event_coordinators ec
            JOIN events e ON ec.event_id = e.event_id
            WHERE ec.student_id = %s
              AND e.is_active=1
              AND e.event_date < CURDATE()
            ORDER BY e.event_date DESC
        """, [student_id])

        past_events = cursor.fetchall()

    return render(request, 'student_past_coordinator_events.html', {
        'past_events': past_events
    })
