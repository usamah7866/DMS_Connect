from django.db import models
from django.contrib.auth.models import User

# Student Model
class Student(models.Model):
    name = models.CharField(max_length=100)
    class_name = models.CharField(max_length=20)
    roll_number = models.IntegerField()
    parent = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return self.name


# Teacher Model
class Teacher(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    subject = models.CharField(max_length=50)

    def __str__(self):
        return self.user.username


# Homework Model (Digital Diary)
class Homework(models.Model):
    class_name = models.CharField(max_length=20)
    subject = models.CharField(max_length=50)
    description = models.TextField()
    date = models.DateField(auto_now_add=True)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.class_name} - {self.subject}"