"""
KugiHub models - mapped from SARIO_ERD.pdf

Entities (10):  USERS, WORKER_PROFILES, EMPLOYER_PROFILES, SKILLS,
                WORKER_SKILLS, JOBS, JOB_SKILLS, JOB_APPLICATIONS,
                REVIEWS, PORTFOLIO_ITEMS

Every model sets db_table so the Supabase tables carry the same names as
the ERD, and PK / FK columns use the ERD column names (user_id, worker_id,
employer_id, job_id, ...).
"""
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------
class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)          # stored (hashed) in password_hash
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Role(models.TextChoices):
        WORKER = "worker", "Skilled Worker"
        EMPLOYER = "employer", "Employer/Client"
        ADMIN = "admin", "Administrator"

    user_id = models.AutoField(primary_key=True)                                   # PK
    email = models.EmailField(max_length=100, unique=True)                         # UK
    # ERD column "password_hash" - Django's hashed password lives here
    password = models.CharField("password", max_length=255, db_column="password_hash")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.WORKER)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, null=True, blank=True)
    city = models.CharField(max_length=80, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    # Not in the ERD: required by django.contrib.admin (access to /admin/)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name

    @property
    def is_worker(self):
        return self.role == self.Role.WORKER

    @property
    def is_employer(self):
        return self.role == self.Role.EMPLOYER


# ---------------------------------------------------------------------------
# WORKER_PROFILES   (PK,FK worker_id -> USERS)      1 : 1
# ---------------------------------------------------------------------------
class WorkerProfile(models.Model):
    class Availability(models.TextChoices):
        AVAILABLE = "available", "Available"
        BUSY = "busy", "Busy"
        UNAVAILABLE = "unavailable", "Unavailable"

    worker = models.OneToOneField(
        User, on_delete=models.CASCADE, primary_key=True,
        db_column="worker_id", related_name="worker_profile",
    )
    headline = models.CharField(max_length=120, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    years_experience = models.PositiveSmallIntegerField(default=0)                 # tinyint
    availability = models.CharField(
        max_length=12, choices=Availability.choices, default=Availability.AVAILABLE
    )
    trust_score = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    review_count = models.IntegerField(default=0)

    skills = models.ManyToManyField(
        "Skill", through="WorkerSkill", related_name="workers"
    )

    class Meta:
        db_table = "worker_profiles"

    def __str__(self):
        return f"Worker: {self.worker.get_full_name()}"


# ---------------------------------------------------------------------------
# EMPLOYER_PROFILES   (PK,FK employer_id -> USERS)   1 : 1
# ---------------------------------------------------------------------------
class EmployerProfile(models.Model):
    class EmployerType(models.TextChoices):
        INDIVIDUAL = "individual", "Private client"
        BUSINESS = "business", "Business"

    employer = models.OneToOneField(
        User, on_delete=models.CASCADE, primary_key=True,
        db_column="employer_id", related_name="employer_profile",
    )
    employer_type = models.CharField(
        max_length=12, choices=EmployerType.choices, default=EmployerType.INDIVIDUAL
    )
    company_name = models.CharField(max_length=100, null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    address = models.CharField(max_length=255, null=True, blank=True)
    trust_score = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    review_count = models.IntegerField(default=0)

    class Meta:
        db_table = "employer_profiles"

    def __str__(self):
        return self.company_name or f"Employer: {self.employer.get_full_name()}"


# ---------------------------------------------------------------------------
# SKILLS
# ---------------------------------------------------------------------------
class Skill(models.Model):
    skill_id = models.AutoField(primary_key=True)
    skill_name = models.CharField(max_length=50, unique=True)                      # UK
    category = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = "skills"
        ordering = ["skill_name"]

    def __str__(self):
        return self.skill_name


# ---------------------------------------------------------------------------
# WORKER_SKILLS   composite PK (worker_id, skill_id)   -> WORKER_PROFILES x SKILLS
# ---------------------------------------------------------------------------
class WorkerSkill(models.Model):
    class Proficiency(models.TextChoices):
        BEGINNER = "beginner", "Beginner"
        INTERMEDIATE = "intermediate", "Intermediate"
        EXPERT = "expert", "Expert"

    pk = models.CompositePrimaryKey("worker", "skill")
    worker = models.ForeignKey(
        WorkerProfile, on_delete=models.CASCADE,
        db_column="worker_id", related_name="worker_skills",
    )
    skill = models.ForeignKey(
        Skill, on_delete=models.CASCADE,
        db_column="skill_id", related_name="worker_skills",
    )
    proficiency = models.CharField(
        max_length=12, choices=Proficiency.choices, default=Proficiency.INTERMEDIATE
    )
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)     # tinyint

    class Meta:
        db_table = "worker_skills"

    def __str__(self):
        return f"{self.worker} - {self.skill} ({self.proficiency})"


# ---------------------------------------------------------------------------
# JOBS
# ---------------------------------------------------------------------------
class Job(models.Model):
    class FeeType(models.TextChoices):
        FIXED = "fixed", "Fixed"
        HOURLY = "hourly", "Hourly"
        DAILY = "daily", "Daily"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"

    job_id = models.AutoField(primary_key=True)
    employer = models.ForeignKey(
        EmployerProfile, on_delete=models.CASCADE,
        db_column="employer_id", related_name="jobs",
    )
    assigned_worker = models.ForeignKey(
        WorkerProfile, on_delete=models.SET_NULL, null=True, blank=True,
        db_column="assigned_worker_id", related_name="assigned_jobs",
    )
    title = models.CharField(max_length=120)
    description = models.TextField()
    location = models.CharField(max_length=255)
    fee_amount = models.DecimalField(max_digits=10, decimal_places=2)
    fee_type = models.CharField(max_length=10, choices=FeeType.choices, default=FeeType.FIXED)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    start_date = models.DateField(null=True, blank=True)
    posted_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    skills = models.ManyToManyField(Skill, through="JobSkill", related_name="jobs")

    class Meta:
        db_table = "jobs"
        ordering = ["-posted_at"]

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# JOB_SKILLS   composite PK (job_id, skill_id)   -> JOBS x SKILLS
# ---------------------------------------------------------------------------
class JobSkill(models.Model):
    pk = models.CompositePrimaryKey("job", "skill")
    job = models.ForeignKey(
        Job, on_delete=models.CASCADE, db_column="job_id", related_name="job_skills"
    )
    skill = models.ForeignKey(
        Skill, on_delete=models.CASCADE, db_column="skill_id", related_name="job_skills"
    )

    class Meta:
        db_table = "job_skills"

    def __str__(self):
        return f"{self.job} requires {self.skill}"


# ---------------------------------------------------------------------------
# JOB_APPLICATIONS
# ---------------------------------------------------------------------------
class JobApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        WITHDRAWN = "withdrawn", "Withdrawn"

    application_id = models.AutoField(primary_key=True)
    job = models.ForeignKey(
        Job, on_delete=models.CASCADE, db_column="job_id", related_name="applications"
    )
    worker = models.ForeignKey(
        WorkerProfile, on_delete=models.CASCADE,
        db_column="worker_id", related_name="applications",
    )
    message = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    applied_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "job_applications"
        ordering = ["-applied_at"]

    def __str__(self):
        return f"{self.worker} -> {self.job} [{self.status}]"


# ---------------------------------------------------------------------------
# REVIEWS   (job + reviewer (USERS) + reviewee (USERS))
# ---------------------------------------------------------------------------
class Review(models.Model):
    review_id = models.AutoField(primary_key=True)
    job = models.ForeignKey(
        Job, on_delete=models.CASCADE, db_column="job_id", related_name="reviews"
    )
    reviewer = models.ForeignKey(
        User, on_delete=models.CASCADE,
        db_column="reviewer_id", related_name="reviews_given",
    )
    reviewee = models.ForeignKey(
        User, on_delete=models.CASCADE,
        db_column="reviewee_id", related_name="reviews_received",
    )
    rating = models.PositiveSmallIntegerField(                                      # tinyint
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "reviews"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.rating}/5 for {self.reviewee} on {self.job}"


# ---------------------------------------------------------------------------
# PORTFOLIO_ITEMS
# ---------------------------------------------------------------------------
class PortfolioItem(models.Model):
    portfolio_id = models.AutoField(primary_key=True)
    worker = models.ForeignKey(
        WorkerProfile, on_delete=models.CASCADE,
        db_column="worker_id", related_name="portfolio_items",
    )
    title = models.CharField(max_length=100)
    description = models.TextField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    photo_url = models.URLField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "portfolio_items"

    def __str__(self):
        return self.title
