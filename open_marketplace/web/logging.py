import logging
import re

_TOKEN_PATHS = re.compile(
    r"(?P<prefix>/(?:identity/(?:verify-email|reset-password|recover-mandatory-totp)|access/staff-invitation)/)[^/?\s]+"
)


def _redact(value):
    if not isinstance(value, str):
        return value
    return _TOKEN_PATHS.sub(r"\g<prefix>[REDACTED]", value)


class SensitiveRouteFilter(logging.Filter):
    def filter(self, record):
        record.msg = _redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(_redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: _redact(value) for key, value in record.args.items()}
        request = getattr(record, "request", None)
        if request is not None and hasattr(request, "path"):
            record.safe_path = _redact(request.path)
        record.request_id = str(getattr(request, "request_id", "-"))
        if record.exc_info is not None:
            record.msg = "Unhandled request exception"
            record.args = ()
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True
