from django.test import TestCase

from engagement.services import queue_due_reminders


class ReminderQueryTests(TestCase):
    def test_maintenance_accepts_empty_reminders_with_nullable_sources(self):
        # PostgreSQL rejects a FOR UPDATE on nullable joins even with zero rows.
        # Exercise the query, rather than mocking its SQL execution.
        queue_due_reminders()
