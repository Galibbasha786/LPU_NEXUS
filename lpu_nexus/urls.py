from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('core/', include('core.urls')),
    path('navigation/', include('navigation.urls')),   # ← ADD THIS
    path('problems/', include('problems.urls')),
    path('ideas/', include('ideas.urls')),
    path('campus-ai/', include('campus_ai.urls')),
    path('', include('accounts.urls')),
        path("crisis/", include("crisis.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)