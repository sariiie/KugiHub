from django.urls import path
from . import views

app_name = 'home'

urlpatterns = [
    # worker
    path('', views.home_view, name='home'),
    path('jobs/', views.find_work_view, name='find_work'),
    path('jobs/<int:job_id>/apply/', views.apply_view, name='apply'),
    path('my-applications/', views.my_applications_view, name='applications'),
    path('applications/<int:application_id>/cancel/', views.cancel_application_view, name='cancel_application'),

    # employer
    path('employer/', views.employer_home_view, name='employer'),
    path('employer/post/', views.post_job_view, name='post_job'),
    path('employer/jobs/', views.my_jobs_view, name='my_jobs'),
    path('employer/jobs/<int:job_id>/applicants/', views.job_applicants_view, name='job_applicants'),
    path('employer/jobs/<int:job_id>/edit/', views.edit_job_view, name='edit_job'),
    path('employer/jobs/<int:job_id>/delete/', views.delete_job_view, name='delete_job'),
    path('employer/jobs/<int:job_id>/status/', views.job_status_view, name='job_status'),
    path('employer/applications/<int:application_id>/decide/', views.application_decision_view, name='decide_application'),

    # both roles
    path('profile/', views.profile_view, name='profile'),
    path('trust-score/', views.trust_score_view, name='trust'),
    path('jobs/<int:job_id>/review/', views.review_view, name='review'),

    # JOIN / SUBQUERY activity
    path('reports/jobs-employers/', views.jobs_with_employers_view, name='jobs_join'),
    path('reports/jobs-with-applications/', views.jobs_with_applications_view, name='jobs_subquery'),
]
