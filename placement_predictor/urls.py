from django.urls import path

from . import views

app_name = "placement_predictor"
urlpatterns = [path("", views.predict, name="predict")]
