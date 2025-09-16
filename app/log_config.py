"""
Logging configuration for the application.

Sets up structured (JSON) logging and provides a function to configure it.
"""
import logging
import json
import os

class JsonFormatter(logging.Formatter):
    """
    Formats log records as JSON strings.
    """
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_record['exc_info'] = self.formatException(record.exc_info)

        # Placeholder for masking sensitive data
        if 'api_key' in log_record['message']:
            log_record['message'] = log_record['message'].replace('api_key', '***REDACTED***')

        return json.dumps(log_record)

def setup_logging():
    """
    Configures the root logger for the application.
    """
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Remove any existing handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create a handler that writes to stdout
    handler = logging.StreamHandler()

    # Use the JSON formatter
    formatter = JsonFormatter()
    handler.setFormatter(formatter)

    # Add the handler to the root logger
    logger.addHandler(handler)
