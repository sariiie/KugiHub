from django.urls import path
from . import views

app_name = 'home'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('employer/', views.employer_home_view, name='employer'),
    path('employer/post/', views.post_job_view, name='post_job'),
    path('jobs/<int:job_id>/apply/', views.apply_view, name='apply'),
]
