import re
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg, Count, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.models import (
    EmployerProfile, Job, JobApplication, JobSkill, Review, Skill, User, WorkerProfile, WorkerSkill,
)

from .forms import (
    AccountForm, EmployerProfileForm, JobForm, ReviewForm, WorkerProfileForm,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _role_guard(request, role):
    """Send users to the dashboard that matches their role."""
    if request.user.role != role:
        if request.user.role == 'admin':
            return redirect('home:admin_home')
        return redirect('home:employer' if request.user.is_employer else 'home:home')
    return None


def _initial(user):
    return (user.first_name[:1] or user.email[:1]).upper()


def _profile_for(user):
    """The WorkerProfile or EmployerProfile that matches the user's role."""
    if user.is_employer:
        profile, _ = EmployerProfile.objects.get_or_create(employer=user)
    else:
        profile, _ = WorkerProfile.objects.get_or_create(worker=user)
    return profile


def _applied_job_ids(profile):
    """Job ids the worker has an active (not withdrawn) application for."""
    return set(profile.applications
               .exclude(status=JobApplication.Status.WITHDRAWN)
               .values_list('job_id', flat=True))


def _recalculate_trust(user):
    """Trust score = average rating of every review the user has received."""
    agg = Review.objects.filter(reviewee=user).aggregate(avg=Avg('rating'), n=Count('review_id'))
    avg = Decimal(str(agg['avg'] or 0)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    profile = _profile_for(user)
    profile.trust_score = avg
    profile.review_count = agg['n']
    profile.save(update_fields=['trust_score', 'review_count'])


def _sync_worker_skills(profile, chosen):
    chosen = list(chosen)
    WorkerSkill.objects.filter(worker=profile).exclude(skill__in=chosen).delete()
    existing = set(WorkerSkill.objects.filter(worker=profile).values_list('skill_id', flat=True))
    for skill in chosen:
        if skill.pk not in existing:
            WorkerSkill.objects.create(worker=profile, skill=skill)


def _sync_job_skills(job, chosen):
    chosen = list(chosen)
    JobSkill.objects.filter(job=job).exclude(skill__in=chosen).delete()
    existing = set(JobSkill.objects.filter(job=job).values_list('skill_id', flat=True))
    for skill in chosen:
        if skill.pk not in existing:
            JobSkill.objects.create(job=job, skill=skill)


def _own_job_or_404(request, job_id):
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)
    return profile, get_object_or_404(Job, pk=job_id, employer=profile)


# ---------------------------------------------------------------------------
# worker: dashboard, find work, apply
# ---------------------------------------------------------------------------
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
    applied_ids = _applied_job_ids(profile)
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
    application, created = JobApplication.objects.get_or_create(job=job, worker=profile)
    if created:
        messages.success(request, f'Application sent for "{job.title}".')
    elif application.status == JobApplication.Status.WITHDRAWN:
        # worker cancelled earlier and now changed their mind
        application.status = JobApplication.Status.PENDING
        application.applied_at = timezone.now()
        application.save(update_fields=['status', 'applied_at'])
        messages.success(request, f'Application re-sent for "{job.title}".')
    else:
        messages.info(request, 'You already applied to this job.')

    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('home:home')


@login_required
def find_work_view(request):
    """Worker 'Find work' page: search, filter and sort open jobs."""
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)

    q = request.GET.get('q', '').strip()
    fee_type = request.GET.get('fee', '')
    if fee_type not in Job.FeeType.values:
        fee_type = ''
    sort = request.GET.get('sort', 'newest')
    matched_only = request.GET.get('matched') == '1'

    jobs = (Job.objects.filter(status=Job.Status.OPEN)
            .select_related('employer__employer')
            .prefetch_related('skills'))
    if q:
        jobs = jobs.filter(Q(title__icontains=q) | Q(location__icontains=q)
                           | Q(skills__skill_name__icontains=q)).distinct()
    if fee_type:
        jobs = jobs.filter(fee_type=fee_type)

    if sort == 'fee_high':
        jobs = jobs.order_by('-fee_amount')
    elif sort == 'fee_low':
        jobs = jobs.order_by('fee_amount')
    else:
        if sort != 'match':
            sort = 'newest'
        jobs = jobs.order_by('-posted_at')

    my_skill_ids = set(profile.skills.values_list('pk', flat=True))
    applied_ids = _applied_job_ids(profile)
    cards = []
    for job in jobs[:100]:
        job_skills = list(job.skills.all())
        matched = any(s.pk in my_skill_ids for s in job_skills)
        if matched_only and not matched:
            continue
        cards.append({
            'job': job,
            'skills': job_skills,
            'matched': matched,
            'applied': job.pk in applied_ids,
        })
    if sort == 'match':
        cards.sort(key=lambda c: not c['matched'])   # matched first (stable sort)

    return render(request, 'home/find_work.html', {
        'initial': _initial(request.user),
        'cards': cards,
        'total': len(cards),
        'q': q,
        'fee_type': fee_type,
        'sort': sort,
        'matched_only': matched_only,
        'filtered': bool(q or fee_type or matched_only or sort != 'newest'),
        'fee_choices': Job.FeeType.choices,
        'current_url': request.get_full_path(),
    })


# ---------------------------------------------------------------------------
# worker: my applications + cancel
# ---------------------------------------------------------------------------
@login_required
def my_applications_view(request):
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)

    status = request.GET.get('status', '')
    all_apps = profile.applications.all()
    counts = dict(all_apps.values_list('status').annotate(n=Count('application_id')).order_by())

    apps = all_apps.select_related('job__employer__employer').order_by('-applied_at')
    if status in JobApplication.Status.values:
        apps = apps.filter(status=status)
    else:
        status = ''

    chips = [('', 'All', sum(counts.values()))] + [
        (value, label, counts.get(value, 0)) for value, label in JobApplication.Status.choices
    ]
    reviewed = set(Review.objects.filter(reviewer=request.user).values_list('job_id', flat=True))

    return render(request, 'home/my_applications.html', {
        'initial': _initial(request.user),
        'applications': apps,
        'chips': chips,
        'status': status,
        'reviewed_job_ids': reviewed,
    })


@login_required
@require_POST
def cancel_application_view(request, application_id):
    if (redirect_to := _role_guard(request, 'worker')):
        return redirect_to
    profile, _ = WorkerProfile.objects.get_or_create(worker=request.user)
    application = get_object_or_404(
        JobApplication.objects.select_related('job'), pk=application_id, worker=profile)
    A = JobApplication.Status

    if application.status == A.PENDING:
        application.status = A.WITHDRAWN
        application.save(update_fields=['status'])
        messages.success(request, f'Application for "{application.job.title}" cancelled.')
    elif application.status == A.ACCEPTED and application.job.status == Job.Status.ASSIGNED:
        # accepted but work has not started: worker backs out, job reopens
        with transaction.atomic():
            application.status = A.WITHDRAWN
            application.save(update_fields=['status'])
            job = application.job
            job.assigned_worker = None
            job.status = Job.Status.OPEN
            job.save(update_fields=['assigned_worker', 'status'])
        messages.success(request, f'You withdrew from "{application.job.title}". The job is open again.')
    else:
        messages.error(request, "This application can't be cancelled anymore.")
    return redirect('home:applications')


# ---------------------------------------------------------------------------
# employer: dashboard, post, list, edit, delete, status
# ---------------------------------------------------------------------------
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


@login_required
def my_jobs_view(request):
    """All of the employer's listings with manage actions."""
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)

    status = request.GET.get('status', '')
    counts = dict(profile.jobs.values_list('status').annotate(n=Count('job_id')).order_by())

    jobs = (profile.jobs
            .annotate(app_count=Count('applications'),
                      pending_count=Count('applications',
                                          filter=Q(applications__status=JobApplication.Status.PENDING)))
            .select_related('assigned_worker__worker'))
    if status in Job.Status.values:
        jobs = jobs.filter(status=status)
    else:
        status = ''

    chips = [('', 'All', sum(counts.values()))] + [
        (value, label, counts.get(value, 0)) for value, label in Job.Status.choices
    ]
    reviewed = set(Review.objects.filter(reviewer=request.user).values_list('job_id', flat=True))

    return render(request, 'home/my_jobs.html', {
        'initial': _initial(request.user),
        'jobs': jobs,
        'chips': chips,
        'status': status,
        'reviewed_job_ids': reviewed,
    })


@login_required
def edit_job_view(request, job_id):
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, job = _own_job_or_404(request, job_id)
    if job.status in (Job.Status.COMPLETED, Job.Status.CANCELLED):
        messages.error(request, f'A {job.get_status_display().lower()} job can no longer be edited.')
        return redirect('home:my_jobs')

    form = JobForm(request.POST or None, instance=job,
                   initial={'skills': list(job.skills.values_list('pk', flat=True))})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            job = form.save(commit=False)
            job.save()
            _sync_job_skills(job, form.cleaned_data['skills'])
        messages.success(request, f'"{job.title}" was updated.')
        return redirect('home:my_jobs')
    return render(request, 'home/edit_job.html', {
        'form': form, 'job': job, 'initial': _initial(request.user),
    })


@login_required
@require_POST
def delete_job_view(request, job_id):
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, job = _own_job_or_404(request, job_id)
    if job.status in (Job.Status.OPEN, Job.Status.CANCELLED):
        title = job.title
        job.delete()
        messages.success(request, f'"{title}" was deleted.')
    else:
        messages.error(request, 'Only open or cancelled jobs can be deleted. Cancel the job first.')
    return redirect('home:my_jobs')


@login_required
@require_POST
def job_status_view(request, job_id):
    """Employer moves a job along: start -> complete, or cancel."""
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, job = _own_job_or_404(request, job_id)
    action = request.POST.get('action')
    S = Job.Status

    if action == 'start' and job.status == S.ASSIGNED:
        job.status = S.IN_PROGRESS
        job.save(update_fields=['status'])
        messages.success(request, f'"{job.title}" is now in progress.')
    elif action == 'complete' and job.status == S.IN_PROGRESS:
        job.status = S.COMPLETED
        job.completed_at = timezone.now()
        job.save(update_fields=['status', 'completed_at'])
        messages.success(request, f'"{job.title}" is completed. Leave a review for the worker.')
        return redirect('home:review', job_id=job.pk)
    elif action == 'cancel' and job.status in (S.OPEN, S.ASSIGNED, S.IN_PROGRESS):
        with transaction.atomic():
            job.status = S.CANCELLED
            job.save(update_fields=['status'])
            job.applications.filter(status=JobApplication.Status.PENDING).update(
                status=JobApplication.Status.REJECTED)
        messages.info(request, f'"{job.title}" was cancelled.')
    else:
        messages.error(request, "That action isn't available for this job's current status.")
    return redirect('home:my_jobs')


# ---------------------------------------------------------------------------
# employer: applicants (accept / reject)
# ---------------------------------------------------------------------------
@login_required
def job_applicants_view(request, job_id):
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, job = _own_job_or_404(request, job_id)

    applications = list(job.applications
                        .select_related('worker__worker')
                        .prefetch_related('worker__worker_skills__skill'))
    # pending first, then highest trust score
    applications.sort(key=lambda a: (a.status != JobApplication.Status.PENDING, -a.worker.trust_score))

    return render(request, 'home/job_applicants.html', {
        'initial': _initial(request.user),
        'job': job,
        'applications': applications,
        'can_decide': job.status == Job.Status.OPEN,
    })


@login_required
@require_POST
def application_decision_view(request, application_id):
    if (redirect_to := _role_guard(request, 'employer')):
        return redirect_to
    profile, _ = EmployerProfile.objects.get_or_create(employer=request.user)
    application = get_object_or_404(
        JobApplication.objects.select_related('job', 'worker__worker'),
        pk=application_id, job__employer=profile)
    A = JobApplication.Status
    action = request.POST.get('action')
    name = application.worker.worker.get_full_name()

    if action == 'accept':
        with transaction.atomic():
            job = Job.objects.select_for_update().get(pk=application.job_id)
            if job.status != Job.Status.OPEN or application.status != A.PENDING:
                messages.error(request, "This application can't be accepted anymore.")
            else:
                application.status = A.ACCEPTED
                application.save(update_fields=['status'])
                job.assigned_worker = application.worker
                job.status = Job.Status.ASSIGNED
                job.save(update_fields=['assigned_worker', 'status'])
                job.applications.filter(status=A.PENDING).exclude(
                    pk=application.pk).update(status=A.REJECTED)
                messages.success(request, f'{name} was accepted for "{job.title}".')
    elif action == 'reject' and application.status == A.PENDING:
        application.status = A.REJECTED
        application.save(update_fields=['status'])
        messages.info(request, f"{name}'s application was rejected.")
    else:
        messages.error(request, "That action isn't available for this application.")
    return redirect('home:job_applicants', job_id=application.job_id)


# ---------------------------------------------------------------------------
# both roles: profile, trust score, reviews
# ---------------------------------------------------------------------------
@login_required
def profile_view(request):
    if request.user.role == 'admin':
        return redirect('home:admin_home')
    user = request.user
    profile = _profile_for(user)
    if user.is_employer:
        ProfileForm, initial = EmployerProfileForm, None
    else:
        ProfileForm = WorkerProfileForm
        initial = {'skills': list(profile.skills.values_list('pk', flat=True))}

    account_form = AccountForm(request.POST or None, instance=user, prefix='acct')
    profile_form = ProfileForm(request.POST or None, instance=profile, prefix='prof', initial=initial)

    if request.method == 'POST' and account_form.is_valid() and profile_form.is_valid():
        with transaction.atomic():
            account_form.save()
            profile = profile_form.save()
            if not user.is_employer:
                chosen = list(profile_form.cleaned_data['skills'])
                for name in profile_form.cleaned_data['new_skills']:
                    # reuse an existing skill (any capitalisation) or create it
                    skill = (Skill.objects.filter(skill_name__iexact=name).first()
                             or Skill.objects.create(skill_name=name))
                    if skill not in chosen:
                        chosen.append(skill)
                _sync_worker_skills(profile, chosen)
        messages.success(request, 'Your profile was updated.')
        return redirect('home:profile')

    if user.is_employer:
        stats = [
            ('Jobs posted', profile.jobs.count()),
            ('Completed', profile.jobs.filter(status=Job.Status.COMPLETED).count()),
            ('Applications received', JobApplication.objects.filter(job__employer=profile).count()),
        ]
    else:
        stats = [
            ('Jobs completed', profile.assigned_jobs.filter(status=Job.Status.COMPLETED).count()),
            ('Applications sent', profile.applications.count()),
            ('Skills listed', profile.worker_skills.count()),
        ]

    if user.is_employer:
        checklist = [
            ('Company name', bool(profile.company_name)),
            ('About your business', bool(profile.description)),
            ('Address', bool(profile.address)),
            ('Phone number', bool(user.phone)),
            ('City', bool(user.city)),
        ]
    else:
        checklist = [
            ('Headline', bool(profile.headline)),
            ('Bio', bool(profile.bio)),
            ('Years of experience', bool(profile.years_experience)),
            ('At least one skill', profile.worker_skills.exists()),
            ('Phone number', bool(user.phone)),
            ('City', bool(user.city)),
        ]
    completion = round(100 * sum(done for _, done in checklist) / len(checklist))

    return render(request, 'home/profile.html', {
        'initial': _initial(user),
        'profile': profile,
        'account_form': account_form,
        'profile_form': profile_form,
        'stats': stats,
        'checklist': checklist,
        'completion': completion,
        'trust_percent': int(profile.trust_score / 5 * 100),
    })


@login_required
def trust_score_view(request):
    if request.user.role == 'admin':
        return redirect('home:admin_home')
    user = request.user
    profile = _profile_for(user)

    received = Review.objects.filter(reviewee=user)
    counts = {r['rating']: r['n']
              for r in received.values('rating').annotate(n=Count('review_id')).order_by()}
    total = sum(counts.values())
    distribution = [{
        'stars': s,
        'n': counts.get(s, 0),
        'pct': int(counts.get(s, 0) * 100 / total) if total else 0,
    } for s in (5, 4, 3, 2, 1)]

    score = profile.trust_score
    if not total:
        label = 'No rating yet'
    elif score >= Decimal('4.5'):
        label = 'Excellent'
    elif score >= Decimal('3.5'):
        label = 'Good'
    elif score >= Decimal('2.5'):
        label = 'Fair'
    else:
        label = 'Needs improvement'

    if user.is_employer:
        pending = (Job.objects.filter(employer=profile, status=Job.Status.COMPLETED,
                                      assigned_worker__isnull=False)
                   .exclude(reviews__reviewer=user).select_related('assigned_worker__worker'))
    else:
        pending = (Job.objects.filter(assigned_worker=profile, status=Job.Status.COMPLETED)
                   .exclude(reviews__reviewer=user).select_related('employer__employer'))

    return render(request, 'home/trust_score.html', {
        'initial': _initial(user),
        'profile': profile,
        'score': score,
        'label': label,
        'trust_percent': int(score / 5 * 100),
        'total': total,
        'distribution': distribution,
        'reviews': received.select_related('job', 'reviewer'),
        'pending_reviews': pending,
        'given_count': Review.objects.filter(reviewer=user).count(),
    })


@login_required
def review_view(request, job_id):
    if request.user.role == 'admin':
        return redirect('home:admin_home')
    """Rate the other person on a completed job (employer <-> worker)."""
    user = request.user
    job = get_object_or_404(
        Job.objects.select_related('employer__employer', 'assigned_worker__worker'), pk=job_id)

    if job.status != Job.Status.COMPLETED or job.assigned_worker is None:
        messages.error(request, 'You can only review a completed job.')
        return redirect('home:trust')

    if user.is_employer and job.employer_id == user.pk:
        reviewee = job.assigned_worker.worker
        reviewee_role = 'worker'
    elif user.is_worker and job.assigned_worker_id == user.pk:
        reviewee = job.employer.employer
        reviewee_role = 'employer'
    else:
        messages.error(request, "You weren't part of that job.")
        return redirect('home:trust')

    if Review.objects.filter(job=job, reviewer=user).exists():
        messages.info(request, 'You already reviewed this job.')
        return redirect('home:trust')

    form = ReviewForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            review = form.save(commit=False)
            review.job = job
            review.reviewer = user
            review.reviewee = reviewee
            review.save()
            _recalculate_trust(reviewee)
        messages.success(request, f'Thanks! Your review for {reviewee.get_full_name()} was saved.')
        return redirect('home:trust')

    return render(request, 'home/review_form.html', {
        'initial': _initial(user),
        'job': job,
        'form': form,
        'reviewee': reviewee,
        'reviewee_role': reviewee_role,
    })


# ---------------------------------------------------------------------------
# administrator: overview + reports (JOIN and SUBQUERY)
# ---------------------------------------------------------------------------
def _admin_guard(request):
    if request.user.role != User.Role.ADMIN:
        return redirect('home:employer' if request.user.is_employer else 'home:home')
    return None


def _pretty_sql(queryset):
    """Readable copy of the SQL Django generates, shown in the report footer."""
    sql = str(queryset.query)
    sql = re.sub(r'^SELECT .*? FROM ', 'SELECT ...\nFROM ', sql, count=1, flags=re.S)
    sql = re.sub(r' (INNER JOIN|LEFT OUTER JOIN|WHERE|GROUP BY|ORDER BY) ', r'\n\1 ', sql)
    return sql.replace('(SELECT', '(\n    SELECT')


def _attach_application_counts(jobs):
    counts = dict(JobApplication.objects.values_list('job_id')
                  .annotate(n=Count('application_id')).order_by())
    for job in jobs:
        job.app_count = counts.get(job.pk, 0)
    return jobs


@login_required
def admin_home_view(request):
    if (redirect_to := _admin_guard(request)):
        return redirect_to
    roles = dict(User.objects.values_list('role').annotate(n=Count('user_id')).order_by())
    statuses = dict(Job.objects.values_list('status').annotate(n=Count('job_id')).order_by())
    applied_ids = JobApplication.objects.values('job_id')
    stale = (Job.objects.filter(status=Job.Status.OPEN)
             .exclude(job_id__in=Subquery(applied_ids)).count())
    return render(request, 'home/admin_home.html', {
        'initial': _initial(request.user),
        'workers': roles.get('worker', 0),
        'employers': roles.get('employer', 0),
        'jobs_total': sum(statuses.values()),
        'open_jobs': statuses.get(Job.Status.OPEN, 0),
        'applications': JobApplication.objects.count(),
        'stale': stale,
    })


@login_required
def admin_listings_view(request):
    """JOIN: jobs + employer_profiles + users."""
    if (redirect_to := _admin_guard(request)):
        return redirect_to
    status = request.GET.get('status', '')
    jobs = Job.objects.select_related('employer__employer').order_by('-posted_at')
    if status in Job.Status.values:
        jobs = jobs.filter(status=status)
    else:
        status = ''
    counts = dict(Job.objects.values_list('status').annotate(n=Count('job_id')).order_by())
    chips = [('', 'All', sum(counts.values()))] + [
        (value, label, counts.get(value, 0)) for value, label in Job.Status.choices]
    return render(request, 'home/admin_listings.html', {
        'initial': _initial(request.user),
        'jobs': _attach_application_counts(list(jobs[:200])),
        'chips': chips,
        'status': status,
        'sql': _pretty_sql(jobs),
    })


@login_required
def admin_engagement_view(request):
    """SUBQUERY: listings with / without applications."""
    if (redirect_to := _admin_guard(request)):
        return redirect_to
    show = request.GET.get('show', 'none')
    if show not in ('none', 'applied'):
        show = 'none'

    applied_ids = JobApplication.objects.values('job_id')                       # inner query
    with_applicants = Job.objects.filter(job_id__in=Subquery(applied_ids))      # outer query
    no_applicants = (Job.objects.filter(status=Job.Status.OPEN)
                     .exclude(job_id__in=Subquery(applied_ids)))

    jobs = with_applicants if show == 'applied' else no_applicants
    jobs = jobs.select_related('employer__employer').order_by('-posted_at')
    return render(request, 'home/admin_engagement.html', {
        'initial': _initial(request.user),
        'jobs': _attach_application_counts(list(jobs[:200])),
        'show': show,
        'n_applied': with_applicants.count(),
        'n_none': no_applicants.count(),
        'sql': _pretty_sql(jobs),
    })
