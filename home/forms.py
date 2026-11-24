from django import forms

from core.models import EmployerProfile, Job, Review, Skill, User, WorkerProfile


class JobForm(forms.ModelForm):
    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.all(), required=False,
        widget=forms.CheckboxSelectMultiple, label='Skills needed',
    )

    class Meta:
        model = Job
        fields = ['title', 'description', 'location', 'fee_amount', 'fee_type', 'start_date', 'skills']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 5}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
        }


class AccountForm(forms.ModelForm):
    """Basic account details stored in USERS."""

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'phone', 'city']
        labels = {'first_name': 'First name', 'last_name': 'Last name'}


class WorkerProfileForm(forms.ModelForm):
    # Not a model field: WORKER_SKILLS is synced by hand in the view.
    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.all(), required=False,
        widget=forms.CheckboxSelectMultiple, label='Your skills',
    )
    new_skills = forms.CharField(
        required=False, max_length=400, label='Add new skills',
        widget=forms.TextInput(attrs={'placeholder': 'e.g. Make-up artist, Hair stylist'}),
    )

    class Meta:
        model = WorkerProfile
        fields = ['headline', 'bio', 'years_experience', 'availability']
        widgets = {'bio': forms.Textarea(attrs={'rows': 5})}
        labels = {'years_experience': 'Years of experience'}

    def clean_new_skills(self):
        """'Make-up artist, Baker' -> ['Make-up artist', 'Baker'] (no blanks/duplicates)."""
        names, seen = [], set()
        for part in self.cleaned_data.get('new_skills', '').split(','):
            name = ' '.join(part.split())
            if not name or name.lower() in seen:
                continue
            if len(name) > 50:
                raise forms.ValidationError('Each skill must be 50 characters or fewer.')
            seen.add(name.lower())
            names.append(name)
        if len(names) > 10:
            raise forms.ValidationError('Add up to 10 new skills at a time.')
        return names

    class Meta:
        model = WorkerProfile
        fields = ['headline', 'bio', 'years_experience', 'availability']
        widgets = {'bio': forms.Textarea(attrs={'rows': 5})}
        labels = {'years_experience': 'Years of experience'}


class EmployerProfileForm(forms.ModelForm):
    class Meta:
        model = EmployerProfile
        fields = ['employer_type', 'company_name', 'description', 'address']
        widgets = {'description': forms.Textarea(attrs={'rows': 4})}
        labels = {'employer_type': 'I am a'}


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        choices=[(5, '5 - Excellent'), (4, '4 - Good'), (3, '3 - Okay'),
                 (2, '2 - Poor'), (1, '1 - Bad')],
        coerce=int, widget=forms.RadioSelect, label='Your rating',
    )

    class Meta:
        model = Review
        fields = ['rating', 'comment']
        widgets = {'comment': forms.Textarea(attrs={'rows': 4, 'maxlength': 500})}
        labels = {'comment': 'Comment (optional)'}
