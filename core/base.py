import uuid
from django.db import models


class TimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        for field in ("code", "name", "full_name", "sku", "email", "label", "business_name"):
            value = getattr(self, field, None)
            if value:
                return str(value)
        return f"{self.__class__.__name__} {str(self.pk)[:8]}"
