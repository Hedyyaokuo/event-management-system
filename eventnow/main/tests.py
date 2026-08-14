from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class PublicPageTests(TestCase):
    def test_event_list_requires_login(self):
        response = self.client.get(reverse("event_list"))

        self.assertRedirects(response, f'{reverse("login")}?next={reverse("event_list")}')

    def test_authenticated_user_can_open_event_list(self):
        user = User.objects.create_user(username="participant", password="test-password")
        self.client.force_login(user)

        response = self.client.get(reverse("event_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "EventNow")

    def test_login_page_loads(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)


class AssistantApiTests(TestCase):
    def test_empty_question_returns_guidance(self):
        user = User.objects.create_user(username="assistant-user", password="test-password")
        self.client.force_login(user)

        response = self.client.post(reverse("eventnow_assistant_api"), {"question": ""})

        self.assertEqual(response.status_code, 200)
        self.assertIn("Please type a question", response.json()["answer"])
