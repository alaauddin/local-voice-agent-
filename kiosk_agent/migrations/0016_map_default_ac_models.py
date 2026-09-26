from django.db import migrations


def map_default_models(apps, schema_editor):
    RemoteControl = apps.get_model("kiosk_agent", "RemoteControl")
    mappings = {
        "gree": "yaw1f",
        "haier_ac": "default",
        "haier_ac_yrw02": "v9014557_a",
        "haier_ac160": "default",
        "haier_ac176": "v9014557_a",
        "midea": "default",
        "kelon168": "dg11r2-01",
    }
    for protocol, model in mappings.items():
        RemoteControl.objects.filter(
            device_type="ac",
            protocol=protocol,
            protocol_model__in=("", "default"),
        ).update(protocol_model=model)


class Migration(migrations.Migration):
    dependencies = [
        ("kiosk_agent", "0015_remotecontrol_ac_control_visibility"),
    ]

    operations = [
        migrations.RunPython(map_default_models, migrations.RunPython.noop),
    ]
