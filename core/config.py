import os
import json
import re
import logging
import time

SCRIPT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE = os.environ.get("GATEWAY_CONFIG", os.path.join(SCRIPT_DIR, "config.json"))
UI_CONFIG_FILE = os.environ.get("UI_CONFIG", os.path.join(SCRIPT_DIR, "ui_config.json"))
SMTP_PID_FILE = "/tmp/smtp_pushover.pid"

PUSHOVER_API_URL = "https://api.pushover.net/1/messages.json"
MAX_ATTACHMENT_BYTES = 5242880
MAX_TITLE_CHARS = 250
MAX_URL_CHARS = 512
MAX_URL_TITLE_CHARS = 100

class GatewayState:
    def __init__(self):
        self.smtp = {}
        self.pushover = {}
        self.smarthost = {}
        self.mappings = {"to": {}, "from": {}}
        self.regex_mappings = {"to": [], "from": []}
        self.config_file = None
        self.vault_file = None
        self.vault = {}

def get_bool(val, default=False):
    if val is None: return default
    return str(val).lower() in ("1", "true", "yes")

def load_clean_json(filepath):
    if not os.path.exists(filepath): return {}
    try:
        with open(filepath, 'r') as f: content = f.read()
        content = re.sub(r'(^|\s)/\*.*?\*/', r'\1', content, flags=re.DOTALL)
        content = re.sub(r'(^|\s)(//|#).*', r'\1', content)
        return json.loads(content)
    except Exception:
        return {}

def save_json(filepath, data):
    with open(filepath, 'w') as f: json.dump(data, f, indent=2)

def load_vault_safe(filepath):
    v = load_clean_json(filepath)
    out = {"app": {}, "user": {}, "smarthost": {}}
    for vtype in ["app", "user", "smarthost"]:
        for alias, val in v.get(vtype, {}).items():
            # Auto-upgrade flat strings to unified dict objects
            if isinstance(val, dict): out[vtype][alias] = val
            else: out[vtype][alias] = {"token": val, "epoch": 0}
    return out

def get_unified_backups(base_dir):
    prefix = ".gateway.valid."
    backups = []
    if os.path.exists(base_dir):
        for f in os.listdir(base_dir):
            if f.startswith(prefix) and f.endswith(".json"):
                backups.append(os.path.join(base_dir, f))

    def extract_epoch(p):
        try: return int(p.split('.')[-2])
        except ValueError: return 0

    backups.sort(key=extract_epoch, reverse=True)
    return backups

def save_unified_backup_if_changed(base_dir, config_data, vault_data, max_backups=50):
    if max_backups <= 0: return

    new_snapshot = {"config": config_data, "vault": vault_data}
    backups = get_unified_backups(base_dir)

    if backups:
        latest_data = load_clean_json(backups[0])
        if latest_data == new_snapshot:
            return

    epoch = int(time.time())
    new_backup_path = os.path.join(base_dir, f".gateway.valid.{epoch}.json")
    save_json(new_backup_path, new_snapshot)

    backups = get_unified_backups(base_dir)
    while len(backups) > max_backups:
        old_file = backups.pop()
        try: os.remove(old_file)
        except OSError: pass

def _build_and_validate_state(config_root, vault_data, file_path, vault_path):
    if "routes" not in config_root:
        config_root["routes"] = {}
        reserved_keys = ["user", "token", "device", "sound", "url", "url_title", "tags", "priority", "ttl", "retry", "expire", "attachments", "force_plaintext", "disable_persistence"]
        po = config_root.get("pushover", {})
        to_del = []
        for k, v in po.items():
            if k not in reserved_keys and isinstance(v, dict):
                v["method"] = "pushover"
                config_root["routes"][k] = v
                to_del.append(k)
        for k in to_del: del po[k]

    if "disable_persistence" in config_root.get("pushover", {}):
        if "smtp" not in config_root: config_root["smtp"] = {}
        config_root["smtp"]["disable_persistence"] = config_root["pushover"]["disable_persistence"]
        del config_root["pushover"]["disable_persistence"]

    smtp_json = config_root.get("smtp", {})
    pushover_json = config_root.get("pushover", {})
    smarthost_json = config_root.get("smarthost", {"aliases": {}, "globals": {}})
    routes_json = config_root.get("routes", {})

    new_state = GatewayState()
    new_state.config_file = file_path
    new_state.vault_file = vault_path

    # Flatten the unified vault objects into raw strings for the worker memory state
    flat_vault = {"app": {}, "user": {}, "smarthost": {}}
    for vt in ["app", "user", "smarthost"]:
        for alias, data_dict in vault_data.get(vt, {}).items():
            flat_vault[vt][alias] = data_dict.get("token", "")
    new_state.vault = flat_vault

    new_state.smtp = {
        "default_route": smtp_json.get("default_route", "pushover"),
        "disable_persistence": get_bool(smtp_json.get("disable_persistence", False)),
        "auth": smtp_json.get("auth", {}),
        "queue_dir": smtp_json.get("queue_dir", "queue"),
        "hostname": smtp_json.get("hostname"),
        "tls_cert_file": smtp_json.get("tls_cert_file"),
        "tls_key_file": smtp_json.get("tls_key_file"),
        "max_retry_backoff": int(smtp_json.get("max_retry_backoff", 21600)),
        "max_backups": int(smtp_json.get("max_backups", 50)),
        "loglevel": smtp_json.get("loglevel", "INFO").upper()
    }

    listeners = smtp_json.get("listeners")
    if not isinstance(listeners, list) or len(listeners) == 0: listeners = [{"bind": "0.0.0.0:25", "starttls": False}]

    for l in listeners:
        l["bind"] = l.get("bind", "0.0.0.0:25")
        l["starttls"] = get_bool(l.get("starttls"))
        if "hostname" in l and str(l["hostname"]).strip(): l["hostname"] = str(l["hostname"]).strip()
        if l["starttls"]:
            l["tls_cert_file"] = l.get("tls_cert_file", new_state.smtp.get("tls_cert_file"))
            l["tls_key_file"] = l.get("tls_key_file", new_state.smtp.get("tls_key_file"))

    new_state.smtp["listeners"] = listeners
    new_state.smtp["queue_dir"] = os.path.normpath(os.path.join(SCRIPT_DIR, new_state.smtp["queue_dir"]))

    new_state.smarthost = {
        "aliases": {},
        "globals": {
            "alias": smarthost_json.get("globals", {}).get("alias"),
            "force_plaintext": get_bool(smarthost_json.get("globals", {}).get("force_plaintext", False)),
            "disable_attachments": get_bool(smarthost_json.get("globals", {}).get("disable_attachments", False))
        }
    }

    for alias, sh in smarthost_json.get("aliases", {}).items():
        new_state.smarthost["aliases"][alias] = {
            "hostname": sh.get("hostname", ""),
            "port": int(sh.get("port", 25)),
            "advertised_hostname": sh.get("advertised_hostname", ""),
            "starttls": get_bool(sh.get("starttls")),
            "disable_tls_validation": get_bool(sh.get("disable_tls_validation")),
            "auth": get_bool(sh.get("auth")),
            "username": sh.get("username", ""),
            "disable_attachments": get_bool(sh.get("disable_attachments")),
            "force_plaintext": get_bool(sh.get("force_plaintext")),
        }

    def _resolve_tok(key, *flat_sections):
        if not key: return key
        for sec in flat_sections:
            if key in sec: return sec[key]
        return key

    global_user = _resolve_tok(pushover_json.get("user"), flat_vault["user"], flat_vault["app"])
    global_token = _resolve_tok(pushover_json.get("token"), flat_vault["app"])

    new_state.pushover = {
        "method": "pushover",
        "user": global_user,
        "token": global_token,
        "device": pushover_json.get("device"),
        "sound": pushover_json.get("sound"),
        "url": pushover_json.get("url"),
        "url_title": pushover_json.get("url_title"),
        "tags": pushover_json.get("tags"),
        "priority": pushover_json.get("priority"),
        "ttl": pushover_json.get("ttl"),
        "retry": pushover_json.get("retry"),
        "expire": pushover_json.get("expire"),
        "attachments": get_bool(pushover_json.get("attachments", True)),
        "force_plaintext": get_bool(pushover_json.get("force_plaintext"))
    }

    for int_param in ["priority", "ttl", "retry", "expire"]:
        val = new_state.pushover.get(int_param)
        if val is not None and str(val).strip():
            try: new_state.pushover[int_param] = int(val)
            except ValueError: new_state.pushover[int_param] = None

    if new_state.pushover.get("priority") == 2:
        r_val = new_state.pushover.get("retry")
        e_val = new_state.pushover.get("expire")
        if r_val is None or e_val is None or r_val < 30 or e_val > 10800:
            raise ValueError("Global priority is 2, but valid 'retry' (>=30) and 'expire' (<=10800) are not properly defined.")

    if new_state.pushover.get("url") and len(new_state.pushover["url"]) > MAX_URL_CHARS:
        logging.warning(f"Validation Warning: Global 'url' exceeds {MAX_URL_CHARS} characters. It will be truncated when sending.")
    if new_state.pushover.get("url_title") and len(new_state.pushover["url_title"]) > MAX_URL_TITLE_CHARS:
        logging.warning(f"Validation Warning: Global 'url_title' exceeds {MAX_URL_TITLE_CHARS} characters. It will be truncated when sending.")

    for key, config in routes_json.items():
        if not isinstance(config, dict): continue
        match_type = config.get("match", "to").lower()
        if match_type not in ("to", "from", "both"): continue

        method = config.get("method", "pushover")
        route_config = {"method": method}

        if method == "smarthost":
            route_config["smarthost_alias"] = config.get("smarthost_alias")
            if "force_plaintext" in config: route_config["force_plaintext"] = get_bool(config["force_plaintext"])
            if "disable_attachments" in config: route_config["disable_attachments"] = get_bool(config["disable_attachments"])
        else:
            user_key = config.get("user")
            user_key = _resolve_tok(user_key, flat_vault["user"], flat_vault["app"]) if user_key else new_state.pushover.get("user")

            app_token = _resolve_tok(config.get("token"), flat_vault["app"])

            if not user_key or not app_token: continue

            route_config["user"] = user_key
            route_config["token"] = app_token

            if "force_plaintext" in config: route_config["force_plaintext"] = get_bool(config["force_plaintext"])
            if "attachments" in config: route_config["attachments"] = get_bool(config["attachments"])

            for string_param in ["device", "sound", "url", "url_title", "tags"]:
                val = config.get(string_param, new_state.pushover.get(string_param))
                if val and str(val).strip(): route_config[string_param] = str(val).strip()

            if "url" in route_config and len(route_config["url"]) > MAX_URL_CHARS:
                logging.warning(f"Validation Warning: Route '{key}' 'url' exceeds {MAX_URL_CHARS} characters. It will be truncated when sending.")
            if "url_title" in route_config and len(route_config["url_title"]) > MAX_URL_TITLE_CHARS:
                logging.warning(f"Validation Warning: Route '{key}' 'url_title' exceeds {MAX_URL_TITLE_CHARS} characters. It will be truncated when sending.")

            for int_param in ["priority", "ttl", "retry", "expire"]:
                val = config.get(int_param, new_state.pushover.get(int_param))
                if val is not None and str(val).strip():
                    try:
                        parsed_val = int(val)
                        if int_param == "priority" and not (-2 <= parsed_val <= 2): continue
                        if int_param == "retry" and parsed_val < 30: continue
                        if int_param == "expire" and parsed_val > 10800: continue
                        route_config[int_param] = parsed_val
                    except ValueError: pass

            if route_config.get("priority") == 2 and ("retry" not in route_config or "expire" not in route_config): continue

        is_regex = False
        email_key = key

        if key.lower().startswith("regex:"):
            is_regex = True
            pattern_str = key[6:].strip()
            try: compiled_pattern = re.compile(pattern_str, re.IGNORECASE)
            except re.error: continue
        else:
            email_key = key.lower()

        if is_regex:
            if match_type in ("to", "both"): new_state.regex_mappings["to"].append((compiled_pattern, route_config))
            if match_type in ("from", "both"): new_state.regex_mappings["from"].append((compiled_pattern, route_config))
        else:
            if match_type in ("to", "both"): new_state.mappings["to"][email_key] = route_config
            if match_type in ("from", "both"): new_state.mappings["from"][email_key] = route_config

    has_mappings = bool(new_state.mappings["to"] or new_state.mappings["from"] or new_state.regex_mappings["to"] or new_state.regex_mappings["from"])

    if not has_mappings:
        if new_state.smtp["default_route"] == "pushover" and not (new_state.pushover.get("user") and new_state.pushover.get("token")):
            raise ValueError("No valid email routing matrices survived validation, and no global Pushover catch-all is defined.")
        elif new_state.smtp["default_route"] == "smarthost" and not new_state.smarthost["globals"].get("alias"):
            raise ValueError("No valid email routing matrices survived validation, and no global Smarthost catch-all is defined.")

    return new_state

def load_config(is_reload=False):
    raw_env = os.environ.get("GATEWAY_CONFIG")
    if not raw_env:
        logging.error("Environment variable GATEWAY_CONFIG is not set.")
        if not is_reload: exit(1)
        return None

    file_path = os.path.normpath(os.path.join(SCRIPT_DIR, raw_env.strip()))
    conf_dir = os.path.dirname(file_path) or "."
    if not os.path.isfile(file_path):
        logging.error(f"GATEWAY_CONFIG must point to a valid file path. File not found: {file_path}")
        if not is_reload: exit(1)
        return None

    try:
        try:
            with open(file_path, 'r') as f: config_str = f.read()
            config_str = re.sub(r'(^|\s)/\*.*?\*/', r'\1', config_str, flags=re.DOTALL)
            config_str = re.sub(r'(^|\s)(//|#).*', r'\1', config_str)
            config_root = json.loads(config_str)
        except Exception as e:
            raise ValueError(f"Config JSON syntax error: {e}")

        vault_file_path = config_root.get("smtp", {}).get("vault_file")
        if not vault_file_path: vault_file_path = os.path.join(conf_dir, "vault.json")
        else: vault_file_path = os.path.normpath(os.path.join(conf_dir, vault_file_path))

        try:
            vault_data = load_vault_safe(vault_file_path)
        except Exception as e:
            raise ValueError(f"Vault JSON syntax error: {e}")

        new_state = _build_and_validate_state(config_root, vault_data, file_path, vault_file_path)

        max_backups = new_state.smtp.get("max_backups", 50)
        save_unified_backup_if_changed(conf_dir, config_root, vault_data, max_backups)

        return new_state

    except ValueError as ve:
        if is_reload:
            logging.error(f"Configuration reload rejected: {ve}. Retaining active memory state.")
            return None
        else:
            logging.critical(f"Poisoned boot detected: {ve}")

            unified_backups = get_unified_backups(conf_dir)
            if not unified_backups:
                logging.error("No valid unified configuration backups found on disk. Aborting boot.")
                exit(1)

            for u_backup in unified_backups:
                logging.warning(f"Attempting fallback to atomic backup: {os.path.basename(u_backup)}")
                try:
                    backup_data = load_clean_json(u_backup)
                    c_root = backup_data.get("config", {})
                    v_data = backup_data.get("vault", {"app": {}, "user": {}, "smarthost": {}})

                    v_path = c_root.get("smtp", {}).get("vault_file")
                    if not v_path: v_path = os.path.join(conf_dir, "vault.json")
                    else: v_path = os.path.normpath(os.path.join(conf_dir, v_path))

                    fallback_state = _build_and_validate_state(c_root, v_data, file_path, v_path)
                    logging.warning(f"Successfully rescued boot state using atomic backup: {os.path.basename(u_backup)}")
                    return fallback_state
                except Exception as b_err:
                    logging.warning(f"Backup {os.path.basename(u_backup)} failed validation: {b_err}. Trying next backup...")
                    continue

            logging.critical("All unified configuration backups failed validation. Aborting boot.")
            exit(1)
