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
        widgets = {
            'description': forms.Textarea(attrs={'rows': 5}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
        }
