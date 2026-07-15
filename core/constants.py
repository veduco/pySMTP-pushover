import os

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CONFIG_FILE = os.environ.get("GATEWAY_CONFIG", os.path.join(SCRIPT_DIR, "config.json"))
UI_CONFIG_FILE = os.environ.get("UI_CONFIG", os.path.join(SCRIPT_DIR, "ui_config.json"))
SMTP_PID_FILE = os.path.join(SCRIPT_DIR, "smtp.pid")

MAX_TITLE_CHARS = 250
MAX_ATTACHMENT_BYTES = 2621440  # 2.5MB
MAX_URL_CHARS = 512
MAX_URL_TITLE_CHARS = 100
PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
