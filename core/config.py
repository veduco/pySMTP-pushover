import os
import re
import time
import shutil
import json
import hashlib

# Facade: Expose separated components to maintain legacy import contracts
from core.constants import *
from core.json_store import *

# Unified standard in-memory config cache for UI processes
_UI_CONFIG_CACHE = None

SCHEMA_FILE = os.path.join(SCRIPT_DIR, "schema.json")

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
        self.raw_config = {}
        self.raw_vault = {}

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

    # Load Source of Truth schema to inject missing default structures
    schema = load_clean_json(SCHEMA_FILE).get("gateway_config", {})

    data = load_clean_json(CONFIG_FILE)
    state = AppState(CONFIG_FILE)

    # Store the pristine disk read immediately
    state.raw_config = data

    # 1. Normalize and hard-set SMTP Core parameters immediately from Schema
    state.smtp = data.get("smtp", {})
    for k, v in schema.get("smtp", {}).items():
        state.smtp.setdefault(k, v)

    # 2. Extract Pushover and Smarthost structures natively from Schema
    state.pushover = data.get("pushover", {})
    for k, v in schema.get("pushover", {}).items():
        state.pushover.setdefault(k, v)

    state.smarthost = data.get("smarthost", {})
    state.smarthost.setdefault("globals", schema.get("smarthost", {}).get("globals", {}))
    state.smarthost.setdefault("aliases", schema.get("smarthost", {}).get("aliases", {}))

    # 3. Resolve cryptographic vault parameters securely
    v_path = state.smtp.get("vault_file")
    conf_dir = os.path.dirname(CONFIG_FILE) or "."
    state.vault_file = os.path.normpath(os.path.join(conf_dir, v_path)) if v_path else os.path.join(conf_dir, "vault.json")
    vault_data = load_vault_safe(state.vault_file)

    # Store the pristine vault read into memory immediately
    state.raw_vault = vault_data

    for v_type in ["app", "user", "smarthost"]:
        for alias, val in vault_data.get(v_type, {}).items():
            if isinstance(val, dict): state.vault[v_type][alias] = val.get("token", "")
            else: state.vault[v_type][alias] = val

    # 4. Process routing mappings directly into immutable collections
    routes = data.get("routes", {})
    for key, route in routes.items():
        match_type = route.get("match", "to").lower()
        method = route.get("method", "pushover").lower()

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

    # 5. Schema verification pass successful. Fire unified semantic data backup check.
    _execute_unified_snapshot(state)

    return state

def save_unified_config(config_path, new_config=None, new_vault=None):
    """
    Safely normalizes JSON payloads, hashes secrets securely, preserves existing API keys,
    and commits config/vault structures to disk while protecting vault alias strings.
    Returns a boolean indicating if SMTP listeners were modified (useful for hot-reloads).
    """
    listeners_changed = False
    old_config = load_clean_json(config_path)

    if new_config:
        # 1. API Secret Preservation
        api_secret = new_config.get("smtp", {}).get("api", {}).get("secret", "")
        if not api_secret:
            old_secret = old_config.get("smtp", {}).get("api", {}).get("secret", "")
            if "smtp" in new_config and "api" in new_config["smtp"]:
                new_config["smtp"]["api"]["secret"] = old_secret

        # 2. Protect Global Pushover Aliases from Password Mask Polution
        for field in ["token", "user"]:
            new_val = new_config.get("pushover", {}).get(field, "")
            # If the value comes back as masked dots or empty, retain the old string alias name
            if new_val == "••••••••" or not new_val:
                if "pushover" in old_config and field in old_config["pushover"]:
                    if "pushover" in new_config:
                        new_config["pushover"][field] = old_config["pushover"][field]

        # 3. SMTP Auth Secret Hashing
        auth_block = new_config.get("smtp", {}).get("auth", {})
        meta_block = new_config.get("_smtp_meta", {})
        for user, pwd in list(auth_block.items()):
            if str(pwd).startswith("RAW:"):
                auth_block[user] = hashlib.sha256(pwd[4:].encode('utf-8')).hexdigest()
                if user not in meta_block:
                    meta_block[user] = int(time.time())

        if "smtp" not in new_config:
            new_config["smtp"] = {}

        new_config["smtp"]["_smtp_meta"] = meta_block
        if "_smtp_meta" in new_config:
            del new_config["_smtp_meta"]

        # 4. Evaluate critical listener diffs for signal dispatch
        old_smtp = old_config.get("smtp", {})
        if "listeners" in old_smtp and "listeners" in new_config["smtp"]:
            if old_smtp["listeners"] != new_config["smtp"]["listeners"]:
                listeners_changed = True
        else:
            listeners_changed = True

        save_json(config_path, new_config)

    if new_vault:
        # Resolve dynamic Vault Path boundary
        v_path = old_config.get("smtp", {}).get("vault_file")
        v_path = os.path.normpath(os.path.join(os.path.dirname(config_path) or ".", v_path)) if v_path else os.path.join(os.path.dirname(config_path) or ".", "vault.json")

        vault_data = load_vault_safe(v_path)
        normalized_vault = {"app": {}, "user": {}, "smarthost": {}}

        for vtype in ["app", "user"]:
            if isinstance(new_vault.get(vtype), list):
                for item in new_vault.get(vtype, []):
                    name = item.get("name")
                    tok = item.get("token")
                    epoch = item.get("epoch", int(time.time()))
                    # Avoid capturing dummy mask constraints into the secure database file
                    if not tok or tok == "••••••••":
                        tok = vault_data.get(vtype, {}).get(name, {}).get("token", "")
                    normalized_vault[vtype][name] = {"token": tok, "epoch": epoch}
            else:
                normalized_vault[vtype] = new_vault.get(vtype, {})

        for alias, tok in new_vault.get("smarthost", {}).items():
            if not tok or tok == "••••••••":
                tok = vault_data.get("smarthost", {}).get(alias, {}).get("token", "")
            normalized_vault["smarthost"][alias] = {"token": tok, "epoch": int(time.time())}

        save_json(v_path, normalized_vault)

    return listeners_changed
