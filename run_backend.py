#!/usr/bin/env python3
import sys
import os
import signal
import logging
import asyncio

# Fortified path injection to ensure the module root is always found
SCRIPT_DIR = os.path.dirname(os.path.realpath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from core.config import load_config, SMTP_PID_FILE, CONFIG_FILE
from core.logger import apply_logging_level
from backend.smtp_handler import PushoverSMTPHandler, GatewayAuthenticator, GatewaySMTP
from backend.delivery_worker import async_delivery_manager, load_queue_from_disk
from backend.server import get_tls_context, get_listen_params, get_file_hash
from backend.control_api import start_control_api, stop_control_api
from backend.events import broker

def get_smtp_factory(handler, eff_hostname, tls_context, authenticator):
    """
    Safely constructs the aiosmtpd Protocol class.
    Attributes that are not supported in the __init__ signature are bound post-instantiation.
    """
    def factory():
        smtp_instance = GatewaySMTP(
            handler,
            ident=eff_hostname,
            tls_context=tls_context,
            authenticator=authenticator,
            auth_require_tls=False
        )

        # Explicitly set the internal hostname used for EHLO responses
        smtp_instance.hostname = eff_hostname

        # Safely enforce size limits without triggering kwargs TypeErrors
        if hasattr(smtp_instance, 'command_size_limit'):
            smtp_instance.command_size_limit = 10485760
        if hasattr(smtp_instance, 'data_line_length_limit'):
            smtp_instance.data_line_length_limit = 10485760

        return smtp_instance
    return factory

async def main():
    shutdown_event = asyncio.Event()
    reload_event = asyncio.Event()
    mappings_reload_event = asyncio.Event()

    loop = asyncio.get_running_loop()

    def _sig_handler(signum):
        if signum in (signal.SIGINT, signal.SIGTERM):
            logging.info(f"Received signal {signum}. Initiating graceful shutdown...")
            shutdown_event.set()
        elif signum == getattr(signal, 'SIGUSR1', None):
            logging.info("Received SIGUSR1. Scheduling TCP listener and TLS reload...")
            reload_event.set()
        elif signum == getattr(signal, 'SIGUSR2', None):
            logging.info("Received SIGUSR2. Scheduling full configuration reload...")
            mappings_reload_event.set()

    try:
        loop.add_signal_handler(signal.SIGINT, _sig_handler, signal.SIGINT)
        loop.add_signal_handler(signal.SIGTERM, _sig_handler, signal.SIGTERM)
        if hasattr(signal, 'SIGUSR1'): loop.add_signal_handler(signal.SIGUSR1, _sig_handler, signal.SIGUSR1)
        if hasattr(signal, 'SIGUSR2'): loop.add_signal_handler(signal.SIGUSR2, _sig_handler, signal.SIGUSR2)
    except NotImplementedError:
        pass # Windows development fallback (Docker environments guarantee POSIX signals)

    with open(SMTP_PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    logging.info(f"Loading config from file '{CONFIG_FILE}'.")
    app_state = load_config()
    apply_logging_level(app_state.smtp["loglevel"])
    os.makedirs(app_state.smtp["queue_dir"], exist_ok=True)

    auth_status = "Enabled" if app_state.smtp.get("auth") else "Disabled (Permissive)"
    total_mapped = len(app_state.mappings["to"]) + len(app_state.mappings["from"]) + len(app_state.regex_mappings["to"]) + len(app_state.regex_mappings["from"])
    cap_method = app_state.smtp['default_route'].capitalize()
    logging.info(f"Explicit rules: {total_mapped}. Global Routing Method: {cap_method}. SMTP Auth: {auth_status}")

    api_task = None
    api_conf = app_state.smtp.get("api", {})
    if api_conf.get("enabled"):
        api_task = asyncio.create_task(start_control_api(api_conf, reload_event, mappings_reload_event, gateway_state=app_state))

    msg_queue = asyncio.Queue()
    load_queue_from_disk(msg_queue, app_state)

    # Boot 5 concurrent delivery tasks in the background
    num_workers = 5
    worker_task = asyncio.create_task(async_delivery_manager(msg_queue, app_state, num_workers, broker))

    handler = PushoverSMTPHandler(app_state, msg_queue, broker)
    authenticator = GatewayAuthenticator(app_state)
    active_servers = {}

    startup_errors = False

    for l_conf in app_state.smtp["listeners"]:
        bind = l_conf["bind"]
        listen_address, listen_port = get_listen_params(bind)
        eff_hostname = l_conf.get("hostname", app_state.smtp.get("hostname"))

        try:
            tls_context = get_tls_context(l_conf, eff_hostname)
            starttls_status = "enabled" if tls_context else "disabled"

            logging.debug(f"Starting SMTP listener on {listen_address}:{listen_port} (STARTTLS: {starttls_status}, Hostname: {eff_hostname})")

            factory = get_smtp_factory(handler, eff_hostname, tls_context, authenticator)
            server = await loop.create_server(factory, host=listen_address, port=listen_port)

            active_servers[bind] = {
                "server": server,
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
            logging.critical(f"CRITICAL: Failed to bind SMTP listener to {bind}. Port may be occupied. Error: {e}")

    if startup_errors:
        logging.warning("Application startup completed with errors.")
    else:
        logging.info("Application startup complete.")

    try:
        while not shutdown_event.is_set():
            # Soft wait allows the loop to periodically catch signals gracefully
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(shutdown_event.wait()),
                    asyncio.create_task(reload_event.wait()),
                    asyncio.create_task(mappings_reload_event.wait())
                ],
                return_when=asyncio.FIRST_COMPLETED,
                timeout=1.0
            )

            if reload_event.is_set():
                reload_event.clear()
                logging.info("Checking listeners for dynamic network or TLS modifications...")

                fresh_state = load_config()
                if fresh_state is not None:
                    app_state.smtp["listeners"] = fresh_state.smtp.get("listeners", [])

                current_binds = set(active_servers.keys())
                new_binds = set(l["bind"] for l in app_state.smtp["listeners"])

                reload_errors = False

                for bind in current_binds - new_binds:
                    logging.info(f"Removing deprecated listener on {bind}...")
                    srv = active_servers[bind]["server"]
                    srv.close()
                    await srv.wait_closed()
                    del active_servers[bind]

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
                    if bind not in active_servers:
                        logging.info(f"New listener declaration discovered for {bind}.")
                        needs_restart = True
                    elif active_servers[bind]["config"] != eff_config:
                        logging.info(f"Configuration or TLS modification detected for {bind}. Restarting listener...")
                        srv = active_servers[bind]["server"]
                        srv.close()
                        await srv.wait_closed()
                        needs_restart = True

                    if needs_restart:
                        listen_address, listen_port = get_listen_params(bind)
                        try:
                            tls_context = get_tls_context(l_conf, eff_hostname)
                            starttls_status = "enabled" if tls_context else "disabled"

                            logging.debug(f"Starting SMTP listener on {listen_address}:{listen_port} (STARTTLS: {starttls_status}, Hostname: {eff_hostname})")

                            factory = get_smtp_factory(handler, eff_hostname, tls_context, authenticator)
                            server = await loop.create_server(factory, host=listen_address, port=listen_port)

                            active_servers[bind] = {"server": server, "config": eff_config}
                            logging.info(f"SMTP listener started on {listen_address}:{listen_port} (STARTTLS: {starttls_status}, Hostname: {eff_hostname})")
                        except Exception as e:
                            reload_errors = True
                            logging.critical(f"CRITICAL: Failed to start SMTP listener on {bind}. Port may be occupied. Error: {e}")

                if reload_errors:
                    logging.warning("Listener hot-reload completed with errors.")
                else:
                    logging.info("Listener hot-reload complete.")

            if mappings_reload_event.is_set():
                mappings_reload_event.clear()

                old_api_conf = app_state.smtp.get("api", {})

                if app_state.config_file:
                    logging.info(f"Reloading gateway configurations from file '{app_state.config_file}'...")
                    new_state = load_config()

                    if new_state is not None:
                        app_state.smtp.clear(); app_state.smtp.update(new_state.smtp)
                        app_state.pushover.clear(); app_state.pushover.update(new_state.pushover)
                        app_state.smarthost.clear(); app_state.smarthost.update(new_state.smarthost)
                        app_state.mappings.clear(); app_state.mappings.update(new_state.mappings)
                        app_state.regex_mappings.clear(); app_state.regex_mappings.update(new_state.regex_mappings)
                        app_state.vault.clear(); app_state.vault.update(new_state.vault)
                        broker.publish("CONFIG_RELOADED")

                        new_api_conf = app_state.smtp.get("api", {})
                        if old_api_conf != new_api_conf:
                            logging.info("Control API configuration change detected. Restarting API listener...")
                            await stop_control_api()

                            if api_task:
                                try:
                                    await asyncio.wait_for(api_task, timeout=2.0)
                                except Exception:
                                    pass

                            if new_api_conf.get("enabled"):
                                api_task = asyncio.create_task(start_control_api(new_api_conf, reload_event, mappings_reload_event, gateway_state=app_state))

                        apply_logging_level(app_state.smtp["loglevel"])
                        os.makedirs(app_state.smtp["queue_dir"], exist_ok=True)

                        new_auth_status = "Enabled" if app_state.smtp.get("auth") else "Disabled (Permissive)"
                        new_total = len(app_state.mappings["to"]) + len(app_state.mappings["from"]) + len(app_state.regex_mappings["to"]) + len(app_state.regex_mappings["from"])
                        cap_method = app_state.smtp['default_route'].capitalize()
                        logging.info(f"Reload success. Mappings tracked: {new_total}. Global Routing Method: {cap_method}. SMTP Auth: {new_auth_status}")
                    else:
                        logging.warning("Config reload failed. Retaining active rules matrix.")

    finally:
        logging.info("Shutting down... Flashing queues to disk safely...")
        await stop_control_api()

        # Gracefully await the Uvicorn task teardown to prevent CancelledError traces
        if api_task:
            try:
                await asyncio.wait_for(api_task, timeout=2.0)
            except Exception:
                pass

        # Close all SMTP sockets to forcefully stop new traffic
        for data in active_servers.values():
            srv = data["server"]
            srv.close()
            await srv.wait_closed()

        # Push shutdown sentinels to tear down the 5 concurrent worker tasks gracefully
        for _ in range(num_workers):
            await msg_queue.put(None)

        # Await execution completion
        await worker_task

        if os.path.exists(SMTP_PID_FILE):
            os.remove(SMTP_PID_FILE)
        logging.info("Shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
