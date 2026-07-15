#!/usr/bin/env python3
import sys
import os
import threading
import queue
import signal
import logging

# Fortified path injection to ensure the module root is always found
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from core.config import load_config, SMTP_PID_FILE, CONFIG_FILE
from core.logger import apply_logging_level
from backend.smtp_handler import PushoverSMTPHandler, GatewayAuthenticator, GatewayController
from backend.delivery_worker import delivery_worker, load_queue_from_disk
from backend.server import get_tls_context, get_listen_params, get_file_hash

shutdown_event = threading.Event()
reload_event = threading.Event()
mappings_reload_event = threading.Event()

def sig_handler(signum, frame):
    if signum in (signal.SIGINT, signal.SIGTERM):
        logging.info(f"Received signal {signum}. Initiating shutdown...")
        shutdown_event.set()
    elif hasattr(signal, 'SIGUSR1') and signum == signal.SIGUSR1:
        logging.info("Received SIGUSR1. Scheduling TCP listener and TLS reload...")
        reload_event.set()
    elif hasattr(signal, 'SIGUSR2') and signum == signal.SIGUSR2:
        logging.info("Received SIGUSR2. Scheduling full configuration reload...")
        mappings_reload_event.set()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)
    if hasattr(signal, 'SIGUSR1'): signal.signal(signal.SIGUSR1, sig_handler)
    if hasattr(signal, 'SIGUSR2'): signal.signal(signal.SIGUSR2, sig_handler)

    with open(SMTP_PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    logging.info(f"Loading config from file '{CONFIG_FILE}'.")
    app_state = load_config(is_reload=False)
    apply_logging_level(app_state.smtp["loglevel"])
    os.makedirs(app_state.smtp["queue_dir"], exist_ok=True)

    auth_status = "Enabled" if app_state.smtp.get("auth") else "Disabled (Permissive)"
    total_mapped = len(app_state.mappings["to"]) + len(app_state.mappings["from"]) + len(app_state.regex_mappings["to"]) + len(app_state.regex_mappings["from"])
    cap_method = app_state.smtp['default_route'].capitalize()
    logging.info(f"Explicit rules: {total_mapped}. Global Routing Method: {cap_method}. SMTP Auth: {auth_status}")

    msg_queue = queue.Queue()
    load_queue_from_disk(msg_queue, app_state)

    worker_thread = threading.Thread(target=delivery_worker, args=(msg_queue, app_state, shutdown_event), daemon=True)
    worker_thread.start()

    handler = PushoverSMTPHandler(app_state, msg_queue)
    authenticator = GatewayAuthenticator(app_state)
    active_controllers = {}

    startup_errors = False

    for l_conf in app_state.smtp["listeners"]:
        bind = l_conf["bind"]
        listen_address, listen_port = get_listen_params(bind)
        eff_hostname = l_conf.get("hostname", app_state.smtp.get("hostname"))

        try:
            tls_context = get_tls_context(l_conf, eff_hostname)
            starttls_status = "enabled" if tls_context else "disabled"

            logging.debug(f"Starting SMTP listener on {listen_address}:{listen_port} (STARTTLS: {starttls_status}, Hostname: {eff_hostname})")

            ctrl = GatewayController(
                handler, hostname=listen_address, port=listen_port, server_hostname=eff_hostname,
                tls_context=tls_context, authenticator=authenticator, auth_require_tls=False
            )
            ctrl.start()

            active_controllers[bind] = {
                "controller": ctrl,
                "config": {
                    "hostname": eff_hostname,
                    "starttls": l_conf.get("starttls", False),
                    "tls_cert_file": l_conf.get("tls_cert_file"),
                    "tls_key_file": l_conf.get("tls_key_file"),
                    "cert_hash": get_file_hash(l_conf.get("tls_cert_file")),
                    "key_hash": get_file_hash(l_conf.get("tls_key_file"))
                }
            }
            logging.info(f"SMTP listener started on {listen_address}:{listen_port} (STARTTLS: {starttls_status}, Hostname: {eff_hostname})")
        except Exception as e:
            startup_errors = True
            logging.critical(f"CRITICAL: Failed to bind SMTP listener to {bind}. Port may be occupied. Skipping. Error: {e}")

    if startup_errors:
        logging.warning("Application startup completed with errors.")
    else:
        logging.info("Application startup complete.")

    try:
        while not shutdown_event.is_set():
            if reload_event.is_set():
                reload_event.clear()
                logging.info("Checking listeners for dynamic network or TLS modifications...")

                current_binds = set(active_controllers.keys())
                new_binds = set(l["bind"] for l in app_state.smtp["listeners"])

                reload_errors = False

                for bind in current_binds - new_binds:
                    logging.info(f"Removing deprecated listener on {bind}...")
                    active_controllers[bind]["controller"].stop()
                    del active_controllers[bind]

                for l_conf in app_state.smtp["listeners"]:
                    bind = l_conf["bind"]
                    eff_hostname = l_conf.get("hostname", app_state.smtp.get("hostname"))
                    eff_cert = l_conf.get("tls_cert_file")
                    eff_key = l_conf.get("tls_key_file")
                    eff_config = {
                        "hostname": eff_hostname,
                        "starttls": l_conf.get("starttls", False),
                        "tls_cert_file": eff_cert,
                        "tls_key_file": eff_key,
                        "cert_hash": get_file_hash(eff_cert),
                        "key_hash": get_file_hash(eff_key)
                    }

                    needs_restart = False
                    if bind not in active_controllers:
                        logging.info(f"New listener declaration discovered for {bind}.")
                        needs_restart = True
                    elif active_controllers[bind]["config"] != eff_config:
                        logging.info(f"Configuration or TLS modification detected for {bind}. Restarting listener...")
                        active_controllers[bind]["controller"].stop()
                        needs_restart = True

                    if needs_restart:
                        listen_address, listen_port = get_listen_params(bind)
                        try:
                            tls_context = get_tls_context(l_conf, eff_hostname)
                            starttls_status = "enabled" if tls_context else "disabled"

                            logging.info(f"Attempting to start SMTP listener on {bind} (STARTTLS: {starttls_status}, Hostname: {eff_hostname})")

                            ctrl = GatewayController(
                                handler, hostname=listen_address, port=listen_port, server_hostname=eff_hostname,
                                tls_context=tls_context, authenticator=authenticator, auth_require_tls=False
                            )
                            ctrl.start()

                            active_controllers[bind] = {"controller": ctrl, "config": eff_config}
                            logging.info(f"SMTP listener started on {bind}")
                        except Exception as e:
                            reload_errors = True
                            logging.critical(f"CRITICAL: Failed to start SMTP listener on {bind}. Port may be occupied. Skipping. Error: {e}")

                if reload_errors:
                    logging.warning("Listener hot-reload completed with errors.")
                else:
                    logging.info("Listener hot-reload complete.")

            if mappings_reload_event.is_set():
                mappings_reload_event.clear()
                if app_state.config_file:
                    logging.info(f"Reloading gateway configurations from file '{app_state.config_file}'...")
                    new_state = load_config(is_reload=True)
                    if new_state is not None:
                        app_state.smtp.clear(); app_state.smtp.update(new_state.smtp)
                        app_state.pushover.clear(); app_state.pushover.update(new_state.pushover)
                        app_state.smarthost.clear(); app_state.smarthost.update(new_state.smarthost)
                        app_state.mappings.clear(); app_state.mappings.update(new_state.mappings)
                        app_state.regex_mappings.clear(); app_state.regex_mappings.update(new_state.regex_mappings)
                        app_state.vault.clear(); app_state.vault.update(new_state.vault)

                        apply_logging_level(app_state.smtp["loglevel"])
                        os.makedirs(app_state.smtp["queue_dir"], exist_ok=True)

                        new_auth_status = "Enabled" if app_state.smtp.get("auth") else "Disabled (Permissive)"
                        new_total = len(app_state.mappings["to"]) + len(app_state.mappings["from"]) + len(app_state.regex_mappings["to"]) + len(app_state.regex_mappings["from"])
                        cap_method = app_state.smtp['default_route'].capitalize()
                        logging.info(f"Reload success. Mappings tracked: {new_total}. Global Routing Method: {cap_method}. SMTP Auth: {new_auth_status}")
                    else:
                        logging.warning("Config reload failed. Retaining active rules matrix.")

            shutdown_event.wait(1.0)

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received.")
    finally:
        logging.info("Shutting down... Flashing queues to disk safely...")
        for data in active_controllers.values():
            data["controller"].stop()

        msg_queue.put(None)
        worker_thread.join()
        if os.path.exists(SMTP_PID_FILE):
            os.remove(SMTP_PID_FILE)
        logging.info("Shutdown complete.")
