import os
import re
import time
import shutil
import json
import hashlib
import asyncio
import logging

# Facade: Expose separated components to maintain legacy import contracts
from core.constants import *
from core.json_store import *
from core.utils import HttpClientPool, get_deterministic_hash

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

    def resolve_delivery_context(self, method: str, overrides: dict = None) -> dict:
        """
        Centralized resolver for outbound configurations. Dynamically evaluates
        route-specific overrides against global fallbacks and secure vault bindings.
        """
        if overrides is None: overrides = {}
        ctx = {}

        if method == "pushover":
            # 1. Resolve Identity and Vault Tokens dynamically
            t_val = overrides.get("token")
            if not t_val or t_val == "••••••••": t_val = self.pushover.get("token", "")
            ctx["token"] = self.vault.get("app", {}).get(t_val, t_val)

            u_val = overrides.get("user")
            if not u_val or u_val == "••••••••": u_val = self.pushover.get("user", "")
            ctx["user"] = self.vault.get("user", {}).get(u_val, u_val)

            # 2. Extract and sanitize Pushover API parameters
            for p in ["device", "sound", "url", "url_title", "priority", "ttl", "tags", "retry", "expire"]:
                val = overrides.get(p)
                if val is None or val == "":
                    val = self.pushover.get(p)
                if val is not None and val != "":
                    if p == "url": val = str(val)[:MAX_URL_CHARS]
                    if p == "url_title": val = str(val)[:MAX_URL_TITLE_CHARS]
                    ctx[p] = val

            # 3. Resolve Structural Delivery Flags
            fp = overrides.get("force_plaintext")
            if fp is None: fp = self.pushover.get("force_plaintext", False)
            ctx["force_plaintext"] = fp

            route_disable_att = overrides.get("disable_attachments")
            if route_disable_att is not None:
                ctx["attachments"] = not route_disable_att
            else:
                ctx["attachments"] = self.pushover.get("attachments", True)

        elif method == "smarthost":
            # 1. Resolve Smarthost Target
            alias = overrides.get("smarthost_alias")
            sh_conf = self.smarthost.get("aliases", {}).get(alias)

            if not sh_conf:
                alias = self.smarthost.get("globals", {}).get("alias")
                sh_conf = self.smarthost.get("aliases", {}).get(alias, {})

            ctx["_resolved_alias"] = alias
            ctx["is_valid"] = bool(sh_conf)

            if sh_conf:
                # Merge Base Configuration
                ctx.update(sh_conf)

                # Bind Vault Credentials
                if sh_conf.get("auth"):
                    ctx["password"] = self.vault.get("smarthost", {}).get(alias, "")

                # 2. Resolve Structural Delivery Flags
                g_smarthost = self.smarthost.get("globals", {})

                fp = overrides.get("force_plaintext")
                if fp is None: fp = sh_conf.get("force_plaintext")
                if fp is None: fp = g_smarthost.get("force_plaintext", False)
                ctx["force_plaintext"] = fp

                route_disable_att = overrides.get("disable_attachments")
                if route_disable_att is not None:
                    ctx["attachments"] = not route_disable_att
                else:
                    sh_disable_att = sh_conf.get("disable_attachments")
                    if sh_disable_att is not None:
                        ctx["attachments"] = not sh_disable_att
                    else:
                        ctx["attachments"] = g_smarthost.get("attachments", True)

        return ctx

def _execute_unified_snapshot(state, config_path):
    """
    Creates a unified backup frame bundling both the config and vault data structures.
    Performs a semantic deep-diff against the latest backup to avoid redundant writes
    when duplicate SIGUSR2 triggers are caught.
    """
    try:
        max_backups = int(state.smtp.get("max_backups", 50))
        if max_backups <= 0:
            return

        conf_dir = os.path.dirname(config_path) or "."

        # 1. Read live clean data states directly from the verified sources
        live_config = load_clean_json(config_path)
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
            "config": load_clean_json(config_path),
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

def load_config(ignore_missing=False, config_path=None):
    """
    Executes a strict, unified compilation of the configuration state.
    Once this function completes, parameters are entirely static in memory
    and disk access is strictly prohibited until a SIGUSR2 signal is tripped.
    """
    target_path = config_path if config_path else CONFIG_FILE

    if not os.path.exists(target_path) and not ignore_missing:
        return None

    # Load Source of Truth schema to inject missing default structures
    schema = load_clean_json(SCHEMA_FILE).get("gateway_config", {})

    data = load_clean_json(target_path)
    state = AppState(target_path)

    # Store the pristine disk read immediately
    state.raw_config = data

    # 1. Normalize and hard-set SMTP Core parameters immediately from Schema
    state.smtp = data.get("smtp", {})
    for k, v in schema.get("smtp", {}).items():
        state.smtp.setdefault(k, v)

    # Inject deduplication defaults natively from parsing block schema
    state.smtp.setdefault("dedupe_enabled", False)
    state.smtp.setdefault("dedupe_window", "10m")
    state.smtp.setdefault("dedupe_keys", ["sender", "match_reason", "message"])

    # 2. Extract Pushover and Smarthost structures natively from Schema
    state.pushover = data.get("pushover", {})
    for k, v in schema.get("pushover", {}).items():
        state.pushover.setdefault(k, v)

    state.smarthost = data.get("smarthost", {})
    state.smarthost.setdefault("globals", schema.get("smarthost", {}).get("globals", {}))
    state.smarthost.setdefault("aliases", schema.get("smarthost", {}).get("aliases", {}))

    # 3. Resolve cryptographic vault parameters securely
    v_path = state.smtp.get("vault_file")
    conf_dir = os.path.dirname(target_path) or "."
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
    _execute_unified_snapshot(state, target_path)

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

class ConfigOrchestrator:
    """
    Centralized controller for configuration reads, commits, and systemic hot-reload signaling.
    Works seamlessly across local filesystem mapping and remote API connectivity paradigms.
    """
    def __init__(self, ui_config: dict, http_client=None):
        self.ui_config = ui_config
        self.bmode = ui_config.get("backend_mode", "local")
        self.primary_host = ui_config.get("primary_host", "")
        self.remote_hosts = ui_config.get("remote_hosts", [])
        self.remote_secrets = ui_config.get("remote_secrets", [])

        self.http_client = http_client
        self.timeout = 5.0
        self.active_path = self.ui_config.get("local_config_path") or CONFIG_FILE

    def trigger_local_backend_reload(self):
        import signal
        if not os.path.exists(SMTP_PID_FILE): return
        try:
            with open(SMTP_PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGUSR2)
        except Exception: pass

    @staticmethod
    def parse_duration_to_seconds(duration_str: str) -> int:
        if not duration_str: return 600
        pattern = re.compile(r'^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$')
        match = pattern.match(str(duration_str).strip().lower())
        if not match: return 600
        hours = int(match.group(1)) if match.group(1) else 0
        minutes = int(match.group(2)) if match.group(2) else 0
        seconds = int(match.group(3)) if match.group(3) else 0
        total = (hours * 3600) + (minutes * 60) + seconds
        return total if total > 0 else 600

    def _get_host_secret(self, host_cfg):
        """Resolves the last known working secret via deterministic hash mapping."""
        target_hash = host_cfg.get("last_secret_hash")
        if not self.remote_secrets: return ""
        if not target_hash: return self.remote_secrets[0]

        for s in self.remote_secrets:
            if get_deterministic_hash({"secret": s}) == target_hash:
                return s
        return self.remote_secrets[0]

    async def get_config(self):
        config, vault_data, smtp_meta = {}, {"app": {}, "user": {}, "smarthost": {}}, {}
        config_ok, current_hash = False, ""

        if self.bmode == "remote":
            primary_cfg = next((h for h in self.remote_hosts if f"{h.get('host')}:{h.get('port')}" == self.primary_host), None)
            if primary_cfg:
                client = self.http_client or HttpClientPool.get_client("frontend", verify_tls=primary_cfg.get("verify_tls", True))
                secret = self._get_host_secret(primary_cfg)
                url = f"https://{primary_cfg['host']}:{primary_cfg['port']}/api/config"
                try:
                    r = await client.get(url, headers={"Authorization": f"Bearer {secret}"}, timeout=self.timeout)
                    if r.status_code == 200:
                        data = r.json()
                        config = data.get("config", {})
                        vault_data = data.get("vault", {})
                        smtp_meta = data.get("smtp_meta", {})
                        current_hash = data.get("config_hash", "")

                        # Sync status back to success if we connected
                        primary_cfg["sync_status"] = "success"
                        primary_cfg["last_secret_hash"] = get_deterministic_hash({"secret": secret})
                        save_json(UI_CONFIG_FILE, self.ui_config)
                        clear_ui_config_cache()

                        config_ok = True
                except Exception as e:
                    logging.error(f"Failed to fetch config from primary host {url}: {e}")
        else:
            try:
                parsed = load_config(ignore_missing=True, config_path=self.active_path)
                if parsed:
                    config = load_clean_json(self.active_path)
                    vault_data = load_vault_safe(parsed.vault_file)
                    smtp_meta = config.get("smtp", {}).get("_smtp_meta", {})
                    current_hash = get_deterministic_hash({"config": config, "vault": vault_data})
                    config_ok = True
            except Exception: pass

        return config, vault_data, smtp_meta, config_ok, current_hash

    async def _push_to_host(self, host_cfg, payload, expected_hash):
        url = f"https://{host_cfg['host']}:{host_cfg['port']}/api/save"
        client = self.http_client or HttpClientPool.get_client("frontend", verify_tls=host_cfg.get("verify_tls", True))

        # Attempt loop: Try last known good secret, then fallback to newest secret if unauthorized
        secrets_to_try = [self._get_host_secret(host_cfg)]
        if self.remote_secrets and self.remote_secrets[0] not in secrets_to_try:
            secrets_to_try.append(self.remote_secrets[0])

        for secret in secrets_to_try:
            try:
                r = await client.post(url, json=payload, headers={"Authorization": f"Bearer {secret}"}, timeout=self.timeout)
                if r.status_code == 200:
                    returned_hash = r.json().get("config_hash", "")
                    if returned_hash == expected_hash:
                        host_cfg["sync_status"] = "success"
                        host_cfg["expected_hash"] = expected_hash
                        host_cfg["last_secret_hash"] = get_deterministic_hash({"secret": secret})
                        return True
            except Exception: pass

        host_cfg["sync_status"] = "failed"
        host_cfg["expected_hash"] = expected_hash
        return False

    async def fan_out_config(self, parsed_config, vault_parsed, expected_hash, specific_hosts=None):
        """Pushes configurations to remote instances and handles granular host synchronization updates."""
        payload = {"config": parsed_config}
        if vault_parsed: payload["vault"] = vault_parsed

        targets = specific_hosts if specific_hosts is not None else self.remote_hosts
        tasks = [self._push_to_host(h, payload, expected_hash) for h in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Purge unused secrets to reduce memory bloat securely
        active_hashes = {h.get("last_secret_hash") for h in self.remote_hosts}
        new_secrets = []
        for s in self.remote_secrets:
            if get_deterministic_hash({"secret": s}) in active_hashes or (self.remote_secrets and s == self.remote_secrets[0]):
                new_secrets.append(s)
        self.ui_config["remote_secrets"] = new_secrets

        save_json(UI_CONFIG_FILE, self.ui_config)
        clear_ui_config_cache()
        return all(res is True for res in results)

    async def save_config(self, parsed_config, vault_parsed=None):
        if self.bmode == "remote":
            expected_hash = get_deterministic_hash({"config": parsed_config, "vault": vault_parsed or {}})
            success = await self.fan_out_config(parsed_config, vault_parsed, expected_hash)
            return "Configuration synchronized to all nodes." if success else "Some hosts failed to sync. Background retries have begun."
        else:
            save_unified_config(self.active_path, new_config=parsed_config, new_vault=vault_parsed)
            self.trigger_local_backend_reload()
            return "Configuration successfully synchronized with the local gateway daemon."
