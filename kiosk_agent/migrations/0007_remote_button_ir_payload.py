from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kiosk_agent", "0006_seed_remote_templates"),
    ]

    operations = [
        migrations.AddField(
            model_name="remotebutton",
            name="frequency",
            field=models.PositiveSmallIntegerField(
                default=38,
                help_text="IR carrier frequency in kHz.",
            ),
        ),
        migrations.AddField(
            model_name="remotebutton",
            name="ir_id",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Controller/device id sent in the JSON payload.",
            ),
        ),
        migrations.AddField(
            model_name="remotebutton",
            name="raw",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Raw IR pulse timings as a JSON array of positive integers.",
            ),
        ),
        migrations.AlterField(
            model_name="remotebutton",
            name="command_url",
            field=models.CharField(
                blank=True,
                help_text="IR controller endpoint, for example http://192.168.1.102/ir.",
                max_length=500,
            ),
        ),
    ]
