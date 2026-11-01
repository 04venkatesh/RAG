from django.urls import path
from . import views

app_name = 'chat'

urlpatterns = [
    path('', views.chat_view, name='chat'),
    path('new/', views.new_chat_view, name='new_chat'),
    path('<int:session_id>/', views.chat_view, name='session_detail'),
    path('<int:session_id>/message/', views.chat_message_api, name='send_message'),
    path('<int:session_id>/delete/', views.delete_chat_view, name='delete_chat'),
]
