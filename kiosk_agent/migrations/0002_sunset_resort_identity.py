from django.db import migrations, models


def apply_sunset_identity(apps, schema_editor):
    ChaletConfig = apps.get_model("kiosk_agent", "ChaletConfig")
    config = ChaletConfig.objects.filter(pk=1).first()
    if config is None:
        return

    changed_fields = []
    if config.chalet_name == "Chalet 101":
        config.chalet_name = "منتجع الغروب"
        changed_fields.append("chalet_name")
    if config.persona_name == "Wazen":
        config.persona_name = "غروب"
        changed_fields.append("persona_name")
    if not config.welcome_message:
        config.welcome_message = "قل «يا غروب» واطلب ما تحتاجه، وسأبقى معك طوال المحادثة."
        changed_fields.append("welcome_message")
    if changed_fields:
        config.save(update_fields=changed_fields)


class Migration(migrations.Migration):
    dependencies = [("kiosk_agent", "0001_initial")]

    operations = [
        migrations.AlterField(
            model_name="chaletconfig",
            name="chalet_name",
            field=models.CharField(default="منتجع الغروب", max_length=120),
        ),
        migrations.AlterField(
            model_name="chaletconfig",
            name="persona_name",
            field=models.CharField(default="غروب", max_length=80),
        ),
        migrations.AlterField(
            model_name="chaletconfig",
            name="welcome_message",
            field=models.TextField(
                blank=True,
                default="قل «يا غروب» واطلب ما تحتاجه، وسأبقى معك طوال المحادثة.",
            ),
        ),
        migrations.RunPython(apply_sunset_identity, migrations.RunPython.noop),
    ]
