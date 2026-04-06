from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('teacher/', views.teacher_dashboard, name='teacher_dashboard'),
    path('parent/', views.parent_dashboard, name='parent_dashboard'),
]