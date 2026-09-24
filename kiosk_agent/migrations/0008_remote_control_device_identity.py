from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kiosk_agent", "0007_remote_button_ir_payload"),
    ]

    operations = [
        migrations.AddField(
            model_name="remotecontrol",
            name="device_name",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Must match DEVICE_NAME reported by the ESP32 /identity endpoint.",
                max_length=120,
            ),
        ),
        migrations.AddField(
            model_name="remotecontrol",
            name="device_ip",
            field=models.GenericIPAddressField(
                blank=True,
                help_text="Current IP discovered by the Sync device IPs admin action.",
                null=True,
                protocol="IPv4",
            ),
        ),
        migrations.AddField(
            model_name="remotecontrol",
            name="device_last_seen_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
    ]
