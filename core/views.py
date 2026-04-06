from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from .models import Homework, Teacher
from .models import Student

import requests

def login_view(request):
    if request.method == 'POST':

        # CAPTCHA verification
        captcha_response = request.POST.get('g-recaptcha-response')
        secret_key = '6LenYZ4sAAAAABDYLJq9kq4DzTX4xk4jQ5Up2lvD'

        data = {
            'secret': secret_key,
            'response': captcha_response
        }

        r = requests.post('https://www.google.com/recaptcha/api/siteverify', data=data)
        result = r.json()

        if not result['success']:
            return render(request, 'login.html', {'error': 'Invalid CAPTCHA'})

        # LOGIN LOGIC
        username = request.POST['username']
        password = request.POST['password']

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            if hasattr(user, 'teacher'):
                return redirect('teacher_dashboard')
            else:
                return redirect('parent_dashboard')

    return render(request, 'login.html')


@login_required
def teacher_dashboard(request):
    teacher = Teacher.objects.get(user=request.user)

    if request.method == 'POST':
        class_name = request.POST['class_name']
        subject = request.POST['subject']
        description = request.POST['description']

        Homework.objects.create(
            class_name=class_name,
            subject=subject,
            description=description,
            teacher=teacher
        )

    return render(request, 'teacher_dashboard.html')



@login_required
def parent_dashboard(request):
    student = Student.objects.get(parent=request.user)

    homework = Homework.objects.filter(class_name=student.class_name)

    return render(request, 'parent_dashboard.html', {'homework': homework})