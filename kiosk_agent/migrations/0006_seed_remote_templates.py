from django.db import migrations


def seed_remote_templates(apps, schema_editor):
    RemoteTemplate = apps.get_model("kiosk_agent", "RemoteTemplate")
    RemoteTemplateButton = apps.get_model("kiosk_agent", "RemoteTemplateButton")
    seeds = [
        {
            "name": "Fan",
            "slug": "fan",
            "category": "fan",
            "description": "Basic fan remote layout.",
            "buttons": [
                {"key": "power_on", "label": "Power On", "icon": "power", "row": 0, "column": 0, "sort_order": 0},
                {"key": "power_off", "label": "Power Off", "icon": "power", "row": 0, "column": 1, "sort_order": 1},
                {"key": "speed_up", "label": "Speed +", "icon": "plus", "row": 1, "column": 0, "sort_order": 2},
                {"key": "speed_down", "label": "Speed -", "icon": "minus", "row": 1, "column": 1, "sort_order": 3},
            ],
        },
        {
            "name": "AC",
            "slug": "ac",
            "category": "ac",
            "description": "Basic air conditioner layout.",
            "buttons": [
                {"key": "power_on", "label": "Power On", "icon": "power", "row": 0, "column": 0, "sort_order": 0},
                {"key": "power_off", "label": "Power Off", "icon": "power", "row": 0, "column": 1, "sort_order": 1},
                {"key": "temp_up", "label": "Temp +", "icon": "plus", "row": 1, "column": 0, "sort_order": 2},
                {"key": "temp_down", "label": "Temp -", "icon": "minus", "row": 1, "column": 1, "sort_order": 3},
                {"key": "mode", "label": "Mode", "icon": "mode", "row": 2, "column": 0, "sort_order": 4},
                {"key": "fan", "label": "Fan", "icon": "fan", "row": 2, "column": 1, "sort_order": 5},
            ],
        },
        {
            "name": "Lights",
            "slug": "lights",
            "category": "lights",
            "description": "Basic lights layout.",
            "buttons": [
                {"key": "on", "label": "On", "icon": "light", "row": 0, "column": 0, "sort_order": 0},
                {"key": "off", "label": "Off", "icon": "light", "row": 0, "column": 1, "sort_order": 1},
                {"key": "dim", "label": "Dim", "icon": "minus", "row": 1, "column": 0, "sort_order": 2},
                {"key": "bright", "label": "Bright", "icon": "plus", "row": 1, "column": 1, "sort_order": 3},
            ],
        },
    ]
    for seed in seeds:
        template, _ = RemoteTemplate.objects.get_or_create(
            slug=seed["slug"],
            defaults={
                "name": seed["name"],
                "category": seed["category"],
                "description": seed["description"],
                "is_active": True,
            },
        )
        for button in seed["buttons"]:
            RemoteTemplateButton.objects.get_or_create(
                template=template,
                key=button["key"],
                defaults={
                    "label": button["label"],
                    "icon": button.get("icon", ""),
                    "row": button["row"],
                    "column": button["column"],
                    "sort_order": button["sort_order"],
                    "requires_confirmation": button.get("requires_confirmation", False),
                },
            )


def unseed_remote_templates(apps, schema_editor):
    # Keep templates if remotes reference them (PROTECT); only remove unused seeds.
    RemoteTemplate = apps.get_model("kiosk_agent", "RemoteTemplate")
    RemoteTemplate.objects.filter(slug__in=("fan", "ac", "lights"), remotes__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("kiosk_agent", "0005_remote_control"),
    ]

    operations = [
        migrations.RunPython(seed_remote_templates, unseed_remote_templates),
    ]
