# accounts/urls.py
from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),

    # dashboards
    path('dashboard/student/', views.student_dashboard, name='student_dashboard'),
    path('dashboard/staff/', views.staff_dashboard, name='staff_dashboard'),
    path('dashboard/admin/', views.admin_dashboard, name='admin_dashboard'),

    # ---- admin management (renamed from admin/ → nexus-admin/) ----
    path('nexus-admin/staff/create/', views.admin_create_staff, name='admin_create_staff'),
    path('nexus-admin/staff/', views.admin_list_staff, name='admin_list_staff'),
    path('nexus-admin/students/', views.admin_list_students, name='admin_list_students'),

    # auth
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
]