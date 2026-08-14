"""
Django admin configuration for EventNow.

The admin panel is mainly used for staff-level management:
- manage subscription plans and archive them
- manage events, sessions, applications and user profiles
- manage KnowledgeArticle records used by the assistant

Search, filters and pagination are included so the marker can easily check data.
"""

from django.contrib import admin
from .models import (
    Event,
    Session,
    Application,
    EventMember,
    UserProfile,
    SubscriptionPlan,
    KnowledgeArticle,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    # Admin setup for SaaS subscription plans.

    list_display = (
        'name',
        'price',
        'max_events',
        'max_sessions_per_event',
        'status',
        'created_at',
    )
    search_fields = ('name', 'description')
    list_filter = ('status',)
    list_per_page = 10
    actions = ['archive_selected_plans']

    def archive_selected_plans(self, request, queryset):
        """Archive selected plans instead of deleting them."""
        queryset.update(status='archived')

    archive_selected_plans.short_description = 'Archive selected subscription plans'


@admin.register(KnowledgeArticle)
class KnowledgeArticleAdmin(admin.ModelAdmin):
    # Admin setup for assistant knowledge base articles.

    list_display = ('title', 'category', 'is_active', 'created_at')
    search_fields = ('title', 'content', 'keywords')
    list_filter = ('category', 'is_active')
    list_per_page = 10


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    # Admin setup for checking and managing event records.

    list_display = (
        'title',
        'category',
        'location',
        'status',
        'start_date',
        'end_date',
        'created_by',
    )
    search_fields = ('title', 'category', 'location', 'created_by__username')
    list_filter = ('status', 'category', 'start_date')
    list_per_page = 10


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    # Admin setup for event sessions.

    list_display = (
        'title',
        'event',
        'session_time',
        'session_location',
        'capacity',
        'status',
    )
    search_fields = ('title', 'event__title', 'session_location')
    list_filter = ('status', 'session_time')
    list_per_page = 10


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    # Admin setup for participant registration records.

    list_display = (
        'user',
        'session',
        'status',
        'applied_at',
    )
    search_fields = ('user__username', 'session__title', 'session__event__title')
    list_filter = ('status', 'applied_at')
    list_per_page = 10


@admin.register(EventMember)
class EventMemberAdmin(admin.ModelAdmin):
    # Admin setup for future event collaboration records.

    list_display = (
        'event',
        'user',
        'role',
    )
    search_fields = ('event__title', 'user__username')
    list_filter = ('role',)
    list_per_page = 10


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    # Admin setup for role and subscription information.

    list_display = (
        'user',
        'global_role',
        'subscription_plan',
    )
    search_fields = ('user__username', 'user__email')
    list_filter = ('global_role', 'subscription_plan')
    list_per_page = 10