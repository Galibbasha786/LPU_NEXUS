# navigation/urls.py
from django.urls import path
from . import views

app_name = "navigation"

urlpatterns = [
    path("", views.campus_map_view, name="map"),
    path("api/route/", views.api_route, name="api_route"),
    path("api/route-from-coords/", views.api_route_from_coords, name="api_route_from_coords"),
    path("api/locations/", views.api_locations, name="api_locations"),
    path("api/report-congestion/", views.api_report_congestion, name="api_report_congestion"),
    path("api/sync-obstacles/", views.api_sync_obstacles, name="api_sync_obstacles"),
    path("api/obstacles/create/", views.api_create_obstacle, name="api_create_obstacle"),
]