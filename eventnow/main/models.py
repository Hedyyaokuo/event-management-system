"""
EventNow data models.

This file defines the main database structure for the project:
- SubscriptionPlan controls organiser limits.
- UserProfile stores the user's global role.
- Event and Session store the event website content and schedule.
- Application stores participant registrations.
- KnowledgeArticle supports the EventNow Assistant.
- EventMember keeps space for future collaborator support.

The project uses status fields instead of always deleting records directly.
This keeps registration history safer and makes the workflow easier to track.
"""

from django.db import models
from django.contrib.auth.models import User


class SubscriptionPlan(models.Model):
    # SaaS-style plan used to limit how many events/sessions an organiser can create.

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('archived', 'Archived'),
    ]

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2)
    max_events = models.PositiveIntegerField(default=1)
    max_sessions_per_event = models.PositiveIntegerField(default=5)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    def archive(self):
        # Archive the plan instead of deleting it, so old organiser records stay meaningful.
        self.status = 'archived'
        self.save()

    def __str__(self):
        return f"{self.name} - {self.status}"


class KnowledgeArticle(models.Model):
    # Small curated knowledge base used by the EventNow Assistant.

    CATEGORY_CHOICES = [
        ('event', 'Event Guidance'),
        ('registration', 'Registration'),
        ('session', 'Session'),
        ('subscription', 'Subscription'),
        ('role', 'Role and Permission'),
        ('recommendation', 'Recommendation'),
        ('general', 'General'),
    ]

    title = models.CharField(max_length=200)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='general')
    content = models.TextField()
    keywords = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class UserProfile(models.Model):
    # Extra user information that Django's built-in User model does not store.

    ROLE_CHOICES = [
        ('participant', 'Participant'),
        ('organiser', 'Organiser'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    global_role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='participant')

    # Only organisers need a plan, so this field is optional.
    subscription_plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    def __str__(self):
        return f"{self.user.username} - {self.global_role}"


class Event(models.Model):
    # Main event record created by an organiser.

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('removed', 'Removed'),
        ('completed', 'Completed'),
    ]

    category = models.CharField(max_length=100)
    title = models.CharField(max_length=255)
    description = models.TextField()
    location = models.CharField(max_length=255)
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='event_images/', blank=True, null=True)

    def __str__(self):
        return self.title


class Session(models.Model):
    # A scheduled session under one event.

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    session_time = models.DateTimeField()
    session_location = models.CharField(max_length=255)
    capacity = models.IntegerField()
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')

    def __str__(self):
        return self.title


class Application(models.Model):
    # Participant registration record for a session.

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('invalid', 'Invalid'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    motivation = models.TextField()
    applied_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # One user should not submit duplicate active records for the same session.
            models.UniqueConstraint(
                fields=['user', 'session'],
                name='unique_user_session_application'
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.session.title}"


class EventMember(models.Model):
    # Future collaborator structure for event teams.

    ROLE_CHOICES = [
        ('owner', 'Owner'),
        ('co_organiser', 'Co-organiser'),
        ('collaborator', 'Collaborator'),
    ]

    event = models.ForeignKey(Event, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='collaborator')

    class Meta:
        constraints = [
            # A user should only have one membership row per event.
            models.UniqueConstraint(
                fields=['event', 'user'],
                name='unique_event_user_member'
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.event.title} ({self.role})"