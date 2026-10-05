from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("kiosk_agent", "0016_map_default_ac_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="remotecontrol",
            name="controller_url",
            field=models.URLField(
                blank=True,
                help_text="Base URL of the dedicated controller, for example http://192.168.1.50.",
                max_length=500,
            ),
        ),
        migrations.AlterField(
            model_name="remotecontrol",
            name="device_type",
            field=models.CharField(
                choices=[
                    ("raw", "Raw IR"),
                    ("ac", "Air conditioner"),
                    ("lg_tv", "LG TV"),
                ],
                default="raw",
                max_length=20,
            ),
        ),
    ]
