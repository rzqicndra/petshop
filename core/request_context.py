from contextvars import ContextVar

# Context-local: never shared between requests or worker tasks.
request_id = ContextVar("sinau_request_id", default=None)
