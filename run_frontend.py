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

from core.config import load_clean_json, save_json, UI_CONFIG_FILE, clear_ui_config_cache, get_cached_ui_config
from core.logger import SuppressUvicornNoiseFilter
from frontend.api import app
from frontend.utils import generate_ui_cert

# Centralized hooks applied directly to the frontend process space
logging.getLogger("uvicorn.error").addFilter(SuppressUvicornNoiseFilter())
logging.getLogger("uvicorn").addFilter(SuppressUvicornNoiseFilter())

ui_shutdown_event = threading.Event()
ui_reload_listeners_event = threading.Event()
ui_reload_configs_event = threading.Event()

def start_server(srv, bnd):
    try:
        srv.run()
    except SystemExit:
        logging.critical(f"CRITICAL: UI listener on {bnd} aborted unexpectedly. Port may be occupied.")
    except Exception as e:
        logging.critical(f"CRITICAL: Failed to start UI listener on {bnd}. Error: {e}")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s, f: ui_shutdown_event.set())
    signal.signal(signal.SIGTERM, lambda s, f: ui_shutdown_event.set())
    if hasattr(signal, 'SIGUSR1'): signal.signal(signal.SIGUSR1, lambda s, f: ui_reload_listeners_event.set())
    if hasattr(signal, 'SIGUSR2'): signal.signal(signal.SIGUSR2, lambda s, f: ui_reload_configs_event.set())

    # Initial priming of the RAM Cache at startup
    ui_config = get_cached_ui_config(force_refresh=True)
    if "local_config_path" not in ui_config:
        env_config = os.environ.get("GATEWAY_CONFIG")
        ui_config["local_config_path"] = env_config if env_config else os.path.join(SCRIPT_DIR, "config.json")
        save_json(UI_CONFIG_FILE, ui_config)
        clear_ui_config_cache()
        logging.info(f"Migrated local config path '{ui_config['local_config_path']}' to UI state.")

    while not ui_shutdown_event.is_set():
        if ui_reload_configs_event.is_set():
            ui_reload_configs_event.clear()
            logging.info("Caught SIGUSR2 inside UI process space. Configuration cache flushed.")
            clear_ui_config_cache()

        # Reads directly out of RAM cache
        ui_config = get_cached_ui_config()

        os.environ["GATEWAY_CONFIG"] = ui_config.get("local_config_path", os.path.join(SCRIPT_DIR, "config.json"))

        ui_loglevel_str = ui_config.get("ui_loglevel", "INFO")
        log_level = getattr(logging, ui_loglevel_str.upper(), logging.INFO)
        logging.getLogger().setLevel(log_level)
        for handler in logging.getLogger().handlers:
            handler.setLevel(log_level)

        logging.info(f"Loading config from file '{UI_CONFIG_FILE}'.")

        listeners = ui_config.get("listeners")
        if not listeners or not isinstance(listeners, list):
            port = ui_config.get("port", 8443)
            use_https = ui_config.get("https", True)
            listeners = [{
                "bind": f"0.0.0.0:{port}",
                "https": use_https,
                "tls_cert": ui_config.get("tls_cert", ""),
                "tls_key": ui_config.get("tls_key", "")
            }]

        servers = []
        threads = []
        startup_tracking = []

        for l_conf in listeners:
            bind = l_conf.get("bind", "0.0.0.0:8443")
            use_https = l_conf.get("https", True)
            host, port_str = bind.rsplit(":", 1) if ":" in bind else (bind, "8443")
            port = int(port_str)

            protocol = "https" if use_https else "http"

            if use_https:
                cert_file, key_file = l_conf.get("tls_cert", ""), l_conf.get("tls_key", "")
                if not cert_file or not os.path.exists(cert_file): cert_file, key_file = generate_ui_cert()
                server_config = uvicorn.Config(
                    app, host=host, port=port, ssl_keyfile=key_file, ssl_certfile=cert_file,
                    log_level=ui_loglevel_str.lower(), log_config=None, access_log=False
                )
            else:
                server_config = uvicorn.Config(
                    app, host=host, port=port, log_level=ui_loglevel_str.lower(),
                    log_config=None, access_log=False
                )

            server = uvicorn.Server(server_config)
            servers.append(server)
            t = threading.Thread(target=start_server, args=(server, bind))
            threads.append(t)

            startup_tracking.append({
                "server": server,
                "thread": t,
                "protocol": protocol,
                "host": host,
                "port": port
            })

            logging.debug(f"Starting UI listener at {protocol}://{host}:{port}")
            t.start()

        startup_errors = False
        for tracker in startup_tracking:
            server = tracker["server"]
            t = tracker["thread"]

            while not server.started and t.is_alive():
                time.sleep(0.05)

            if server.started:
                logging.info(f"UI listener started at {tracker['protocol']}://{tracker['host']}:{tracker['port']}")
            else:
                startup_errors = True

        if startup_errors:
            logging.warning("Application startup completed with errors.")
        else:
            logging.info("Application startup complete.")

        while any(t.is_alive() for t in threads):
            if ui_reload_configs_event.is_set():
                ui_reload_configs_event.clear()
                logging.info("Caught SIGUSR2 inside UI process space. Configuration cache flushed.")
                clear_ui_config_cache()

            if ui_reload_listeners_event.is_set() or ui_shutdown_event.is_set():
                for s in servers: s.should_exit = True
                if ui_reload_listeners_event.is_set():
                    ui_reload_listeners_event.clear()
                    logging.info("Caught SIGUSR1 inside UI process space. Hot-reloading network port binders...")
                break
            time.sleep(1)

        for t in threads:
            t.join()
