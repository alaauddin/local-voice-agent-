from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("kiosk_agent", "0009_ac_control"),
    ]

    operations = [
        migrations.AlterField(
            model_name="remotecontrol",
            name="brand",
            field=models.CharField(
                blank=True,
                choices=[
                    ("gree", "Gree"),
                    ("haier", "Haier"),
                    ("midea", "Midea"),
                    ("hisense", "Hisense"),
                ],
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="remotecontrol",
            name="protocol",
            field=models.CharField(
                blank=True,
                choices=[
                    ("gree", "Gree"),
                    ("haier_ac", "Haier AC"),
                    ("haier_ac_yrw02", "Haier AC YR-W02"),
                    ("haier_ac160", "Haier AC 160-bit"),
                    ("haier_ac176", "Haier AC 176-bit"),
                    ("midea", "Midea"),
                    ("kelon168", "Kelon 168-bit (Hisense)"),
                ],
                max_length=50,
            ),
        ),
        migrations.AlterField(
            model_name="remotecontrol",
            name="protocol_model",
            field=models.CharField(
                blank=True,
                choices=[
                    ("default", "Default"),
                    ("yaw1f", "Gree YAW1F"),
                    ("ybofb", "Gree YBOFB"),
                    ("yx1fsf", "Gree YX1FSF"),
                    ("v9014557_a", "Haier V9014557 A"),
                    ("v9014557_b", "Haier V9014557 B"),
                    ("dg11r2-01", "Hisense/Kelon DG11R2-01"),
                ],
                max_length=50,
            ),
        ),
    ]
