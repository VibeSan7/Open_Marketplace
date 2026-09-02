import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('identity', '0003_accountsession'),
    ]

    operations = [
        migrations.CreateModel(
            name='RecoveryCode',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('set_id', models.UUIDField(editable=False)),
                ('code_digest', models.CharField(editable=False, max_length=64, unique=True)),
                ('issued_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(null=True)),
                ('revoked_at', models.DateTimeField(null=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recovery_codes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'identity_recovery_code',
                'indexes': [models.Index(fields=['account', 'set_id', 'used_at', 'revoked_at'], name='identity_recovery_owner_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('used_at__isnull', True), ('revoked_at__isnull', True), _connector='OR'), name='identity_recovery_not_used_and_revoked'), models.CheckConstraint(condition=models.Q(('used_at__isnull', True), ('used_at__gte', models.F('issued_at')), _connector='OR'), name='identity_recovery_used_after_issue'), models.CheckConstraint(condition=models.Q(('revoked_at__isnull', True), ('revoked_at__gte', models.F('issued_at')), _connector='OR'), name='identity_recovery_revoked_after_issue')],
            },
        ),
        migrations.CreateModel(
            name='TotpCredential',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('encrypted_secret', models.BinaryField()),
                ('confirmed_at', models.DateTimeField()),
                ('last_accepted_counter', models.PositiveBigIntegerField()),
                ('disabled_at', models.DateTimeField(null=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='totp_credentials', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'identity_totp_credential',
                'indexes': [models.Index(fields=['account', 'disabled_at'], name='identity_totp_cred_owner_idx')],
                'constraints': [models.UniqueConstraint(condition=models.Q(('disabled_at__isnull', True)), fields=('account',), name='identity_one_active_totp_credential'), models.CheckConstraint(condition=models.Q(('disabled_at__isnull', True), ('disabled_at__gte', models.F('confirmed_at')), _connector='OR'), name='identity_totp_disabled_after_confirmed')],
            },
        ),
        migrations.CreateModel(
            name='TotpRequirement',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_type', models.CharField(choices=[('staff_role', 'Staff role'), ('seller_profile', 'Seller profile')], max_length=32)),
                ('source_id', models.UUIDField(editable=False)),
                ('created_at', models.DateTimeField()),
                ('removed_at', models.DateTimeField(null=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='totp_requirements', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'identity_totp_requirement',
                'indexes': [models.Index(fields=['account', 'removed_at'], name='identity_totp_req_owner_idx')],
                'constraints': [models.UniqueConstraint(fields=('account', 'source_type', 'source_id'), name='identity_unique_totp_requirement_source'), models.CheckConstraint(condition=models.Q(('removed_at__isnull', True), ('removed_at__gte', models.F('created_at')), _connector='OR'), name='identity_totp_requirement_removed_after_create')],
            },
        ),
        migrations.CreateModel(
            name='TotpSetup',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('encrypted_secret', models.BinaryField()),
                ('created_at', models.DateTimeField()),
                ('expires_at', models.DateTimeField()),
                ('consumed_at', models.DateTimeField(null=True)),
                ('invalidated_at', models.DateTimeField(null=True)),
                ('account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='totp_setups', to=settings.AUTH_USER_MODEL)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='totp_setups', to='identity.accountsession')),
            ],
            options={
                'db_table': 'identity_totp_setup',
                'indexes': [models.Index(fields=['account', 'consumed_at', 'invalidated_at', 'expires_at'], name='identity_totp_setup_owner_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('expires_at__gt', models.F('created_at'))), name='identity_totp_setup_expiry_after_create'), models.CheckConstraint(condition=models.Q(('consumed_at__isnull', True), ('invalidated_at__isnull', True), _connector='OR'), name='identity_totp_setup_one_terminal_state'), models.CheckConstraint(condition=models.Q(('consumed_at__isnull', True), ('consumed_at__gte', models.F('created_at')), _connector='OR'), name='identity_totp_setup_consumed_after_create'), models.CheckConstraint(condition=models.Q(('invalidated_at__isnull', True), ('invalidated_at__gte', models.F('created_at')), _connector='OR'), name='identity_totp_setup_invalidated_after_create')],
            },
        ),
    ]
