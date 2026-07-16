import re
import time
import hashlib
import os
from core.config import load_clean_json, save_json, load_vault_safe
from frontend.utils import get_active_config_path

def process_legacy_config(config):
    changed = False
    if "routes" not in config:
        config["routes"] = {}
        po = config.get("pushover", {})
        to_del = []
        for k, v in po.items():
            if k not in ["user", "token", "device", "sound", "url", "url_title", "tags", "priority", "ttl", "retry", "expire", "attachments", "force_plaintext", "disable_persistence"] and isinstance(v, dict):
                v["method"] = "pushover"; config["routes"][k] = v; to_del.append(k)
        for k in to_del: del po[k]
        changed = True

    if "disable_persistence" in config.get("pushover", {}):
        if "smtp" not in config: config["smtp"] = {}
        config["smtp"]["disable_persistence"] = config["pushover"]["disable_persistence"]
        del config["pushover"]["disable_persistence"]
        changed = True

    if "smarthost" not in config: config["smarthost"] = {"aliases": {}, "globals": {}}; changed = True
    if "smtp" not in config: config["smtp"] = {}
    if "default_route" not in config["smtp"]: config["smtp"]["default_route"] = "pushover"; changed = True

    auth_block = config.get("smtp", {}).get("auth", {})
    meta_block = config.get("smtp", {}).get("_smtp_meta", {})
    for user, pwd in list(auth_block.items()):
        if not pwd.startswith("$") and not re.match(r'^[a-fA-F0-9]{64}$', pwd):
            auth_block[user] = hashlib.sha256(pwd.encode('utf-8')).hexdigest()
            if user not in meta_block: meta_block[user] = int(time.time())
            changed = True

    if changed:
        config["smtp"]["auth"] = auth_block
        config["smtp"]["_smtp_meta"] = meta_block
    return config, changed

def save_normalized_config(parsed, vault_parsed=None):
    old_config = load_clean_json(get_active_config_path())

    api_secret = parsed.get("smtp", {}).get("api", {}).get("secret", "")
    if not api_secret:
        old_secret = old_config.get("smtp", {}).get("api", {}).get("secret", "")
        if "smtp" in parsed and "api" in parsed["smtp"]:
            parsed["smtp"]["api"]["secret"] = old_secret

    auth_block = parsed.get("smtp", {}).get("auth", {})
    meta_block = parsed.get("_smtp_meta", {})
    for user, pwd in list(auth_block.items()):
        if str(pwd).startswith("RAW:"):
            auth_block[user] = hashlib.sha256(pwd[4:].encode('utf-8')).hexdigest()
            if user not in meta_block: meta_block[user] = int(time.time())
    parsed["smtp"]["_smtp_meta"] = meta_block
    if "_smtp_meta" in parsed: del parsed["_smtp_meta"]
    save_json(get_active_config_path(), parsed)

    if vault_parsed:
        v_path = old_config.get("smtp", {}).get("vault_file")
        v_path = os.path.normpath(os.path.join(os.path.dirname(get_active_config_path()) or ".", v_path)) if v_path else os.path.join(os.path.dirname(get_active_config_path()) or ".", "vault.json")
        vault_data = load_vault_safe(v_path)
        new_vault = {"app": {}, "user": {}, "smarthost": {}}
        for vtype in ["app", "user"]:
            for item in vault_parsed.get(vtype, []):
                name = item["name"]; tok = item["token"]; epoch = item["epoch"]
                if not tok: tok = vault_data[vtype].get(name, {}).get("token", "")
                new_vault[vtype][name] = {"token": tok, "epoch": epoch}
        for alias, tok in vault_parsed.get("smarthost", {}).items():
            if not tok: tok = vault_data.get("smarthost", {}).get(alias, {}).get("token", "")
            new_vault["smarthost"][alias] = {"token": tok, "epoch": int(time.time())}
        save_json(v_path, new_vault)

    old_smtp = old_config.get("smtp", {})
    new_smtp = parsed.get("smtp", {})
    if "_smtp_meta" in old_smtp: del old_smtp["_smtp_meta"]
    if "_smtp_meta" in new_smtp: del new_smtp["_smtp_meta"]
    return old_smtp != new_smtp
