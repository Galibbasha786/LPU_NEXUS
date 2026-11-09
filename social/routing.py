from django.urls import path

from .consumers import SocialChatConsumer

websocket_urlpatterns = [
    path('ws/social/chats/<str:chat_id>/', SocialChatConsumer.as_asgi()),
]
