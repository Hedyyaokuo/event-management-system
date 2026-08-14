"""
EventNow views.py

This file is basically the control centre of my EventNow project.
It connects the Django models, forms, templates, role checks, and fetch API endpoints together.

The main things handled here are:
1. Login, register and logout flow.
2. Role-based page access for admin, organiser and participant users.
3. Public event browsing and participant registration workflow.
4. Organiser event/session management, including subscription limit checks.
5. Application status management, such as approve, reject, cancel and invalid.
6. Capacity calculation for sessions and events.
7. Fetch API endpoints used by the front end to update capacity, applications, sessions and profile details without refreshing the whole page.
8. EventNow Assistant, which is my advanced feature. It is not just a random chatbot; it uses EventNow data, session capacity, application workflow rules, and curated knowledge articles to give safer and more grounded answers.

Design idea:
I tried to avoid dangerous physical deletion for important records. Events and sessions use status-based lifecycle control where needed, so old registration/application relationships are less likely to break. In other words, the system is more like a real web app: not everything should just be deleted from the database directly.
"""

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib.auth import logout, login, update_session_auth_hash
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET

from .models import Event, Session, Application, UserProfile, SubscriptionPlan, KnowledgeArticle
from django.db.models import Q
import re
from .forms import (
    ApplicationForm,
    RegisterForm,
    EventCreateForm,
    SessionCreateForm,
    EventUpdateForm,
    SessionUpdateForm,
    ProfileUpdateForm,
    CustomPasswordChangeForm,
)



# Small helper: check whether the current user should be treated as an admin.
# I use this repeatedly because admin users should go to Django Admin, not normal user pages.
def is_admin_user(user):
    return user.is_staff or user.is_superuser



# Small helper: check whether the current user is an organiser.
# The role is stored in UserProfile, so the view logic does not need to repeat this query everywhere.
def is_organiser_user(user):
    profile = UserProfile.objects.filter(user=user).first()
    return profile and profile.global_role == 'organiser'



# Work out the organiser's current subscription usage.
# This is used before event/session creation, so organisers cannot create more than their plan allows.
def get_organiser_event_usage(user):
    current_event_count = Event.objects.filter(
        created_by=user
    ).exclude(
        status='removed'
    ).count()

    profile = UserProfile.objects.filter(user=user).select_related('subscription_plan').first()
    plan = profile.subscription_plan if profile else None

    remaining_events = None
    if plan:
        remaining_events = max(plan.max_events - current_event_count, 0)

    return profile, plan, current_event_count, remaining_events



# Calculate total capacity, accepted applications, and remaining places for one event.
# This keeps the capacity logic consistent across normal pages and fetch API responses.
def get_event_capacity_summary(event):
    sessions = Session.objects.filter(event=event).exclude(status='cancelled')

    total_capacity = sum(session.capacity for session in sessions)

    accepted_count = Application.objects.filter(
        session__event=event,
        status='accepted'
    ).exclude(
        session__status='cancelled'
    ).count()

    remaining = max(total_capacity - accepted_count, 0)

    return total_capacity, accepted_count, remaining


# Custom login view.
# After login, admin users go to Django Admin, while normal users enter the EventNow site.
class UserLoginView(LoginView):
    template_name = 'main/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        if is_admin_user(self.request.user):
            return '/eventnow/admin/'
        return '/eventnow/'



# Register a new user and create their UserProfile at the same time.
# The profile role decides whether the user behaves as a participant or organiser later.
def register_view(request):
    if request.user.is_authenticated:
        if is_admin_user(request.user):
            return redirect('/eventnow/admin/')
        return redirect('event_list')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.email = form.cleaned_data['email']
            user.save()

            UserProfile.objects.create(
                user=user,
                global_role=form.cleaned_data['global_role']
            )

            login(request, user)
            return redirect('event_list')
    else:
        form = RegisterForm()

    return render(request, 'main/register.html', {'form': form})


@login_required

# Main event list page.
# Users can browse events and filter by category, location, and status.
# Organisers also get extra context so the template can show which events they own.
def event_list(request):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    category_options = [
        'Technology',
        'Education',
        'Health',
        'Arts',
        'Sports',
        'Hobby',
    ]

    events = Event.objects.all()

    category = request.GET.get('category')
    location = request.GET.get('location')
    status = request.GET.get('status')

    if category:
        events = events.filter(category__iexact=category)

    if location:
        events = events.filter(location__icontains=location)

    if status:
        events = events.filter(status=status)

    is_organiser = is_organiser_user(request.user)
    owned_event_ids = []

    if is_organiser:
        owned_event_ids = list(
            Event.objects.filter(created_by=request.user).values_list('id', flat=True)
        )

    return render(request, 'main/event_list.html', {
        'events': events,
        'is_organiser': is_organiser,
        'owned_event_ids': owned_event_ids,
        'category_options': category_options,
        'selected_category': category,
        'selected_location': location,
        'selected_status': status,
    })


@login_required

# Participant-facing event detail page.
# It shows event information, available sessions, accepted application count, and remaining capacity.
def event_detail(request, event_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    event = get_object_or_404(Event, id=event_id)

    sessions = Session.objects.filter(
        event=event
    ).exclude(
        status='cancelled'
    ).order_by('session_time')

    for session in sessions:
        session.accepted_count = session.application_set.filter(status='accepted').count()
        session.remaining_count = max(session.capacity - session.accepted_count, 0)

    total_capacity = sum(session.capacity for session in sessions)

    accepted_count = Application.objects.filter(
        session__event=event,
        status='accepted'
    ).exclude(
        session__status='cancelled'
    ).count()

    remaining = max(total_capacity - accepted_count, 0)

    return render(request, 'main/event_detail.html', {
        'event': event,
        'sessions': sessions,
        'accepted_count': accepted_count,
        'remaining': remaining,
        'total_capacity': total_capacity,
    })


@login_required
@require_POST

# EventNow Assistant API.
# This is my advanced feature: a recommendation/helper assistant grounded in EventNow data.
# It reads the user's question, detects intent, checks events/sessions/applications/knowledge articles,
# and returns a safer answer instead of pretending to know unsupported information.
def eventnow_assistant_api(request):
    question = request.POST.get("question", "").strip()
    question_lower = question.lower()

    if not question:
        return JsonResponse({
            "answer": (
                "Please type a question about EventNow. You can ask about events, sessions, "
                "capacity, applications, organiser actions, subscriptions, or recommendations."
            )
        })

    try:
        articles = KnowledgeArticle.objects.filter(is_active=True)


        # Tiny keyword matcher used by the assistant intent rules.
        def contains_any(text, keywords):
            return any(keyword in text for keyword in keywords)


        # Normalise database text before keyword matching.
        def normalise_text(text):
            if text is None:
                return ""
            return str(text).lower()


        # Calculate one session's remaining seats from accepted applications.
        def calculate_remaining_for_session(session):
            accepted_count = Application.objects.filter(
                session=session,
                status="accepted"
            ).count()
            remaining_count = max(session.capacity - accepted_count, 0)
            return remaining_count, accepted_count


        # Detect soft user needs, such as exercise, low effort, stress relief, socialising, or learning.
        # This is what turns the assistant from a basic FAQ bot into a recommendation helper.
        def detect_user_needs(user_question):
            detected_needs = []
            matched_keywords = []

            need_groups = {
                "exercise or sports": [
                    "exercise", "sport", "sports", "fitness", "workout", "active",
                    "move", "movement", "running", "gym", "dance", "kpop", "jazz",
                    "lacking exercise", "not exercising", "healthy", "health"
                ],
                "easy or low effort": [
                    "easy", "easier", "simple", "beginner", "beginner-friendly",
                    "not too much effort", "doesn't require too much effort",
                    "without too much effort", "low effort", "light", "casual",
                    "relaxed", "relaxing", "no experience", "no experience required",
                    "less effort", "not difficult", "not hard", "too hard",
                    "too much effort", "don't want to work too hard"
                ],
                "wellbeing or relaxation": [
                    "stress", "stressed", "anxiety", "anxious", "relax", "relaxation",
                    "mental", "wellbeing", "wellness", "pressure", "tired", "burnout",
                    "calm", "mindfulness", "feel bad", "feel down", "overwhelmed"
                ],
                "social or community": [
                    "social", "meet people", "friends", "friend", "community",
                    "networking", "connect", "lonely", "group", "together",
                    "make friends", "new people"
                ],
                "learning or skill": [
                    "learn", "learning", "study", "skill", "workshop", "lecture",
                    "class", "training", "improve", "practice", "knowledge"
                ],
                "technology or career": [
                    "technology", "tech", "coding", "programming", "python",
                    "career", "industry", "software", "data", "ai", "computer"
                ],
                "arts or creative activities": [
                    "music", "art", "creative", "dance", "jazz", "kpop",
                    "drawing", "design", "performance", "singing"
                ],
                "business or networking": [
                    "business", "startup", "entrepreneur", "network", "networking",
                    "career", "professional", "industry", "conference"
                ],
            }

            for need_name, keywords in need_groups.items():
                for keyword in keywords:
                    if keyword in user_question:
                        detected_needs.append(need_name)
                        matched_keywords.append(keyword)
                        break

            clean_needs = []
            for need in detected_needs:
                if need not in clean_needs:
                    clean_needs.append(need)

            return clean_needs, matched_keywords


        # Map detected user needs to event keywords, so recommendation scoring can compare user needs with event content.
        def get_keywords_for_need(need):
            keyword_map = {
                "exercise or sports": [
                    "sport", "sports", "fitness", "exercise", "active", "movement",
                    "dance", "kpop", "jazz", "health", "wellbeing"
                ],
                "easy or low effort": [
                    "easy", "beginner", "beginner-friendly", "casual", "relaxed",
                    "relaxing", "no experience", "no experience required",
                    "introduction", "introductory", "basic", "foundation", "simple"
                ],
                "wellbeing or relaxation": [
                    "health", "wellbeing", "wellness", "relax", "relaxation",
                    "anxiety", "stress", "mindfulness", "mental", "calm"
                ],
                "social or community": [
                    "social", "community", "networking", "friends", "group",
                    "meet", "club", "collaboration", "people"
                ],
                "learning or skill": [
                    "learn", "learning", "workshop", "class", "training",
                    "lecture", "skill", "practice", "education"
                ],
                "technology or career": [
                    "technology", "tech", "coding", "programming", "python",
                    "software", "data", "ai", "career", "computer"
                ],
                "arts or creative activities": [
                    "music", "art", "creative", "dance", "jazz", "kpop",
                    "design", "performance"
                ],
                "business or networking": [
                    "business", "startup", "entrepreneur", "networking",
                    "career", "professional", "industry"
                ],
            }
            return keyword_map.get(need, [])


        # Main recommendation algorithm.
        # It ranks active events using matched needs, open sessions, remaining capacity, and application interest.
        def build_event_recommendations(user_question):
            detected_needs, matched_user_keywords = detect_user_needs(user_question)

            active_events = Event.objects.filter(status="active")
            ranked_events = []

            for event in active_events:
                open_sessions = Session.objects.filter(
                    event=event,
                    status="open"
                ).exclude(
                    status="cancelled"
                ).order_by("session_time")

                open_session_count = open_sessions.count()

                if open_session_count == 0:
                    continue

                total_remaining = 0
                available_session_titles = []

                for session in open_sessions:
                    remaining_count, accepted_count = calculate_remaining_for_session(session)
                    total_remaining += remaining_count

                    if remaining_count > 0:
                        available_session_titles.append(session.title)

                if total_remaining <= 0:
                    continue

                total_applications = Application.objects.filter(
                    session__event=event
                ).count()

                event_text = normalise_text(
                    f"{event.title} {event.category} {event.description} {event.location}"
                )

                keyword_score = 0
                matched_event_keywords = []

                for need in detected_needs:
                    for keyword in get_keywords_for_need(need):
                        if keyword in event_text:
                            keyword_score += 8
                            if keyword not in matched_event_keywords:
                                matched_event_keywords.append(keyword)

                question_words = re.findall(r"[a-zA-Z]+", user_question)

                for word in question_words:
                    if len(word) >= 5 and word in event_text:
                        keyword_score += 3
                        if word not in matched_event_keywords:
                            matched_event_keywords.append(word)

                capacity_score = min(total_remaining, 20)
                session_score = open_session_count * 4
                popularity_score = min(total_applications, 15)
                base_score = 10

                final_score = (
                    base_score
                    + keyword_score
                    + capacity_score
                    + session_score
                    + popularity_score
                )

                ranked_events.append({
                    "event": event,
                    "score": final_score,
                    "keyword_score": keyword_score,
                    "matched_event_keywords": matched_event_keywords,
                    "detected_needs": detected_needs,
                    "matched_user_keywords": matched_user_keywords,
                    "total_remaining": total_remaining,
                    "total_applications": total_applications,
                    "open_session_count": open_session_count,
                    "available_session_titles": available_session_titles,
                })

            ranked_events.sort(key=lambda item: item["score"], reverse=True)
            return ranked_events


        # Try curated KnowledgeArticle first. If nothing matches, return a safe fallback answer.
        def answer_with_article_or_fallback(article_query, fallback_answer):
            article = article_query.first()
            if article:
                return JsonResponse({
                    "answer": (
                        f"{article.title}\n\n"
                        f"{article.content}\n\n"
                        "This answer is based on EventNow's curated knowledge base."
                    )
                })

            return JsonResponse({
                "answer": fallback_answer
            })

        # 1. General help
        if contains_any(question_lower, [
            "help", "what can you do", "guide", "how does this work"
        ]):
            return JsonResponse({
                "answer": (
                    "I can help both participants and organisers with EventNow.\n\n"
                    "For participants, I can help with:\n"
                    "- Finding suitable events\n"
                    "- Checking available sessions and remaining capacity\n"
                    "- Explaining how to apply for a session\n"
                    "- Explaining application statuses such as pending, accepted, rejected, cancelled, or invalid\n\n"
                    "For organisers, I can help with:\n"
                    "- Creating events and sessions\n"
                    "- Understanding subscription limits\n"
                    "- Approving or rejecting applications\n"
                    "- Understanding session deletion and invalid applications\n\n"
                    "I can also recommend events based on needs such as exercise, relaxation, social activities, easy activities, learning, technology, or creative interests."
                )
            })

        # 2. Specific organiser workflow help
        # Important: this must come before the generic session-list logic.
        if contains_any(question_lower, [
            "what can organisers do", "what can organizers do", "organiser", "organizer",
            "create event", "make event", "new event", "add event",
            "create a session", "create session", "add session", "new session",
            "manage event", "approve", "reject", "delete session",
            "delete a session", "remove session", "update session", "edit session"
        ]):
            if contains_any(question_lower, ["approve", "reject"]):
                return JsonResponse({
                    "answer": (
                        "Organisers can approve or reject participant applications from the Registration Records table on the organiser event detail page.\n\n"
                        "- Approve changes the application status to accepted.\n"
                        "- Reject changes the application status to rejected.\n"
                        "- When an application is accepted, the accepted count increases and the remaining capacity decreases.\n"
                        "- If the session is already full, the system should not approve more applications."
                    )
                })

            if contains_any(question_lower, ["delete session", "delete a session", "remove session"]):
                return JsonResponse({
                    "answer": (
                        "When an organiser deletes a session in EventNow, the system does not physically remove the database record immediately.\n\n"
                        "Instead:\n"
                        "- The session status becomes cancelled.\n"
                        "- Pending or accepted applications for that session become invalid.\n"
                        "- The session disappears from the participant event detail page.\n"
                        "- The organiser page removes the session row using the fetch API.\n"
                        "- This keeps historical data safer while avoiding broken application records."
                    )
                })

            if contains_any(question_lower, ["create a session", "create session", "add session", "new session"]):
                return JsonResponse({
                    "answer": (
                        "To create a session, the organiser opens the organiser event detail page and uses the Add New Session form.\n\n"
                        "The system checks:\n"
                        "- The user must be the event owner.\n"
                        "- The organiser must have an active subscription plan.\n"
                        "- The event must not exceed the maximum sessions allowed by the plan.\n\n"
                        "After the session is created, it appears in the Session Management table and can be updated or deleted."
                    )
                })

            if contains_any(question_lower, ["update session", "edit session"]):
                return JsonResponse({
                    "answer": (
                        "Organisers can update a session from the Session Management table by clicking the Update button.\n\n"
                        "If a session is changed to a non-open status, pending or accepted applications related to that session should become invalid, because the session is no longer available in the same way."
                    )
                })

            if contains_any(question_lower, ["create event", "make event", "new event", "add event"]):
                return JsonResponse({
                    "answer": (
                        "To create an event, an organiser needs to select an active subscription plan first.\n\n"
                        "After that, they can use the Create New Event button from the organiser profile page. "
                        "The system checks the organiser's event quota before allowing a new event to be created."
                    )
                })

            return JsonResponse({
                "answer": (
                    "Organisers can create and manage events, add sessions, update sessions, delete sessions, and review participant applications.\n\n"
                    "Subscription plans control how many events and sessions an organiser can create. "
                    "Organisers also manage registration records by approving or rejecting participant applications."
                )
            })

        # 3. Application / registration guidance
        if (
            contains_any(question_lower, ["apply", "register", "registration", "application"])
            and not contains_any(question_lower, [
                "status", "pending", "accepted", "rejected", "cancelled", "invalid"
            ])
        ):
            return answer_with_article_or_fallback(
                articles.filter(
                    Q(keywords__icontains="apply") |
                    Q(keywords__icontains="register") |
                    Q(category__icontains="registration")
                ),
                (
                    "To apply for a session, open an active event, choose an open session with remaining capacity, "
                    "and click the Register button. Your application will start as pending until the organiser reviews it."
                )
            )

        # 4. Application status explanation
        if contains_any(question_lower, [
            "pending", "accepted", "rejected", "cancelled", "invalid",
            "application status", "what does status mean"
        ]):
            return answer_with_article_or_fallback(
                articles.filter(
                    Q(title__icontains="Application status") |
                    Q(keywords__icontains="pending") |
                    Q(keywords__icontains="accepted") |
                    Q(keywords__icontains="invalid")
                ),
                (
                    "In EventNow, application statuses usually mean:\n\n"
                    "- Pending: waiting for organiser review\n"
                    "- Accepted: approved by the organiser\n"
                    "- Rejected: not approved by the organiser\n"
                    "- Cancelled: cancelled by the participant\n"
                    "- Invalid: no longer valid because the event or session became unavailable"
                )
            )

        # 5. Subscription / plan explanation
        if contains_any(question_lower, [
            "subscription", "plan", "limit", "quota", "max event", "max session"
        ]):
            return answer_with_article_or_fallback(
                articles.filter(
                    Q(category__icontains="subscription") |
                    Q(keywords__icontains="subscription") |
                    Q(keywords__icontains="plan")
                ),
                (
                    "Subscription plans control what organisers can create.\n\n"
                    "- A plan can limit the number of events an organiser can create.\n"
                    "- A plan can also limit the number of sessions under each event.\n"
                    "- Only active plans can be selected and used.\n"
                    "- Archived plans should not be used for new organiser activity."
                )
            )

        # 6. Profile and password help
        if contains_any(question_lower, [
            "profile", "username", "email", "password", "change my details"
        ]):
            return JsonResponse({
                "answer": (
                    "You can update your basic profile information from the My Profile page.\n\n"
                    "- Basic information includes username and email.\n"
                    "- Password changes require your current password and a new password.\n"
                    "- For security reasons, the current password is never displayed."
                )
            })

        # 7. Remaining capacity / available sessions
        if contains_any(question_lower, [
            "capacity", "available", "remaining", "left", "spots", "place",
            "free space", "open session", "open sessions", "available sessions",
            "which sessions are available"
        ]):
            sessions = Session.objects.filter(
                event__status="active",
                status="open"
            ).exclude(
                status="cancelled"
            ).select_related("event").order_by("event__title", "session_time")

            answer_lines = [
                "Based on current registration records, these open sessions still have remaining capacity:"
            ]

            found = False

            for session in sessions:
                remaining_count, accepted_count = calculate_remaining_for_session(session)

                if remaining_count > 0:
                    found = True
                    answer_lines.append(
                        f"- {session.event.title} / {session.title}: {remaining_count} spot(s) left"
                    )

            if not found:
                return JsonResponse({
                    "answer": "No open sessions currently have available capacity."
                })

            answer_lines.append("")
            answer_lines.append("You can open the event detail page and register for any available open session.")

            return JsonResponse({
                "answer": "\n".join(answer_lines)
            })

        # 8. Popular events
        if contains_any(question_lower, [
            "popular", "hot", "most applied", "trending", "most popular"
        ]):
            active_events = Event.objects.filter(status="active")
            event_scores = []

            for event in active_events:
                total_apps = Application.objects.filter(session__event=event).count()

                accepted = Application.objects.filter(
                    session__event=event,
                    status="accepted"
                ).count()

                open_sessions = Session.objects.filter(
                    event=event,
                    status="open"
                ).exclude(
                    status="cancelled"
                ).count()

                score = total_apps + accepted + open_sessions
                event_scores.append((event, total_apps, accepted, open_sessions, score))

            event_scores.sort(key=lambda item: item[4], reverse=True)

            if not event_scores:
                return JsonResponse({
                    "answer": "There are no active events currently."
                })

            answer_lines = [
                "Popular events based on current applications, accepted registrations, and open sessions:"
            ]

            for event, total_apps, accepted, open_sessions, score in event_scores[:5]:
                answer_lines.append(
                    f"- {event.title}: {total_apps} application(s), {accepted} accepted, {open_sessions} open session(s)"
                )

            return JsonResponse({
                "answer": "\n".join(answer_lines)
            })

        # 9. Need-based recommendation algorithm
        recommendation_intent_words = [
            "recommend", "suggest", "which event", "what event", "find me",
            "looking for", "i want", "i need", "i feel", "i think",
            "interested in", "lacking", "bored", "stress", "anxiety",
            "exercise", "sport", "sports", "fitness", "workout",
            "social", "meet people", "friends", "learn", "skill",
            "dance", "music", "health", "relax", "easy", "easier",
            "simple", "beginner", "low effort", "too much effort",
            "not hard", "not difficult", "career", "business", "technology",
            "creative", "art", "music", "lonely", "overwhelmed"
        ]

        detected_needs, matched_user_keywords = detect_user_needs(question_lower)
        should_recommend = bool(detected_needs)

        for intent_word in recommendation_intent_words:
            if intent_word in question_lower:
                should_recommend = True
                break

        if should_recommend:
            ranked_events = build_event_recommendations(question_lower)

            if not ranked_events:
                return JsonResponse({
                    "answer": (
                        "I cannot recommend a suitable event right now because there are no active events "
                        "with open sessions and remaining capacity."
                    )
                })

            best = ranked_events[0]
            event = best["event"]

            reason_lines = []

            if best["detected_needs"]:
                need_text = ", ".join(best["detected_needs"])
                reason_lines.append(
                    f"- Your message suggests interest or need related to {need_text}."
                )

            if best["matched_event_keywords"]:
                keywords = ", ".join(best["matched_event_keywords"][:5])
                reason_lines.append(
                    f"- This event matches relevant keywords such as: {keywords}."
                )

            reason_lines.extend([
                "- It is currently active.",
                f"- It has {best['open_session_count']} open session(s).",
                f"- It still has {best['total_remaining']} remaining place(s).",
                f"- It has received {best['total_applications']} application(s), which suggests participant interest."
            ])

            if best["available_session_titles"]:
                session_preview = ", ".join(best["available_session_titles"][:3])
                reason_lines.append(
                    f"- Available session(s) include: {session_preview}."
                )

            answer_lines = [
                f"Based on your message, I recommend \"{event.title}\".",
                "",
                "Reason:",
                *reason_lines,
                "",
                f"Location: {event.location}",
                f"Date: {event.start_date} to {event.end_date}",
            ]

            if len(ranked_events) > 1:
                answer_lines.append("")
                answer_lines.append("Other suitable options:")

                for item in ranked_events[1:3]:
                    other_event = item["event"]
                    answer_lines.append(
                        f"- {other_event.title}: {item['total_remaining']} remaining place(s), "
                        f"{item['open_session_count']} open session(s)"
                    )

            return JsonResponse({
                "answer": "\n".join(answer_lines)
            })

        # 10. Session list / schedule
        # Important: do not use a broad "session" match here, because questions like
        # "How do I create a session?" should be handled by organiser help above.
        if contains_any(question_lower, [
            "session list", "list sessions", "all sessions", "session schedule",
            "schedule", "timetable", "current sessions", "show sessions"
        ]):
            sessions = Session.objects.filter(
                event__status="active"
            ).exclude(
                status="cancelled"
            ).select_related("event").order_by("session_time")

            if not sessions:
                return JsonResponse({
                    "answer": "No active sessions found."
                })

            answer_lines = [
                "Current active event sessions:"
            ]

            for session in sessions[:8]:
                remaining_count, accepted_count = calculate_remaining_for_session(session)

                answer_lines.append(
                    f"- {session.event.title}: {session.title} at {session.session_time}, "
                    f"status: {session.status}, remaining: {remaining_count}"
                )

            return JsonResponse({
                "answer": "\n".join(answer_lines)
            })

        # 11. Responsible fallback
        return JsonResponse({
            "answer": (
                "I could not find an exact EventNow answer for that question.\n\n"
                "To avoid giving unsupported information, I can currently help with:\n"
                "- Available sessions and remaining capacity\n"
                "- Popular events\n"
                "- Event recommendations based on user needs\n"
                "- Easy, low-effort, exercise, wellbeing, social, learning, technology, or creative activity suggestions\n"
                "- How to apply for a session\n"
                "- Application status meanings\n"
                "- Organiser actions such as creating sessions, deleting sessions, and approving applications\n"
                "- Subscription plan rules"
            )
        })

    except Exception as error:
        return JsonResponse({
            "answer": f"Assistant backend error: {str(error)}"
        })

@login_required
@require_GET

# Fetch API: return updated session capacity data for one event.
# The front end can call this without refreshing the whole page.
def session_capacity_api(request, event_id):
    if is_admin_user(request.user):
        return JsonResponse({
            'success': False,
            'message': 'Admin should use the admin panel.'
        }, status=403)

    event = get_object_or_404(Event, id=event_id)

    sessions = Session.objects.filter(
        event=event
    ).exclude(
        status='cancelled'
    ).order_by('session_time')

    session_data = []

    for session in sessions:
        accepted_count = Application.objects.filter(
            session=session,
            status='accepted'
        ).count()

        remaining_count = max(session.capacity - accepted_count, 0)

        session_data.append({
            'session_id': session.id,
            'title': session.title,
            'session_time': session.session_time.strftime('%B %d, %Y, %-I:%M %p') if hasattr(session.session_time, 'strftime') else str(session.session_time),
            'session_location': session.session_location,
            'capacity': session.capacity,
            'accepted_count': accepted_count,
            'remaining_count': remaining_count,
            'status': session.status,
        })

    total_capacity, event_accepted_count, event_remaining_count = get_event_capacity_summary(event)

    return JsonResponse({
        'success': True,
        'event_id': event.id,
        'sessions': session_data,
        'total_capacity': total_capacity,
        'event_accepted_count': event_accepted_count,
        'event_remaining_count': event_remaining_count,
    })


@login_required
@require_POST

# Fetch API: organiser approves or rejects a participant application.
# It also recalculates capacity immediately, so the UI can update after the action.
def application_status_api(request, application_id):
    if is_admin_user(request.user):
        return JsonResponse({
            'success': False,
            'message': 'Admin should use the admin panel.'
        }, status=403)

    application = get_object_or_404(Application, id=application_id)
    event = application.session.event

    if not is_organiser_user(request.user) or event.created_by != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Permission denied.'
        }, status=403)

    action = request.POST.get('action')

    if action == 'approve':
        accepted_count = Application.objects.filter(
            session=application.session,
            status='accepted'
        ).count()

        if accepted_count >= application.session.capacity:
            return JsonResponse({
                'success': False,
                'message': 'This session is already full.'
            }, status=400)

        application.status = 'accepted'
        application.save()

    elif action == 'reject':
        application.status = 'rejected'
        application.save()

    else:
        return JsonResponse({
            'success': False,
            'message': 'Invalid action.'
        }, status=400)

    accepted_count = Application.objects.filter(
        session=application.session,
        status='accepted'
    ).count()

    remaining_count = max(application.session.capacity - accepted_count, 0)

    total_capacity, event_accepted_count, event_remaining_count = get_event_capacity_summary(event)

    return JsonResponse({
        'success': True,
        'application_id': application.id,
        'new_status': application.status,
        'session_id': application.session.id,
        'accepted_count': accepted_count,
        'remaining_count': remaining_count,
        'total_capacity': total_capacity,
        'event_accepted_count': event_accepted_count,
        'event_remaining_count': event_remaining_count,
        'message': f'Application {application.status} successfully.'
    })


@login_required
@require_POST

# Fetch API: participant cancels their own application.
# It only allows the logged-in owner of the application to cancel it.
def cancel_application_api(request, application_id):
    if is_admin_user(request.user):
        return JsonResponse({
            'success': False,
            'message': 'Admin should use the admin panel.'
        }, status=403)

    application = get_object_or_404(
        Application,
        id=application_id,
        user=request.user
    )

    if application.status == 'cancelled':
        return JsonResponse({
            'success': True,
            'application_id': application.id,
            'new_status': application.status,
            'message': 'Application is already cancelled.'
        })

    application.status = 'cancelled'
    application.save()

    return JsonResponse({
        'success': True,
        'application_id': application.id,
        'new_status': application.status,
        'message': 'Application cancelled successfully.'
    })


@login_required
@require_POST

# Fetch API: update the user's basic profile information.
# This keeps profile editing lightweight and avoids a full page refresh.
def update_basic_info_api(request):
    if is_admin_user(request.user):
        return JsonResponse({
            'success': False,
            'message': 'Admin should use the admin panel.'
        }, status=403)

    username = request.POST.get('username', '').strip()
    email = request.POST.get('email', '').strip()

    if not username or not email:
        return JsonResponse({
            'success': False,
            'message': 'Username and email cannot be empty.'
        }, status=400)

    request.user.username = username
    request.user.email = email
    request.user.save()

    return JsonResponse({
        'success': True,
        'message': 'Basic information updated successfully.',
        'username': request.user.username,
        'email': request.user.email,
    })


@login_required
@require_POST

# Fetch API: change password from the profile page.
# update_session_auth_hash keeps the user logged in after changing the password.
def change_password_api(request):
    if is_admin_user(request.user):
        return JsonResponse({
            'success': False,
            'message': 'Admin should use the admin panel.'
        }, status=403)

    password_form = CustomPasswordChangeForm(request.user, request.POST)

    if password_form.is_valid():
        user = password_form.save()
        update_session_auth_hash(request, user)

        return JsonResponse({
            'success': True,
            'message': 'Password changed successfully.'
        })

    return JsonResponse({
        'success': False,
        'message': 'Password change failed. Please check your current password and new password.'
    }, status=400)


@login_required
@require_POST

# Fetch API: organiser creates a new session from the organiser event detail page.
# The view checks role, event ownership, active subscription plan, and session limit before saving.
def create_session_api(request, event_id):
    if is_admin_user(request.user):
        return JsonResponse({
            'success': False,
            'message': 'Admin should use the admin panel.'
        }, status=403)

    event = get_object_or_404(Event, id=event_id)

    if not is_organiser_user(request.user) or event.created_by != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Permission denied.'
        }, status=403)

    profile, plan, current_event_count, remaining_events = get_organiser_event_usage(request.user)

    if plan is None:
        return JsonResponse({
            'success': False,
            'message': 'Please choose a subscription plan before creating sessions.'
        }, status=400)

    if plan.status != 'active':
        return JsonResponse({
            'success': False,
            'message': 'Your subscription plan is not active.'
        }, status=400)

    current_session_count = Session.objects.filter(
        event=event
    ).exclude(
        status='cancelled'
    ).count()

    if current_session_count >= plan.max_sessions_per_event:
        return JsonResponse({
            'success': False,
            'message': f'Your current plan only allows {plan.max_sessions_per_event} session(s) per event.'
        }, status=400)

    form_data = request.POST.copy()
    form_data['status'] = 'open'

    form = SessionCreateForm(form_data)

    if not form.is_valid():
        return JsonResponse({
            'success': False,
            'message': 'Session creation failed. Please check the form fields.',
            'errors': form.errors
        }, status=400)

    session = form.save(commit=False)
    session.event = event
    session.status = 'open'
    session.save()

    accepted_count = Application.objects.filter(
        session=session,
        status='accepted'
    ).count()

    remaining_count = max(session.capacity - accepted_count, 0)

    total_capacity, event_accepted_count, event_remaining_count = get_event_capacity_summary(event)

    return JsonResponse({
        'success': True,
        'message': 'Session created successfully.',
        'session': {
            'session_id': session.id,
            'title': session.title,
            'session_time': session.session_time.strftime('%B %d, %Y, %I:%M %p'),
            'status': session.status,
            'capacity': session.capacity,
            'accepted_count': accepted_count,
            'remaining_count': remaining_count,
        },
        'total_capacity': total_capacity,
        'event_accepted_count': event_accepted_count,
        'event_remaining_count': event_remaining_count,
    })


@login_required
@require_POST

# Fetch API: delete a session in a safer soft-delete way.
# The session becomes cancelled, and related pending/accepted applications become invalid.
# This is safer than hard deleting because registration history will not randomly break.
def delete_session_api(request, session_id):
    if is_admin_user(request.user):
        return JsonResponse({
            'success': False,
            'message': 'Admin should use the admin panel.'
        }, status=403)

    session = get_object_or_404(Session, id=session_id)
    event = session.event

    if not is_organiser_user(request.user) or event.created_by != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Permission denied.'
        }, status=403)

    session.status = 'cancelled'
    session.save()

    affected_applications = Application.objects.filter(
        session=session,
        status__in=['pending', 'accepted']
    )

    invalid_application_ids = list(
        affected_applications.values_list('id', flat=True)
    )

    affected_applications.update(status='invalid')

    total_capacity, event_accepted_count, event_remaining_count = get_event_capacity_summary(event)

    return JsonResponse({
        'success': True,
        'message': 'Session deleted successfully. It will no longer be visible to participants.',
        'session_id': session.id,
        'invalid_application_ids': invalid_application_ids,
        'total_capacity': total_capacity,
        'event_accepted_count': event_accepted_count,
        'event_remaining_count': event_remaining_count,
    })


@login_required
@require_POST

# Fetch API: organiser deletes a registration record after it is no longer pending.
# Pending applications should be handled by approve/reject first, so the workflow stays clear.
def delete_application_record_api(request, application_id):
    if is_admin_user(request.user):
        return JsonResponse({
            'success': False,
            'message': 'Admin should use the admin panel.'
        }, status=403)

    application = get_object_or_404(Application, id=application_id)
    event = application.session.event

    if not is_organiser_user(request.user) or event.created_by != request.user:
        return JsonResponse({
            'success': False,
            'message': 'Permission denied.'
        }, status=403)

    if application.status == 'pending':
        return JsonResponse({
            'success': False,
            'message': 'Pending applications should be approved or rejected before deleting the record.'
        }, status=400)

    deleted_application_id = application.id
    application.delete()

    total_capacity, event_accepted_count, event_remaining_count = get_event_capacity_summary(event)

    return JsonResponse({
        'success': True,
        'message': 'Registration record deleted successfully.',
        'application_id': deleted_application_id,
        'total_capacity': total_capacity,
        'event_accepted_count': event_accepted_count,
        'event_remaining_count': event_remaining_count,
    })


@login_required

# Organiser event management page.
# The event owner can view sessions, applications, members, capacity summary, and create sessions.
# Non-owner organisers are sent to a read-only page instead of getting edit access.
def organiser_event_detail_view(request, event_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    event = get_object_or_404(Event, id=event_id)

    if not is_organiser_user(request.user):
        return redirect('event_detail', event_id=event_id)

    if event.created_by != request.user:
        return redirect('organiser_readonly_event_detail', event_id=event_id)

    sessions = Session.objects.filter(
        event=event
    ).exclude(
        status='cancelled'
    ).order_by('session_time')

    members = event.eventmember_set.all()

    applications = Application.objects.filter(
        session__event=event
    ).select_related('user', 'session')

    for session in sessions:
        session.accepted_count = session.application_set.filter(status='accepted').count()
        session.remaining_count = max(session.capacity - session.accepted_count, 0)

    total_capacity, accepted_count, remaining = get_event_capacity_summary(event)

    profile, plan, current_event_count, remaining_events = get_organiser_event_usage(request.user)

    current_session_count = sessions.count()
    remaining_sessions = None

    if plan:
        remaining_sessions = max(plan.max_sessions_per_event - current_session_count, 0)

    if request.method == 'POST':
        if plan is None:
            messages.error(request, 'Please choose a subscription plan before creating sessions.')
            return redirect('organiser_profile')

        if plan.status != 'active':
            messages.error(request, 'Your subscription plan is not active.')
            return redirect('organiser_profile')

        if current_session_count >= plan.max_sessions_per_event:
            messages.error(
                request,
                f'Your current plan only allows {plan.max_sessions_per_event} session(s) per event.'
            )
            return redirect('organiser_event_detail', event_id=event.id)

        form_data = request.POST.copy()
        form_data['status'] = 'open'

        form = SessionCreateForm(form_data)

        if form.is_valid():
            session = form.save(commit=False)
            session.event = event
            session.status = 'open'
            session.save()

            messages.success(request, 'Session created successfully.')
            return redirect('organiser_event_detail', event_id=event.id)
    else:
        form = SessionCreateForm()

    return render(request, 'main/organiser_event_detail.html', {
        'event': event,
        'sessions': sessions,
        'members': members,
        'applications': applications,
        'form': form,
        'accepted_count': accepted_count,
        'remaining': remaining,
        'total_capacity': total_capacity,
        'plan': plan,
        'current_session_count': current_session_count,
        'remaining_sessions': remaining_sessions,
    })


@login_required

# Read-only organiser view.
# This supports the collaborator-style idea at a safe level: users can see event information without being allowed to edit it.
def organiser_readonly_event_detail_view(request, event_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    if not is_organiser_user(request.user):
        return redirect('event_detail', event_id=event_id)

    event = get_object_or_404(Event, id=event_id)

    sessions = Session.objects.filter(
        event=event
    ).exclude(
        status='cancelled'
    ).order_by('session_time')

    for session in sessions:
        session.accepted_count = session.application_set.filter(status='accepted').count()
        session.remaining_count = max(session.capacity - session.accepted_count, 0)

    total_capacity, accepted_count, remaining = get_event_capacity_summary(event)

    return render(request, 'main/organiser_readonly_event_detail.html', {
        'event': event,
        'sessions': sessions,
        'accepted_count': accepted_count,
        'remaining': remaining,
        'total_capacity': total_capacity,
    })


@login_required

# Update an event.
# Only the event owner can edit it. If the event becomes non-active, related pending/accepted applications become invalid.
def update_event_view(request, event_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    event = get_object_or_404(Event, id=event_id)

    if not is_organiser_user(request.user):
        return redirect('event_detail', event_id=event.id)

    if event.created_by != request.user:
        return redirect('organiser_readonly_event_detail', event_id=event.id)

    if request.method == 'POST':
        form = EventUpdateForm(request.POST, request.FILES, instance=event)

        if form.is_valid():
            event = form.save()

            if event.status != 'active':
                Application.objects.filter(
                    session__event=event,
                    status__in=['pending', 'accepted']
                ).update(status='invalid')

            messages.success(request, 'Event updated successfully.')
            return redirect('organiser_event_detail', event_id=event.id)
    else:
        form = EventUpdateForm(instance=event)

    return render(request, 'main/update_event.html', {
        'event': event,
        'form': form,
    })


@login_required

# Participant application flow.
# It checks event status, session status, capacity, and duplicate applications before allowing submission.
def apply_session(request, session_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    if is_organiser_user(request.user):
        return redirect('event_list')

    session = get_object_or_404(Session, id=session_id)
    event = session.event

    accepted_count = Application.objects.filter(
        session=session,
        status='accepted'
    ).count()
    remaining_count = max(session.capacity - accepted_count, 0)

    if event.status != 'active':
        return render(request, 'main/application_success.html', {
            'session': session,
            'message': 'This event is not available for registration.'
        })

    if session.status != 'open':
        return render(request, 'main/application_success.html', {
            'session': session,
            'message': 'This session is not open for registration.'
        })

    if remaining_count <= 0:
        return render(request, 'main/application_success.html', {
            'session': session,
            'message': 'This session is already full.'
        })

    existing_application = Application.objects.filter(
        user=request.user,
        session=session
    ).first()

    if existing_application and existing_application.status != 'cancelled':
        return render(request, 'main/application_success.html', {
            'session': session,
            'message': 'You have already applied for this session.'
        })

    if request.method == 'POST':
        form = ApplicationForm(request.POST)
        if form.is_valid():
            if existing_application and existing_application.status == 'cancelled':
                existing_application.motivation = form.cleaned_data['motivation']
                existing_application.status = 'pending'
                existing_application.save()
            else:
                application = form.save(commit=False)
                application.user = request.user
                application.session = session
                application.status = 'pending'
                application.save()

            return render(request, 'main/application_success.html', {
                'session': session,
                'message': 'Your application has been submitted successfully.'
            })
    else:
        form = ApplicationForm()

    return render(request, 'main/application_form.html', {
        'form': form,
        'session': session,
    })


@login_required

# Update a session.
# If the session is no longer open, pending/accepted applications become invalid because the session changed availability.
def update_session_view(request, session_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    session = get_object_or_404(Session, id=session_id)
    event = session.event

    if not is_organiser_user(request.user):
        return redirect('event_detail', event_id=event.id)

    if event.created_by != request.user:
        return redirect('organiser_readonly_event_detail', event_id=event.id)

    if request.method == 'POST':
        form = SessionUpdateForm(request.POST, instance=session)
        if form.is_valid():
            session = form.save()

            if session.status != 'open':
                Application.objects.filter(
                    session=session,
                    status__in=['pending', 'accepted']
                ).update(status='invalid')

            messages.success(request, 'Session updated successfully.')
            return redirect('organiser_event_detail', event_id=event.id)
    else:
        initial_data = {
            'session_time': session.session_time.strftime('%Y-%m-%dT%H:%M')
        }
        form = SessionUpdateForm(instance=session, initial=initial_data)

    return render(request, 'main/update_session.html', {
        'form': form,
        'session': session,
        'event': event,
    })


@login_required

# Normal form-based backup version of session deletion.
# It follows the same safer logic as the fetch API: mark cancelled and invalidate affected applications.
def delete_session_view(request, session_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    session = get_object_or_404(Session, id=session_id)
    event = session.event

    if not is_organiser_user(request.user):
        return redirect('event_detail', event_id=event.id)

    if event.created_by != request.user:
        return redirect('organiser_readonly_event_detail', event_id=event.id)

    if request.method == 'POST':
        session.status = 'cancelled'
        session.save()

        Application.objects.filter(
            session=session,
            status__in=['pending', 'accepted']
        ).update(status='invalid')

        messages.success(
            request,
            'Session deleted successfully. It will no longer be visible to participants.'
        )

        return redirect('organiser_event_detail', event_id=event.id)

    return redirect('organiser_event_detail', event_id=event.id)


@login_required

# Participant profile page.
# It shows the user's applications and supports basic profile/password updates.
def profile_view(request):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    applications = Application.objects.filter(user=request.user).select_related('session', 'session__event')
    profile = UserProfile.objects.filter(user=request.user).first()

    if request.method == 'POST':
        if 'update_profile' in request.POST:
            profile_form = ProfileUpdateForm(request.POST, instance=request.user)
            password_form = CustomPasswordChangeForm(request.user)

            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Your basic information has been updated successfully.')
                return redirect('profile')

        elif 'change_password' in request.POST:
            profile_form = ProfileUpdateForm(instance=request.user)
            password_form = CustomPasswordChangeForm(request.user, request.POST)

            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password has been changed successfully.')
                return redirect('profile')
        else:
            profile_form = ProfileUpdateForm(instance=request.user)
            password_form = CustomPasswordChangeForm(request.user)
    else:
        profile_form = ProfileUpdateForm(instance=request.user)
        password_form = CustomPasswordChangeForm(request.user)

    return render(request, 'main/profile.html', {
        'applications': applications,
        'profile': profile,
        'profile_form': profile_form,
        'password_form': password_form,
    })


@login_required

# Organiser profile/dashboard page.
# It shows subscription plan, event quota, owned events, joined/read-only events, and profile settings.
def organiser_profile_view(request):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    if not is_organiser_user(request.user):
        return redirect('profile')

    profile, plan, current_event_count, remaining_events = get_organiser_event_usage(request.user)

    active_plans = SubscriptionPlan.objects.filter(status='active').order_by('price', 'max_events')

    owned_events = Event.objects.filter(created_by=request.user)

    joined_events = Event.objects.filter(
        eventmember__user=request.user
    ).exclude(created_by=request.user).distinct()

    can_create_event = (
        plan is not None
        and plan.status == 'active'
        and current_event_count < plan.max_events
    )

    if request.method == 'POST':
        if 'choose_plan' in request.POST:
            plan_id = request.POST.get('plan_id')
            selected_plan = get_object_or_404(
                SubscriptionPlan,
                id=plan_id,
                status='active'
            )

            profile.subscription_plan = selected_plan
            profile.save()

            messages.success(request, f'You have selected the {selected_plan.name} plan.')
            return redirect('organiser_profile')

        if 'update_profile' in request.POST:
            profile_form = ProfileUpdateForm(request.POST, instance=request.user)
            password_form = CustomPasswordChangeForm(request.user)

            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Your basic information has been updated successfully.')
                return redirect('organiser_profile')

        elif 'change_password' in request.POST:
            profile_form = ProfileUpdateForm(instance=request.user)
            password_form = CustomPasswordChangeForm(request.user, request.POST)

            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password has been changed successfully.')
                return redirect('organiser_profile')
        else:
            profile_form = ProfileUpdateForm(instance=request.user)
            password_form = CustomPasswordChangeForm(request.user)
    else:
        profile_form = ProfileUpdateForm(instance=request.user)
        password_form = CustomPasswordChangeForm(request.user)

    return render(request, 'main/organiser_profile.html', {
        'profile': profile,
        'plan': plan,
        'active_plans': active_plans,
        'current_event_count': current_event_count,
        'remaining_events': remaining_events,
        'can_create_event': can_create_event,
        'owned_events': owned_events,
        'joined_events': joined_events,
        'profile_form': profile_form,
        'password_form': password_form,
    })


@login_required

# Create a new event.
# Only organisers with an active subscription plan and remaining event quota can create events.
def create_event_view(request):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    if not is_organiser_user(request.user):
        messages.error(request, 'Only organisers can create events.')
        return redirect('event_list')

    profile, plan, current_event_count, remaining_events = get_organiser_event_usage(request.user)

    if plan is None:
        messages.error(request, 'Please choose a subscription plan before creating events.')
        return redirect('organiser_profile')

    if plan.status != 'active':
        messages.error(request, 'Your subscription plan is not active.')
        return redirect('organiser_profile')

    if current_event_count >= plan.max_events:
        messages.error(
            request,
            f'Your current plan only allows {plan.max_events} event(s). '
            'Please archive an existing event or upgrade your plan.'
        )
        return redirect('organiser_profile')

    if request.method == 'POST':
        form = EventCreateForm(request.POST, request.FILES)

        if form.is_valid():
            event = form.save(commit=False)
            event.created_by = request.user
            event.status = 'active'
            event.save()

            messages.success(request, 'Event created successfully.')
            return redirect('organiser_event_detail', event_id=event.id)
    else:
        form = EventCreateForm()

    return render(request, 'main/create_event.html', {
        'form': form,
        'plan': plan,
        'current_event_count': current_event_count,
        'remaining_events': remaining_events,
    })


@login_required

# Form-based backup version of approving an application.
# The fetch API is used for the smoother UI, but this keeps the workflow available without JavaScript too.
def approve_application(request, application_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    application = get_object_or_404(Application, id=application_id)
    event = application.session.event

    if not is_organiser_user(request.user) or event.created_by != request.user:
        return redirect('event_detail', event_id=event.id)

    if request.method == 'POST':
        accepted_count = Application.objects.filter(
            session=application.session,
            status='accepted'
        ).count()

        if accepted_count < application.session.capacity:
            application.status = 'accepted'
            application.save()
        else:
            messages.error(request, 'This session is already full.')

    return redirect('organiser_event_detail', event_id=event.id)


@login_required

# Form-based backup version of rejecting an application.
# Only the owner organiser can reject applications for their event.
def reject_application(request, application_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    application = get_object_or_404(Application, id=application_id)
    event = application.session.event

    if not is_organiser_user(request.user) or event.created_by != request.user:
        return redirect('event_detail', event_id=event.id)

    if request.method == 'POST':
        application.status = 'rejected'
        application.save()

    return redirect('organiser_event_detail', event_id=event.id)


@login_required

# Form-based backup version of participant cancellation.
# The participant can only cancel their own application.
def cancel_application(request, application_id):
    if is_admin_user(request.user):
        return redirect('/eventnow/admin/')

    application = get_object_or_404(Application, id=application_id, user=request.user)

    if request.method == 'POST':
        application.status = 'cancelled'
        application.save()
        messages.success(request, 'Your application has been cancelled.')
        return redirect('profile')

    return redirect('profile')



# Log out the current user and return to the login page.
def logout_view(request):
    logout(request)
    return redirect('login')