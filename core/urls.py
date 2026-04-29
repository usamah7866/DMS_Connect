from django.urls import path
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('admissions/', views.admissions_view, name='admissions'),
    path('admissions/thank-you/', views.admission_thank_you_view, name='admission_thank_you'),
    path('careers/', views.careers_view, name='careers'),
    path('careers/thank-you/', views.career_thank_you_view, name='career_thank_you'),
    path('teacher/', views.teacher_dashboard, name='teacher_dashboard'),
    path('student/', views.student_dashboard, name='student_dashboard'),
    path('parent/', views.student_dashboard, name='legacy_parent_dashboard'),
    path('logout/', views.logout_view, name='logout'),
]



