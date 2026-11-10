from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.models import EmployerProfile, Job, JobApplication, JobSkill, WorkerProfile

from .forms import JobForm


def _role_guard(request, role):
    """Send users to the dashboard that matches their role."""
    if request.user.role != role:
        return redirect('home:employer' if request.user.is_employer else 'home:home')
    return None


def _initial(user):
    return (user.first_name[:1] or user.email[:1]).upper()


@login_required
def home_view(request):
    """Worker dashboard: browse open jobs, apply, see own profile."""
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)

    q = request.GET.get('q', '').strip()
    jobs = (Job.objects.filter(status=Job.Status.OPEN)
            .select_related('employer__employer')
            .prefetch_related('skills'))
    if q:
        jobs = jobs.filter(Q(title__icontains=q) | Q(location__icontains=q)
                           | Q(skills__skill_name__icontains=q)).distinct()

    my_skill_ids = set(profile.skills.values_list('pk', flat=True))
    applied_ids = set(profile.applications.values_list('job_id', flat=True))
    job_cards = []
    for job in jobs[:20]:
        job_skills = list(job.skills.all())
        job_cards.append({
            'job': job,
            'skills': job_skills,
            'matched': any(s.pk in my_skill_ids for s in job_skills),
            'applied': job.pk in applied_ids,
        })
    job_cards.sort(key=lambda c: not c['matched'])   # matched jobs first (stable sort)

    checks = [profile.headline, profile.bio, profile.years_experience,
              my_skill_ids, request.user.phone, request.user.city]
    completion = round(100 * sum(bool(c) for c in checks) / len(checks))

    return render(request, 'home/home.html', {
        'profile': profile,
        'initial': _initial(request.user),
        'job_cards': job_cards,
        'my_skills': profile.worker_skills.select_related('skill'),
        'completed_jobs': profile.assigned_jobs.filter(status=Job.Status.COMPLETED).count(),
        'trust_percent': int(profile.trust_score / 5 * 100),
        'completion': completion,
        'q': q,
    })


@login_required
@require_POST
def apply_view(request, job_id):
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    job = get_object_or_404(Job, pk=job_id, status=Job.Status.OPEN)
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)
    _, created = JobApplication.objects.get_or_create(job=job, worker=profile)
    if created:
        messages.success(request, f'Application sent for "{job.title}".')
    else:
        messages.info(request, 'You already applied to this job.')
    return redirect('home:home')


@login_required
def employer_home_view(request):
    """Employer dashboard: own listings, application counts, trust score."""
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)

    listings = (profile.jobs.annotate(app_count=Count('applications'))
                .exclude(status=Job.Status.CANCELLED))
    active = listings.filter(status__in=[Job.Status.OPEN, Job.Status.ASSIGNED, Job.Status.IN_PROGRESS])

    checks = [profile.description, profile.address, request.user.phone,
              request.user.city, profile.company_name]
    completion = round(100 * sum(bool(c) for c in checks) / len(checks))

    return render(request, 'home/employer.html', {
        'profile': profile,
        'initial': _initial(request.user),
        'listings': active[:10],
        'active_count': active.count(),
        'application_total': JobApplication.objects.filter(job__employer=profile).count(),
        'completed_jobs': profile.jobs.filter(status=Job.Status.COMPLETED).count(),
        'trust_percent': int(profile.trust_score / 5 * 100),
        'completion': completion,
    })


@login_required
def post_job_view(request):
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)
    form = JobForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        job = form.save(commit=False)
        job.employer = profile
        job.save()
        for skill in form.cleaned_data['skills']:      # JOB_SKILLS rows
            JobSkill.objects.create(job=job, skill=skill)
        messages.success(request, f'"{job.title}" is now live.')
        return redirect('home:employer')
    return render(request, 'home/post_job.html', {'form': form, 'initial': _initial(request.user)})
