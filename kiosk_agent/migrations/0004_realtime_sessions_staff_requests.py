import uuid

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [("kiosk_agent", "0003_saas_integration")]

    operations = [
        migrations.AddField(
            model_name="kioskmessage",
            name="event_id",
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name="kioskmessage",
            name="sequence",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="kioskmessage",
            index=models.Index(
                fields=["stay_id", "request_id", "role"],
                name="kiosk_agent_stay_requ_role_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="kioskmessage",
            index=models.Index(
                fields=["stay_id", "status", "role"],
                name="kiosk_agent_stay_stat_role_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="kioskmessage",
            constraint=models.UniqueConstraint(
                condition=Q(event_id__isnull=False),
                fields=("stay_id", "event_id"),
                name="unique_stay_realtime_event",
            ),
        ),
        migrations.AddConstraint(
            model_name="kioskmessage",
            constraint=models.UniqueConstraint(
                condition=~Q(tool_call_id=""),
                fields=("stay_id", "tool_call_id"),
                name="unique_stay_tool_call",
            ),
        ),
        migrations.CreateModel(
            name="RealtimeSession",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("stay_id", models.UUIDField(db_index=True)),
                (
                    "state",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("closed", "Closed"),
                            ("reset", "Reset"),
                            ("expired", "Expired"),
                        ],
                        default="active",
                        max_length=16,
                    ),
                ),
                ("expires_at", models.DateTimeField(db_index=True)),
                ("last_activity_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["stay_id", "state"],
                        name="kiosk_agent_stay_state_rt_idx",
                    )
                ]
            },
        ),
        migrations.CreateModel(
            name="StaffRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("stay_id", models.UUIDField(db_index=True)),
                ("request_id", models.UUIDField(db_index=True)),
                ("service", models.CharField(max_length=40)),
                ("details", models.TextField(max_length=1000)),
                ("urgency", models.CharField(max_length=12)),
                ("local_reference", models.CharField(blank=True, max_length=32, unique=True)),
                (
                    "delivery_status",
                    models.CharField(
                        choices=[
                            ("disabled", "Disabled"),
                            ("queued", "Queued"),
                            ("delivered", "Delivered"),
                            ("failed", "Failed"),
                        ],
                        default="disabled",
                        max_length=16,
                    ),
                ),
                ("external_reference", models.CharField(blank=True, max_length=160)),
                ("delivery_attempts", models.PositiveSmallIntegerField(default=0)),
                ("last_error", models.CharField(blank=True, max_length=500)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ("-created_at",)},
        ),
    ]
