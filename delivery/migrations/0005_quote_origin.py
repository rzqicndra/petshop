from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("delivery", "0004_routeestimate")]
    operations = [
        migrations.AddField(model_name="shippingquote", name="origin_fingerprint", field=models.CharField(max_length=64, default="", blank=True)),
        migrations.AddField(model_name="shippingquote", name="origin_snapshot", field=models.JSONField(default=dict, blank=True)),
    ]
