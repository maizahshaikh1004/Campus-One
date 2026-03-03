from django.urls import path
from .views import (
    splash_view,
    login_view,
    logout_view,
    admin_dashboard,
    faculty_dashboard,
    student_dashboard,
    mark_attendance,
    view_attendance,
    request_attendance_correction,
    attendance_corrections_admin,
    approve_attendance_request,
    faculty_view_attendance,
    student_attendance_report,
    faculty_attendance_report,
    admin_attendance_report,
    student_timetable_view,
    faculty_timetable_view,
    admin_timetable_view,
    create_assignment_view,
    student_assignments_view,
    submit_assignment_view,
    faculty_assignment_submissions_view,
    create_notice,
    student_notices,
    get_semesters_by_department,
    get_classes_by_department,
    get_semesters_by_class,
    faculty_notices_view,
    admin_notices_view,
    edit_notice,
    delete_notice,
    create_event_view,
    student_events_view,
    event_detail_view,
    faculty_events_view,
    admin_events_view,
    assign_event_coordinator_view,
    edit_event_view,
    delete_event_view,
    student_coordinator_events_view,
    register_request_view,
    admin_registration_requests_view,
    approve_registration_view,
    reject_registration_view,
    verify_otp_view,
    bulk_user_upload_view, 
    notifications_view,
    mark_notification_read,
    notice_detail_view,
    unread_notification_count_view,
    profile_view,
    edit_profile_view,
    add_emergency_contact_view,
    delete_emergency_contact_view,
    faculty_assignments_view,
    delete_assignment_view,
    faculty_events_only_view,
    faculty_pending_submissions_view,
    student_subjects_view,
    student_pending_assignments_view,
    student_attendance_view,
    student_attendance_detail_view,
    delete_notification,
    mark_all_notifications_read,
    student_past_coordinator_events_view,
    get_subjects_by_semester,
    
    admin_students_list_view,
    admin_all_faculty_view,
    reject_attendance_request,
    view_student_profile,
    view_faculty_profile,
    resend_otp_view,
    student_attendance_detail_view,
)

urlpatterns = [
    path('', splash_view, name='splash'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),

    path('admin/', admin_dashboard, name='admin_dashboard'),
    path('faculty/', faculty_dashboard, name='faculty_dashboard'),
    path('student/', student_dashboard, name='student_dashboard'),

    path('attendance/mark/', mark_attendance, name='mark_attendance'),
    path('attendance/view/', view_attendance, name='view_attendance'),
    path('attendance/request-fix/', request_attendance_correction, name='request_attendance_correction'),

    path('admin/attendance-corrections/', attendance_corrections_admin, name='attendance_corrections_admin'),
    path(
        'admin/attendance-corrections/approve/<int:request_id>/',
        approve_attendance_request,
        name='approve_attendance_request'
    ),
    path('faculty/attendance/', faculty_view_attendance, name='faculty_view_attendance'),
    path('student/attendance-report/', student_attendance_report, name='student_attendance_report'),
    path('faculty/attendance-report/',faculty_attendance_report,name='faculty_attendance_report'),
    path('admin/attendance-report/',admin_attendance_report,name='admin_attendance_report'),
    path('student/timetable/',student_timetable_view,name='student_timetable'),
    path('faculty/timetable/',faculty_timetable_view,name='faculty_timetable'),
    path('admin/timetable/',admin_timetable_view,name='admin_timetable'),
    path('faculty/assignments/create/',create_assignment_view,name='create_assignment'),
    path('student/assignments/',student_assignments_view,name='student_assignments'),
    path('student/assignments/submit/<int:assignment_id>/',submit_assignment_view,name='submit_assignment'),
    path('faculty/assignments/submissions/',faculty_assignment_submissions_view,name='faculty_assignment_submissions'),
    path('notices/create/', create_notice, name='create_notice'),
    path('student/notices/', student_notices, name='student_notices'),
    path('ajax/get-semesters/', get_semesters_by_department, name='get_semesters_by_department'),
    path('faculty/notices/', faculty_notices_view, name='faculty_notices'),
    path('admin/notices/', admin_notices_view, name='admin_notices'),
    path('notices/edit/<int:notice_id>/',edit_notice,name='edit_notice'),
    path('notices/delete/<int:notice_id>/', delete_notice, name='delete_notice'),
    path('events/create/', create_event_view, name='create_event'),
    path('student/events/', student_events_view, name='student_events'),
    path('events/<int:event_id>/', event_detail_view, name='event_detail'),
    path('faculty-only/events/', faculty_events_only_view, name='faculty_events_only'),
    path('faculty/events/', faculty_events_view, name='faculty_events'),
    path('admin/events/', admin_events_view, name='admin_events'),
    path('events/<int:event_id>/assign-coordinators/',assign_event_coordinator_view,
    name='assign_event_coordinators'
),
    path('events/edit/<int:event_id>/', edit_event_view, name='edit_event'),
path('events/delete/<int:event_id>/', delete_event_view, name='delete_event'),
path(
    'student/coordinator/events/',
    student_coordinator_events_view,
    name='student_coordinator_events'
),

path('register/', register_request_view, name='register'),
path('admin/registration-requests/', admin_registration_requests_view, name='admin_registration_requests'),
path('admin/registration-requests/approve/<int:request_id>/', approve_registration_view, name='approve_registration'),
path('admin/registration-requests/reject/<int:request_id>/', reject_registration_view, name='reject_registration'),
path(
    'ajax/get-classes/',
    get_classes_by_department,
    name='get_classes_by_department'
),

path(
    'ajax/get-semesters-by-class/',
    get_semesters_by_class,
    name='get_semesters_by_class'
),
path('verify-otp/', verify_otp_view, name='verify_otp'),
path(
    'admin/bulk-users/',
    bulk_user_upload_view,
    name='bulk_user_upload'
),
path('notifications/', notifications_view, name='notifications'),
path(
    'notifications/read/<int:notification_id>/',
    mark_notification_read,
    name='mark_notification_read'
),
path('notices/<int:notice_id>/', notice_detail_view, name='notice_detail'),
path(
    'notifications/unread-count/',
    unread_notification_count_view,
    name='unread_notification_count'
),
path('profile/', profile_view, name='profile'),
path('profile/edit/', edit_profile_view, name='edit_profile'),


path('profile/emergency/add/', add_emergency_contact_view, name='add_emergency_contact'),
path(
    'profile/emergency/delete/<int:contact_id>/',
    delete_emergency_contact_view,
    name='delete_emergency_contact'
),
path(
    'faculty/assignments/',
    faculty_assignments_view,
    name='faculty_assignments'
),
path(
    'faculty/assignments/delete/<int:assignment_id>/',
    delete_assignment_view,
    name='delete_assignment'
),
path('faculty/pending-submissions/', faculty_pending_submissions_view, name='faculty_pending_submissions'),
path('student/subjects/', student_subjects_view, name='student_subjects'),
path(
    'student/pending-assignments/',
    student_pending_assignments_view,
    name='student_pending_assignments'
),
path('student/attendance/', student_attendance_view, name='student_attendance'),
path(
    'student/attendance/<int:subject_id>/',
    student_attendance_detail_view,
    name='student_attendance_detail'
),
path(
    'notifications/delete/<int:notification_id>/',
    delete_notification,
    name='delete_notification'
),
path(
    'notifications/mark-all-read/',
    mark_all_notifications_read,
    name='mark_all_notifications_read'
),
path(
    'student/coordinator/events/past/',
    student_past_coordinator_events_view,
    name='student_past_coordinator_events'
),
path(
    'ajax/get-subjects-by-semester/',
    get_subjects_by_semester,
    name='get_subjects_by_semester'
),

path(
    'admin/students/',
    admin_students_list_view,
    name='admin_students_list'
),
path('admin/faculty/', admin_all_faculty_view, name='admin_all_faculty'),
path(
    'attendance-corrections/<int:request_id>/reject/',
    reject_attendance_request,
    name='reject_attendance_request'
),
path('student/profile/<int:student_id>/', view_student_profile, name='view_student_profile'),
path('faculty/profile/<int:faculty_id>/', view_faculty_profile, name='view_faculty_profile'),

path('resend-otp/', resend_otp_view, name='resend_otp'),
path('student/attendance/<int:subject_id>/', student_attendance_detail_view, name='student_attendance_detail'),
]
