"""
EventNow forms.

Forms are used to clean and validate user input before the view saves anything.
Some fields are intentionally not exposed in forms, because they should be set
by backend logic instead of trusting user input from the browser.
"""

from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, PasswordChangeForm

from .models import Application, Session, Event


class ApplicationForm(forms.ModelForm):
    # Participant form for explaining why they want to join a session.

    class Meta:
        model = Application
        fields = ['motivation']
        widgets = {
            'motivation': forms.Textarea(attrs={'rows': 4}),
        }


class RegisterForm(UserCreationForm):
    # Registration form with an extra role field for participant/organiser.

    ROLE_CHOICES = [
        ('participant', 'Participant'),
        ('organiser', 'Organiser'),
    ]

    email = forms.EmailField(required=True)
    global_role = forms.ChoiceField(choices=ROLE_CHOICES)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2', 'global_role']


class EventCreateForm(forms.ModelForm):
    # Form for creating an event. The owner and initial status are set in the view.

    class Meta:
        model = Event
        fields = [
            'title',
            'category',
            'start_date',
            'end_date',
            'location',
            'description',
            'image',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 5}),
        }


class SessionCreateForm(forms.ModelForm):
    # Form for creating a session under an existing event.

    class Meta:
        model = Session
        fields = ['title', 'session_time', 'session_location', 'capacity', 'status']
        widgets = {
            'session_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class EventUpdateForm(forms.ModelForm):
    # Form for updating event details and lifecycle status.

    class Meta:
        model = Event
        fields = [
            'description',
            'start_date',
            'end_date',
            'location',
            'status',
            'image',
        ]
        widgets = {
            'description': forms.Textarea(attrs={'rows': 5}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }


class SessionUpdateForm(forms.ModelForm):
    # Form for updating a session. Status changes are handled carefully in the view.

    class Meta:
        model = Session
        fields = ['title', 'session_time', 'session_location', 'capacity', 'status']
        widgets = {
            'session_time': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }


class ProfileUpdateForm(forms.ModelForm):
    # Basic profile form with duplicate username/email checks.

    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email']

    def clean_email(self):
        email = self.cleaned_data['email']
        qs = User.objects.filter(email=email).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This email is already being used by another account.')
        return email

    def clean_username(self):
        username = self.cleaned_data['username']
        qs = User.objects.filter(username=username).exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('This username is already taken.')
        return username


class CustomPasswordChangeForm(PasswordChangeForm):
    # Password form with consistent CSS class names for the template.

    old_password = forms.CharField(
        label='Current Password',
        widget=forms.PasswordInput(attrs={'class': 'form-input'})
    )
    new_password1 = forms.CharField(
        label='New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-input'})
    )
    new_password2 = forms.CharField(
        label='Confirm New Password',
        widget=forms.PasswordInput(attrs={'class': 'form-input'})
    )