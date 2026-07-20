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
    for vtype in ["app", "user", "smarthost"]:
        if vtype not in v or not isinstance(v[vtype], dict):
            v[vtype] = {}
    return v
