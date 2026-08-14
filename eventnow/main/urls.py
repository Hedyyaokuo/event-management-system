"""
URL routes for the EventNow app.

This file connects browser/API URLs to view functions.
The routes are grouped by workflow so the project is easier to explain in code review.
"""

from django.urls import path
from . import views

urlpatterns = [
    # Authentication
    path('login/', views.UserLoginView.as_view(), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),

    # Main participant event browsing
    path('', views.event_list, name='event_list'),
    path('event/<int:event_id>/', views.event_detail, name='event_detail'),

    # EventNow Assistant
    path('api/assistant/', views.eventnow_assistant_api, name='eventnow_assistant_api'),

    # Fetch/API routes used by page-specific JavaScript
    path('api/events/<int:event_id>/capacity/', views.session_capacity_api, name='session_capacity_api'),
    path('api/applications/<int:application_id>/status/', views.application_status_api, name='application_status_api'),
    path('api/applications/<int:application_id>/cancel/', views.cancel_application_api, name='cancel_application_api'),
    path('api/profile/basic-info/', views.update_basic_info_api, name='update_basic_info_api'),
    path('api/profile/change-password/', views.change_password_api, name='change_password_api'),
    path('api/events/<int:event_id>/sessions/create/', views.create_session_api, name='create_session_api'),
    path('api/sessions/<int:session_id>/delete/', views.delete_session_api, name='delete_session_api'),
    path('api/applications/<int:application_id>/record/delete/', views.delete_application_record_api, name='delete_application_record_api'),

    # Organiser event management pages
    path('organiser/event/create/', views.create_event_view, name='create_event'),
    path('organiser/event/<int:event_id>/', views.organiser_event_detail_view, name='organiser_event_detail'),
    path('organiser/session/<int:session_id>/update/', views.update_session_view, name='update_session'),
    path('organiser/event/<int:event_id>/readonly/', views.organiser_readonly_event_detail_view, name='organiser_readonly_event_detail'),
    path('organiser/session/<int:session_id>/delete/', views.delete_session_view, name='delete_session'),
    path('organiser/event/<int:event_id>/update/', views.update_event_view, name='update_event'),

    # Session registration and application actions
    path('session/<int:session_id>/apply/', views.apply_session, name='apply_session'),
    path('application/<int:application_id>/cancel/', views.cancel_application, name='cancel_application'),
    path('application/<int:application_id>/approve/', views.approve_application, name='approve_application'),
    path('application/<int:application_id>/reject/', views.reject_application, name='reject_application'),

    # User profile pages
    path('profile/', views.profile_view, name='profile'),
    path('organiser/profile/', views.organiser_profile_view, name='organiser_profile'),
]