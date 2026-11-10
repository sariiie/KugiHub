from django import forms

from core.models import Job, Skill


class JobForm(forms.ModelForm):
    skills = forms.ModelMultipleChoiceField(
        queryset=Skill.objects.all(), required=False,
        widget=forms.CheckboxSelectMultiple, label='Skills needed',
    )

    class Meta:
        model = Job
        fields = ['title', 'description', 'location', 'fee_amount', 'fee_type', 'start_date', 'skills']
        labels = {
            'title': 'Service title',
            'description': 'What needs to be done?',
            'location': 'Service location',
            'fee_amount': 'Fee (PHP)',
            'fee_type': 'Fee type',
            'start_date': 'Preferred start date',
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'e.g. Aircon cleaning and repair'}),
            'description': forms.Textarea(attrs={'rows': 4, 'placeholder': 'Describe the work, materials, schedule...'}),
            'location': forms.TextInput(attrs={'placeholder': 'e.g. Lahug, Cebu City'}),
            'fee_amount': forms.NumberInput(attrs={'placeholder': '0.00', 'step': '0.01', 'min': '0'}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
        }