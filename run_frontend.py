#!/usr/bin/env python3
import sys
import os
import threading
import time
import signal
import logging
import uvicorn

# Establish baseline logging format before Uvicorn seizes the console
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Fortified path injection to ensure the module root is always found
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from core.config import load_clean_json, UI_CONFIG_FILE
from frontend.api import app, generate_ui_cert

class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "/healthcheck" not in record.getMessage() and "/api/queue" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

ui_shutdown_event = threading.Event()
ui_reload_listeners_event = threading.Event()
ui_reload_configs_event = threading.Event()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: ui_shutdown_event.set())
    signal.signal(signal.SIGTERM, lambda s, f: ui_shutdown_event.set())
    if hasattr(signal, 'SIGUSR1'): signal.signal(signal.SIGUSR1, lambda s, f: ui_reload_listeners_event.set())
    if hasattr(signal, 'SIGUSR2'): signal.signal(signal.SIGUSR2, lambda s, f: ui_reload_configs_event.set())

    while not ui_shutdown_event.is_set():
        if ui_reload_configs_event.is_set():
            ui_reload_configs_event.clear()
            logging.info("Caught SIGUSR2 inside UI process space. Configuration cache cleared.")

        ui_config = load_clean_json(UI_CONFIG_FILE)
        port = ui_config.get("port", 8443)
        use_https = ui_config.get("https", True)

        ui_loglevel_str = ui_config.get("ui_loglevel", "INFO")
        log_level = getattr(logging, ui_loglevel_str.upper(), logging.INFO)
        logging.getLogger().setLevel(log_level)
        for handler in logging.getLogger().handlers:
            handler.setLevel(log_level)

        if use_https:
            cert_file, key_file = ui_config.get("tls_cert"), ui_config.get("tls_key")
            if not cert_file or not os.path.exists(cert_file): cert_file, key_file = generate_ui_cert()
            server_config = uvicorn.Config(app, host="0.0.0.0", port=port, ssl_keyfile=key_file, ssl_certfile=cert_file, log_level=ui_loglevel_str.lower())
        else:
            server_config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level=ui_loglevel_str.lower())

        server = uvicorn.Server(server_config)
        t = threading.Thread(target=server.run)
        t.start()

        while t.is_alive():
            if ui_reload_configs_event.is_set():
                ui_reload_configs_event.clear()
                logging.info("Caught SIGUSR2 inside UI process space. Configuration cache cleared.")

            if ui_reload_listeners_event.is_set() or ui_shutdown_event.is_set():
                server.should_exit = True
                if ui_reload_listeners_event.is_set():
                    ui_reload_listeners_event.clear()
                    logging.info("Caught SIGUSR1 inside UI process space. Hot-reloading network port binders...")
                break
            time.sleep(1)
        t.join()
