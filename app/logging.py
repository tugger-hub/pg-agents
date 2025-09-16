import logging
import json
from typing import Any

# A list of keys to mask in log records
SENSITIVE_KEYS = [
    "api_key",
    "secret",
    "token",
    "password",
    "authorization",
]

class SensitiveDataFilter(logging.Filter):
    """
    A logging filter that masks sensitive data in log records.
    It recursively scrubs dictionaries passed as the log message.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # We operate on the record's __dict__ so it affects the final output
        self._mask_sensitive_data(record.__dict__)
        return True

    def _mask_sensitive_data(self, data: dict):
        for key, value in data.items():
            if key in SENSITIVE_KEYS:
                data[key] = "***MASKED***"
            elif isinstance(value, dict):
                self._mask_sensitive_data(value)
            elif isinstance(value, list):
                data[key] = [self._scrub_list_item(item) for item in value]

    def _scrub_list_item(self, item: Any) -> Any:
        if isinstance(item, dict):
            # Return a scrubbed copy
            scrubbed_dict = item.copy()
            self._mask_sensitive_data(scrubbed_dict)
            return scrubbed_dict
        return item


class JsonFormatter(logging.Formatter):
    """
    A logging formatter that outputs logs in JSON format.
    """

    def format(self, record: logging.LogRecord) -> str:
        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_object["exc_info"] = self.formatException(record.exc_info)

        # Add extra fields passed to the logger.
        # These are fields that are not part of the standard LogRecord attributes.
        extra = {k: v for k, v in record.__dict__.items() if k not in logging.LogRecord.__dict__}
        if extra:
            log_object['extra'] = extra

        return json.dumps(log_object, default=str)


def setup_logging(log_level: str = "INFO"):
    """
    Configures the root logger for structured JSON logging.
    """
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Remove any existing handlers to avoid duplicate logs
    if logger.hasHandlers():
        logger.handlers.clear()

    handler = logging.StreamHandler()

    # The filter should be added to the handler
    handler.addFilter(SensitiveDataFilter())

    # Set the custom formatter
    # The format string for the formatter is not strictly needed for the JsonFormatter
    # but it's good practice to have it.
    formatter = JsonFormatter()
    handler.setFormatter(formatter)

    logger.addHandler(handler)
