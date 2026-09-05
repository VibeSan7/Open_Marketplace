from django.urls import path

from open_marketplace.web import identity_views, seller_views, staff_views

urlpatterns = [
    path("register/", identity_views.register, name="register"),
    path("login/", identity_views.login, name="login"),
    path("logout/", identity_views.logout, name="logout"),
    path(
        "identity/password-reset/",
        identity_views.password_reset_request,
        name="password-reset-request",
    ),
    path(
        "identity/reset-password/confirm/",
        identity_views.password_reset_confirm,
        name="password-reset-confirm",
    ),
    path(
        "identity/reset-password/<str:raw_token>/",
        identity_views.sensitive_entry,
        {"purpose": "password_reset", "clean_name": "password-reset-confirm"},
        name="password-reset-entry",
    ),
    path(
        "identity/verify-email/complete/",
        identity_views.verify_email_complete,
        name="verify-email-complete",
    ),
    path(
        "identity/verify-email/<str:raw_token>/",
        identity_views.sensitive_entry,
        {"purpose": "email_verification", "clean_name": "verify-email-complete"},
        name="verify-email-entry",
    ),
    path(
        "identity/password-change/",
        identity_views.password_change,
        name="password-change",
    ),
    path("security/", identity_views.security, name="security"),
    path("security/reauthenticate/", identity_views.reauthenticate, name="reauthenticate"),
    path("security/totp/setup/", identity_views.totp_setup, name="totp-setup"),
    path("security/totp/disable/", identity_views.totp_disable, name="totp-disable"),
    path(
        "security/recovery-codes/replace/",
        identity_views.recovery_codes_replace,
        name="recovery-codes-replace",
    ),
    path("sessions/", identity_views.sessions, name="sessions"),
    path(
        "sessions/<uuid:session_id>/revoke/",
        identity_views.session_revoke,
        name="session-revoke",
    ),
    path(
        "sessions/revoke-others/",
        identity_views.sessions_revoke_others,
        name="sessions-revoke-others",
    ),
    path(
        "identity/recover-mandatory-totp/",
        identity_views.mandatory_totp_recovery,
        name="mandatory-totp-recovery",
    ),
    path(
        "identity/recover-mandatory-totp/<str:raw_token>/",
        identity_views.sensitive_entry,
        {
            "purpose": "mandatory_totp_recovery",
            "clean_name": "mandatory-totp-recovery",
        },
        name="mandatory-totp-recovery-entry",
    ),
    path(
        "staff/invitations/accept/",
        staff_views.staff_invitation_accept,
        name="staff-invitation-accept",
    ),
    path(
        "access/staff-invitation/<str:raw_token>/",
        identity_views.sensitive_entry,
        {"purpose": "staff_invitation", "clean_name": "staff-invitation-accept"},
        name="staff-invitation-entry",
    ),
    path(
        "seller/applications/create/",
        seller_views.seller_application_create,
        name="seller-application-create",
    ),
    path(
        "seller/applications/<uuid:application_id>/edit/",
        seller_views.seller_application_edit,
        name="seller-application-edit",
    ),
    path(
        "seller/applications/<uuid:application_id>/submit/",
        seller_views.seller_application_submit,
        name="seller-application-submit",
    ),
    path(
        "seller/applications/<uuid:application_id>/withdraw/",
        seller_views.seller_application_withdraw,
        name="seller-application-withdraw",
    ),
    path(
        "seller/applications/",
        seller_views.seller_applications,
        name="seller-applications",
    ),
    path(
        "seller/applications/<uuid:application_id>/",
        seller_views.seller_application_detail,
        name="seller-application-detail",
    ),
    path("seller/status/", seller_views.seller_status, name="seller-status"),
]
