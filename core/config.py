import os
import re

# Facade: Expose separated components to maintain legacy import contracts
from core.constants import *
from core.json_store import *

class AppState:
    def __init__(self, config_file):
        self.config_file = config_file
        self.smtp = {}
        self.pushover = {}
        self.smarthost = {}
        self.mappings = {"to": {}, "from": {}}
        self.regex_mappings = {"to": [], "from": []}
        self.vault = {"app": {}, "user": {}, "smarthost": {}}
        self.vault_file = None

def load_config(ignore_missing=False):
    if not os.path.exists(CONFIG_FILE) and not ignore_missing:
        return None

    data = load_clean_json(CONFIG_FILE)
    state = AppState(CONFIG_FILE)

    state.smtp = data.get("smtp", {})
    if "queue_dir" not in state.smtp: state.smtp["queue_dir"] = "data/queue"
    if "max_retry_backoff" not in state.smtp: state.smtp["max_retry_backoff"] = 21600
    if "loglevel" not in state.smtp: state.smtp["loglevel"] = "INFO"
    if "default_route" not in state.smtp: state.smtp["default_route"] = "pushover"
    if "listeners" not in state.smtp: state.smtp["listeners"] = [{"bind": "0.0.0.0:25", "starttls": False}]

    state.pushover = data.get("pushover", {})
    state.smarthost = data.get("smarthost", {})
    if "globals" not in state.smarthost: state.smarthost["globals"] = {}
    if "aliases" not in state.smarthost: state.smarthost["aliases"] = {}

    v_path = state.smtp.get("vault_file")
    conf_dir = os.path.dirname(CONFIG_FILE) or "."
    state.vault_file = os.path.normpath(os.path.join(conf_dir, v_path)) if v_path else os.path.join(conf_dir, "vault.json")
    vault_data = load_vault_safe(state.vault_file)

    for v_type in ["app", "user", "smarthost"]:
        for alias, val in vault_data.get(v_type, {}).items():
            if isinstance(val, dict): state.vault[v_type][alias] = val.get("token", "")
            else: state.vault[v_type][alias] = val

    routes = data.get("routes", {})
    for key, route in routes.items():
        match_type = route.get("match", "to").lower()
        method = route.get("method", "pushover").lower()

        if method == "pushover":
            tok = route.get("token")
            if tok in state.vault["app"]: route["token"] = state.vault["app"][tok]
            usr = route.get("user")
            if usr in state.vault["user"]: route["user"] = state.vault["user"][usr]

        is_regex = key.lower().startswith("regex:")
        actual_key = key[6:] if is_regex else key.lower()

        if is_regex:
            try:
                pattern = re.compile(actual_key, re.IGNORECASE)
                if match_type in ["to", "both"]: state.regex_mappings["to"].append((pattern, route))
                if match_type in ["from", "both"]: state.regex_mappings["from"].append((pattern, route))
            except Exception: pass
        else:
            if match_type in ["to", "both"]: state.mappings["to"][actual_key] = route
            if match_type in ["from", "both"]: state.mappings["from"][actual_key] = route

    if state.pushover.get("token") in state.vault["app"]: state.pushover["token"] = state.vault["app"][state.pushover["token"]]
    if state.pushover.get("user") in state.vault["user"]: state.pushover["user"] = state.vault["user"][state.pushover["user"]]

    return state
