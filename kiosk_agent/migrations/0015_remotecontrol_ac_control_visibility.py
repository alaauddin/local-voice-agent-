from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("kiosk_agent", "0014_alter_remotebutton_key_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="remotecontrol",
            name="ac_control_visibility",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Per-control visibility overrides for the AC guest interface.",
            ),
        ),
    ]
