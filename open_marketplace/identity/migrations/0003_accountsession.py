import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('identity', '0002_onetimetoken'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccountSession',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('django_session_key', models.CharField(editable=False, max_length=40, unique=True)),
                ('created_at', models.DateTimeField()),
                ('last_activity_at', models.DateTimeField()),
                ('absolute_expires_at', models.DateTimeField()),
                ('reauthenticated_at', models.DateTimeField(null=True)),
                ('device_label', models.CharField(max_length=200)),
                ('revoked_at', models.DateTimeField(null=True)),
                ('revoked_reason', models.CharField(choices=[('logout', 'Logout'), ('user_revoked', 'User revoked'), ('other_sessions_revoked', 'Other sessions revoked'), ('password_changed', 'Password changed'), ('password_reset', 'Password reset'), ('optional_totp_disabled', 'Optional TOTP disabled'), ('mandatory_totp_recovered', 'Mandatory TOTP recovered'), ('account_blocked', 'Account blocked'), ('role_changed', 'Role changed'), ('compromised', 'Compromised')], max_length=64, null=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='account_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'identity_account_session',
                'indexes': [models.Index(fields=['account', 'revoked_at', 'absolute_expires_at'], name='identity_session_owner_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('absolute_expires_at__gt', models.F('created_at'))), name='identity_session_expiry_after_create'), models.CheckConstraint(condition=models.Q(('last_activity_at__gte', models.F('created_at'))), name='identity_session_activity_after_create'), models.CheckConstraint(condition=models.Q(('last_activity_at__lt', models.F('absolute_expires_at'))), name='identity_session_activity_before_expiry'), models.CheckConstraint(condition=models.Q(models.Q(('revoked_at__isnull', True), ('revoked_reason__isnull', True)), models.Q(('revoked_at__isnull', False), ('revoked_reason__isnull', False)), _connector='OR'), name='identity_session_revocation_pair'), models.CheckConstraint(condition=models.Q(('revoked_reason__isnull', True), ('revoked_reason__in', ('logout', 'user_revoked', 'other_sessions_revoked', 'password_changed', 'password_reset', 'optional_totp_disabled', 'mandatory_totp_recovered', 'account_blocked', 'role_changed', 'compromised')), _connector='OR'), name='identity_session_revocation_reason')],
            },
        ),
    ]
