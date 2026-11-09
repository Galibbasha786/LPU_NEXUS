from django.urls import path

from . import views

app_name = 'social'

urlpatterns = [
    path('', views.feed, name='feed'),
    path('stories/create/', views.create_story, name='create_story'),
    path('posts/<str:post_id>/', views.post_detail, name='post'),
    path('posts/<str:post_id>/like/', views.like_post, name='like'),
    path('posts/<str:post_id>/comment/', views.comment_post, name='comment'),
    path('posts/<str:post_id>/reshare/', views.reshare_post, name='reshare'),
    path('posts/<str:post_id>/share/', views.share_post, name='share_post'),
    path('people/', views.people, name='people'),
    path('students/search/', views.search_students, name='search_students'),
    path('people/<str:peer_id>/block/', views.set_student_block, name='block'),
    path('chats/', views.chats, name='chats'),
    path('chats/direct/', views.start_direct_chat, name='start_direct'),
    path('chats/<str:chat_id>/', views.chat_detail, name='chat'),
    path('chats/<str:chat_id>/messages/', views.messages_json, name='messages'),
    path('chats/<str:chat_id>/send/', views.send_chat_message, name='send_message'),
    path('chats/<str:chat_id>/call/start/', views.start_video_call, name='start_call'),
    path('chats/<str:chat_id>/call/join/', views.join_video_call, name='join_call'),
    path('chats/<str:chat_id>/call/end/', views.end_video_call, name='end_call'),
    path('chats/<str:chat_id>/call/status/', views.call_status, name='call_status'),
    path('chats/<str:chat_id>/delete/', views.delete_chat_group, name='delete_group'),
    path('gifs/', views.gif_search, name='gif_search'),
]
