import logging

# Ensure root logger is explicitly initialized with standard formatting across all imported modules
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

aiosmtpd_logger = logging.getLogger('mail.log')

class SuppressAiosmtpdNoiseFilter(logging.Filter):
    def filter(self, record):
        # If the user sets the gateway to DEBUG mode, let everything through
        if logging.getLogger().getEffectiveLevel() <= logging.DEBUG: return True

        msg = record.getMessage()
        # Drop the TLS gibberish probe warnings and the internal aiosmtpd deprecation bug
        if "unrecognised" in msg or "login_data is deprecated" in msg:
            return False
        return True

class SuppressUvicornNoiseFilter(logging.Filter):
    """Unified filter to strip transient framework process messages from console streams."""
    def filter(self, record):
        msg = record.getMessage()
        suppress_list = [
            "Started server process",
            "Waiting for application startup",
            "Application startup complete",
            "Uvicorn running on",
            "Shutting down",
            "Waiting for connections to close",
            "Finished server process"
        ]
        return not any(s in msg for s in suppress_list)

# Apply noise reduction to mail framework
aiosmtpd_logger.addFilter(SuppressAiosmtpdNoiseFilter())

# Securely mask server framework logs on the backend process space
uvicorn_error = logging.getLogger("uvicorn.error")
uvicorn_core = logging.getLogger("uvicorn")
uvicorn_error.addFilter(SuppressUvicornNoiseFilter())
uvicorn_core.addFilter(SuppressUvicornNoiseFilter())

def apply_logging_level(loglevel_str):
    log_level = getattr(logging, loglevel_str, logging.INFO)
    logging.getLogger().setLevel(log_level)
    for handler in logging.getLogger().handlers: handler.setLevel(log_level)
    if log_level > logging.DEBUG: aiosmtpd_logger.setLevel(logging.WARNING)
    else: aiosmtpd_logger.setLevel(logging.DEBUG)
