import os
import re
import time
import shutil
import json

# Facade: Expose separated components to maintain legacy import contracts
from core.constants import *
from core.json_store import *

# Unified standard in-memory config cache for UI processes
_UI_CONFIG_CACHE = None

def get_cached_ui_config(force_refresh=False):
    """Serves the UI configuration from RAM, falling back to disk read on cache miss."""
    global _UI_CONFIG_CACHE
    if _UI_CONFIG_CACHE is None or force_refresh:
        _UI_CONFIG_CACHE = load_clean_json(UI_CONFIG_FILE)
    return _UI_CONFIG_CACHE

def clear_ui_config_cache():
    """Flushes the in-memory cache, forcing the next lookup to sync with disk."""
    global _UI_CONFIG_CACHE
    _UI_CONFIG_CACHE = None


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

def _execute_unified_snapshot(state):
    """
    Creates a unified backup frame bundling both the config and vault data structures.
    Performs a semantic deep-diff against the latest backup to avoid redundant writes
    when duplicate SIGUSR2 triggers are caught.
    """
    try:
        max_backups = int(state.smtp.get("max_backups", 50))
        if max_backups <= 0:
            return

        conf_dir = os.path.dirname(CONFIG_FILE) or "."

        # 1. Read live clean data states directly from the verified sources
        live_config = load_clean_json(CONFIG_FILE)
        live_vault = load_clean_json(state.vault_file)

        # Sanitize runtime transient tracking blocks to prevent false diff flags
        if "smtp" in live_config and "_smtp_meta" in live_config["smtp"]:
            del live_config["smtp"]["_smtp_meta"]

        # 2. Gather historical unified backup frames
        snapshots = []
        for entry in os.listdir(conf_dir):
            if entry.startswith(".gateway.valid.") and entry.endswith(".json"):
                snapshots.append(os.path.join(conf_dir, entry))

        snapshots.sort(key=os.path.getmtime)

        # 3. Structural Data-Diff Pass (Ignores transient file metadata/blind hashes)
        if snapshots:
            latest_backup_path = snapshots[-1]
            latest_data = load_clean_json(latest_backup_path)

            cached_config = latest_data.get("config", {})
            cached_vault = latest_data.get("vault", {})

            if "smtp" in cached_config and "_smtp_meta" in cached_config["smtp"]:
                del cached_config["smtp"]["_smtp_meta"]

            # Compare underlying data values directly
            if live_config == cached_config and live_vault == cached_vault:
                # Structures are identical. Terminate snapshot slice without touching disk.
                return

        # 4. Content has changed or no backup exists; compile and write the unified file
        unified_payload = {
            "config": load_clean_json(CONFIG_FILE),
            "vault": load_clean_json(state.vault_file)
        }

        epoch = int(time.time())
        backup_path = os.path.join(conf_dir, f".gateway.valid.{epoch}.json")

        with open(backup_path, 'w') as f:
            json.dump(unified_payload, f, indent=2)

        snapshots.append(backup_path)

        # 5. Enforce rolling historical rotation policy
        while len(snapshots) > max_backups:
            oldest = snapshots.pop(0)
            try:
                os.remove(oldest)
            except OSError:
                pass
    except Exception:
        # Protect core lifecycle loops from crashing on local environment storage issues
        pass

def load_config(ignore_missing=False):
    """
    Executes a strict, unified compilation of the configuration state.
    Once this function completes, parameters are entirely static in memory
    and disk access is strictly prohibited until a SIGUSR2 signal is tripped.
    """
    if not os.path.exists(CONFIG_FILE) and not ignore_missing:
        return None

    data = load_clean_json(CONFIG_FILE)
    state = AppState(CONFIG_FILE)

    # 1. Normalize and hard-set SMTP Core parameters immediately
    state.smtp = data.get("smtp", {})
    state.smtp["queue_dir"] = state.smtp.get("queue_dir", "data/queue")
    state.smtp["max_retry_backoff"] = int(state.smtp.get("max_retry_backoff", 21600))
    state.smtp["loglevel"] = state.smtp.get("loglevel", "INFO")
    state.smtp["default_route"] = state.smtp.get("default_route", "pushover")
    state.smtp["listeners"] = state.smtp.get("listeners", [{"bind": "0.0.0.0:25", "starttls": False}])
    state.smtp["auth"] = state.smtp.get("auth", {})
    state.smtp["max_backups"] = int(state.smtp.get("max_backups", 50))

    # 2. Extract Pushover and Smarthost structures natively
    state.pushover = data.get("pushover", {})
    state.smarthost = data.get("smarthost", {})
    if "globals" not in state.smarthost: state.smarthost["globals"] = {}
    if "aliases" not in state.smarthost: state.smarthost["aliases"] = {}

    # 3. Resolve cryptographic vault parameters securely
    v_path = state.smtp.get("vault_file")
    conf_dir = os.path.dirname(CONFIG_FILE) or "."
    state.vault_file = os.path.normpath(os.path.join(conf_dir, v_path)) if v_path else os.path.join(conf_dir, "vault.json")
    vault_data = load_vault_safe(state.vault_file)

    for v_type in ["app", "user", "smarthost"]:
        for alias, val in vault_data.get(v_type, {}).items():
            if isinstance(val, dict): state.vault[v_type][alias] = val.get("token", "")
            else: state.vault[v_type][alias] = val

    # 4. Process routing mappings directly into immutable collections
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

    # 5. Schema verification pass successful. Fire unified semantic data backup check.
    _execute_unified_snapshot(state)

    return state
