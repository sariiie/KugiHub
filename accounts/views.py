from django.contrib import messages
from django.contrib.auth import login, logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .forms import LoginForm, RegisterForm


def _landing_for(user):
    return 'home:employer' if user.is_employer else 'home:home'


def login_view(request):
    if request.user.is_authenticated:
        return redirect(_landing_for(request.user))
    form = LoginForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        login(request, form.user)
        return redirect(request.GET.get('next') or _landing_for(form.user))
    return render(request, 'accounts/login.html', {'form': form})


def register_view(request):
    if request.user.is_authenticated:
        return redirect(_landing_for(request.user))
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Welcome to KugiHub! Your account is ready.')
        return redirect(_landing_for(user))
    return render(request, 'accounts/register.html', {'form': form})


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('accounts:login')
