from datetime import timedelta
from uuid import uuid4

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from open_marketplace.identity.tests.web_fixtures import Account, AccountSession
from open_marketplace.seller_onboarding.tests.web_fixtures import SellerApplication


class UserJourneyTests(TestCase):
    password = "Correct Horse Battery Staple 42!"

    def _account(self, *, kind=Account.Kind.ORDINARY):
        create = (
            Account.objects.create_user
            if kind == Account.Kind.ORDINARY
            else Account.objects.create_service_account
        )
        return create(
            email=f"journey-{uuid4().hex}@example.com",
            password=self.password,
            state=Account.State.ACTIVE,
            email_verified_at=timezone.now(),
        )

    def _bind(self, account):
        client = Client(enforce_csrf_checks=True)
        session = client.session
        session.save()
        now = timezone.now()
        registry = AccountSession.objects.create(
            account=account,
            django_session_key=session.session_key,
            created_at=now,
            last_activity_at=now,
            absolute_expires_at=now + timedelta(days=30),
            reauthenticated_at=now,
            device_label="Journey browser",
        )
        session["account_id"] = str(account.id)
        session["session_id"] = str(registry.id)
        session.save()
        return client

    def _create_application(self, client, account):
        response = client.get(reverse("seller-application-create"))
        self.assertEqual(response.status_code, 200)
        token = client.cookies["csrftoken"].value
        created = client.post(
            reverse("seller-application-create"),
            {"csrfmiddlewaretoken": token},
        )
        self.assertEqual(created.status_code, 303)
        return SellerApplication.objects.get(
            applicant_id=account.id,
            state=SellerApplication.State.DRAFT,
        )

    def test_anonymous_seller_start_explains_next_steps_without_mutation(self):
        response = self.client.get(reverse("seller-start"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Стать продавцом")
        self.assertContains(response, 'href="/login/?next=%2Fseller%2F"')
        self.assertContains(response, 'href="/register/"')
        self.assertContains(response, "тестовые данные")
        self.assertContains(response, "отдельный допуск")
        self.assertNotContains(response, "method=\"post\"")
        self.assertNotContains(response, "csrfmiddlewaretoken")

    def test_seller_start_is_read_only_and_shows_only_own_progress(self):
        account = self._account()
        client = self._bind(account)
        before = SellerApplication.objects.count()

        response = client.get(reverse("seller-start"))
        posted = Client().post(reverse("seller-start"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, ">безопасности аккаунта</a>")
        self.assertContains(response, reverse("security"))
        self.assertContains(response, reverse("seller-applications"))
        self.assertContains(response, reverse("seller-application-create"))
        self.assertContains(response, "тестовые данные")
        self.assertContains(response, "отдельный допуск")
        self.assertEqual(posted.status_code, 405)
        self.assertEqual(SellerApplication.objects.count(), before)

    def test_seller_start_does_not_show_another_account_application(self):
        owner = self._account()
        owner_client = self._bind(owner)
        owner_application = self._create_application(owner_client, owner)
        other = self._account()
        other_client = self._bind(other)
        other_application = self._create_application(other_client, other)

        response = owner_client.get(reverse("seller-start"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse(
                "seller-application-detail",
                kwargs={"application_id": owner_application.id},
            ),
        )
        self.assertNotContains(
            response,
            reverse(
                "seller-application-detail",
                kwargs={"application_id": other_application.id},
            ),
        )

    def test_existing_draft_has_continue_action_instead_of_starting_again(self):
        account = self._account()
        client = self._bind(account)
        application = self._create_application(client, account)

        response = client.get(reverse("seller-start"))

        self.assertContains(response, "Продолжить заявку")
        self.assertContains(response, reverse("seller-application-edit", kwargs={"application_id": application.id}))
        self.assertNotContains(response, reverse("seller-application-create"))

    def test_unavailable_seller_lookup_is_not_presented_as_no_application(self):
        from unittest.mock import patch
        from open_marketplace.common.errors import ApplicationError

        client = self._bind(self._account())
        with patch("open_marketplace.web.seller_views.seller_public.get_seller_profile_for_owner", side_effect=ApplicationError("unavailable")):
            response = client.get(reverse("seller-start"))

        self.assertContains(response, "Не удалось проверить состояние заявки")
        self.assertNotContains(response, reverse("seller-application-create"))

    def test_service_account_seller_start_explains_ordinary_account_without_seller_rights(self):
        client = self._bind(self._account(kind=Account.Kind.SERVICE))

        response = client.get(reverse("seller-start"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "обычный аккаунт")
        self.assertNotContains(response, reverse("seller-application-create"))
        self.assertNotContains(response, "method=\"post\"")

    def test_identity_and_seller_forms_have_russian_labels(self):
        for name, expected in (
            ("login", ("Электронная почта", "Пароль", "Код второго фактора")),
            ("register", ("Электронная почта", "Пароль")),
            ("seller-application-create", ("Начать заявку",)),
        ):
            with self.subTest(name=name):
                client = self.client if name != "seller-application-create" else self._bind(self._account())
                if name == "seller-application-create":
                    response = client.get(reverse(name))
                else:
                    response = client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                for text in expected:
                    self.assertContains(response, text)
                for english in ("Sign in", "Register", "Continue", "Seller application", "Save application"):
                    self.assertNotContains(response, english)

        login = self.client.get(reverse("login"))
        self.assertContains(login, "Необязательно")
        self.assertContains(login, "приложения-аутентификатора")

    def test_seller_application_form_has_russian_labels_and_test_data_explanation(self):
        account = self._account()
        client = self._bind(account)
        application = self._create_application(client, account)

        response = client.get(
            reverse(
                "seller-application-edit",
                kwargs={"application_id": application.id},
            )
        )

        self.assertEqual(response.status_code, 200)
        for text in (
            "Форма ведения деятельности",
            "Название в каталоге",
            "Официальное название",
            "Регистрационный номер",
            "Контактная почта",
            "только тестовые данные",
        ):
            self.assertContains(response, text)
