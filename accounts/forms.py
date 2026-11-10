from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from core.models import EmployerProfile, User, WorkerProfile


class LoginForm(forms.Form):
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, request=None, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        email, password = cleaned.get("email"), cleaned.get("password")
        if email and password:
            self.user = authenticate(self.request, username=email, password=password)
            if self.user is None:
                raise forms.ValidationError("Incorrect email or password.")
        return cleaned


class RegisterForm(forms.Form):
    role = forms.ChoiceField(
        choices=[(User.Role.WORKER, "Skilled worker"), (User.Role.EMPLOYER, "Employer / client")],
        initial=User.Role.WORKER,
    )
    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(max_length=100)
    email = forms.EmailField(max_length=100)
    password = forms.CharField(widget=forms.PasswordInput)

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"])
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    @transaction.atomic
    def save(self):
        data = self.cleaned_data
        user = User.objects.create_user(
            email=data["email"], password=data["password"], role=data["role"],
            first_name=data["first_name"].strip(), last_name=data["last_name"].strip(),
        )
        # Every user gets the matching profile row (WORKER_PROFILES / EMPLOYER_PROFILES)
        if user.role == User.Role.WORKER:
            WorkerProfile.objects.create(worker=user)
        else:
            EmployerProfile.objects.create(employer=user)
        return user
