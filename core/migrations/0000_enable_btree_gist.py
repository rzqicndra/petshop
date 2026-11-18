from django.contrib.postgres.operations import BtreeGistExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = []
    run_before = [("core", "0001_initial"), ("scheduling", "0001_initial")]
    operations = [BtreeGistExtension()]
