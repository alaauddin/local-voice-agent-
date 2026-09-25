import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("kiosk_agent", "0008_remote_control_device_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="remotecontrol",
            name="device_type",
            field=models.CharField(
                choices=[("raw", "Raw IR"), ("ac", "Air conditioner")],
                default="raw",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="remotecontrol",
            name="brand",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="remotecontrol",
            name="protocol",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="remotecontrol",
            name="protocol_model",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="remotecontrol",
            name="esp32_device_id",
            field=models.PositiveIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name="remotecontrol",
            name="ir_output",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.CreateModel(
            name="ACState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("power", models.BooleanField(default=False)),
                ("mode", models.CharField(choices=[("auto", "Auto"), ("cool", "Cool"), ("heat", "Heat"), ("dry", "Dry"), ("fan", "Fan")], default="cool", max_length=20)),
                ("temperature", models.PositiveSmallIntegerField(default=24)),
                ("fan", models.CharField(choices=[("auto", "Auto"), ("low", "Low"), ("medium", "Medium"), ("high", "High")], default="auto", max_length=20)),
                ("swing_vertical", models.BooleanField(default=False)),
                ("swing_horizontal", models.BooleanField(default=False)),
                ("turbo", models.BooleanField(default=False)),
                ("sleep", models.BooleanField(default=False)),
                ("eco", models.BooleanField(default=False)),
                ("quiet", models.BooleanField(default=False)),
                ("light", models.BooleanField(default=False)),
                ("x_fan", models.BooleanField(default=False)),
                ("state_version", models.PositiveBigIntegerField(default=0)),
                ("esp32_updated_at", models.PositiveBigIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("device", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="ac_state", to="kiosk_agent.remotecontrol")),
            ],
        ),
    ]
