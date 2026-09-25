from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("kiosk_agent", "0010_remotecontrol_ac_choices"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="remotecontrol",
            name="esp32_device_id",
        ),
        migrations.RemoveField(
            model_name="remotecontrol",
            name="ir_output",
        ),
        migrations.AddConstraint(
            model_name="remotecontrol",
            constraint=models.UniqueConstraint(
                condition=models.Q(device_type="ac") & ~models.Q(device_name=""),
                fields=("device_name",),
                name="uniq_ac_remote_device_name",
            ),
        ),
    ]
