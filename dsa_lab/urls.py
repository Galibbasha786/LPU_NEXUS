from django.urls import path
from . import views

app_name = 'dsa_lab'

urlpatterns = [
    path('', views.lab_home, name='home'),
    path('progress/', views.save_progress, name='progress'),
]
