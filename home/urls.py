from django.urls import path
from . import views

app_name = 'home'

urlpatterns = [
    path('', views.home_view, name='home'),
    path('employer/', views.employer_home_view, name='employer'),
    path('employer/post/', views.post_job_view, name='post_job'),
    path('jobs/<int:job_id>/apply/', views.apply_view, name='apply'),
        path('jobs/', views.find_work_view, name='find_work'),
        path('reports/jobs-employers/', views.jobs_with_employers_view, name='jobs_join'),
    path('reports/jobs-with-applications/', views.jobs_with_applications_view, name='jobs_subquery'),
]
