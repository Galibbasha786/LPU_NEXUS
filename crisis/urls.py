# crisis/urls.py
from django.urls import path
from . import views

app_name = "crisis"

urlpatterns = [
    # Student
    path("report/", views.student_report, name="student_report"),
    path("my-reports/", views.my_reports, name="my_reports"),
    path("incident/<str:incident_id>/", views.incident_detail, name="incident_detail"),

    # Staff
    path("staff/queue/", views.staff_queue, name="staff_queue"),
    path("staff/incident/<str:incident_id>/verify/", views.staff_verify, name="staff_verify"),
    path("staff/incident/<str:incident_id>/assign/", views.staff_assign, name="staff_assign"),
    path("staff/incident/<str:incident_id>/status/", views.staff_update_status, name="staff_update_status"),
    path("staff/incident/<str:incident_id>/note/", views.staff_add_note, name="staff_add_note"),
    path("staff/announce/", views.announcement_new, name="announcement_new"),

    # Admin
    path("admin/toggle-crisis/", views.admin_toggle_crisis, name="admin_toggle_crisis"),
    path("admin/restricted-zones/", views.admin_restricted_zones, name="admin_restricted_zones"),
    path("admin/restricted-zones/<str:zone_id>/off/", views.admin_deactivate_zone, name="admin_deactivate_zone"),

    # API
    path("api/alerts/", views.api_active_alerts, name="api_active_alerts"),
    path("api/incidents/", views.api_incident_feed, name="api_incident_feed"),
]