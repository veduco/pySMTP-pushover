import json
import os

def load_clean_json(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_json(filepath, data):
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def load_vault_safe(vault_path):
    v = load_clean_json(vault_path)
    if "app" not in v: v["app"] = {}
    if "user" not in v: v["user"] = {}
    if "smarthost" not in v: v["smarthost"] = {}
    return v
