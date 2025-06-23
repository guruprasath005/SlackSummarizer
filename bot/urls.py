from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('health/', views.health, name='health'),
    path('slack/test/', views.slack_test, name='slack_test'),
    path('slack/events/', views.slack_events, name='slack_events'),
    path('slack/commands/', views.slack_commands, name='slack_commands'),
    path('slack/commands/fast/', views.slack_commands_fast, name='slack_commands_fast'),
    path('slack/commands/ultra/', views.slack_commands_ultra_fast, name='slack_commands_ultra_fast'),
] 