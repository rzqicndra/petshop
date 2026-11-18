from urllib.parse import urlsplit
from django.db import migrations, models


def label_known_environments(apps, schema_editor):
    Attempt = apps.get_model("billing", "PaymentAttempt")
    Attempt.objects.filter(provider="MOCK").update(environment="mock")
    # Never infer a legacy environment from the current .env: it may have changed.
    for row in Attempt.objects.filter(provider="MIDTRANS").exclude(session_url="").iterator():
        host = urlsplit(row.session_url).hostname
        environment = {"app.sandbox.midtrans.com": "midtrans_sandbox", "app.midtrans.com": "midtrans_live"}.get(host)
        if environment:
            Attempt.objects.filter(pk=row.pk).update(environment=environment)


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_initial")]
    operations = [
        migrations.AddField(model_name="paymentattempt", name="environment", field=models.CharField(max_length=30, default="", blank=True)),
        migrations.RunPython(label_known_environments, migrations.RunPython.noop),
    ]
