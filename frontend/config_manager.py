import httpx
from frontend.utils import get_active_config_path, trigger_local_backend_reload
from core.config import load_clean_json, load_vault_safe, load_config, save_unified_config

class ConfigManager:
    def __init__(self, ui_config: dict):
        self.ui_config = ui_config
        self.bmode = ui_config.get("backend_mode", "local")
        self.url = ui_config.get("remote_url", "")
        self.sec = ui_config.get("remote_secret", "")
        self.verify_tls = ui_config.get("remote_verify_tls", False)

    async def get_config(self):
        """Fetches the configuration state from either the local disk or remote gateway."""
        config = {}
        vault_data = {"app": {}, "user": {}, "smarthost": {}}
        smtp_meta = {}
        config_ok = False

        if self.bmode == "remote":
            try:
                async with httpx.AsyncClient(verify=self.verify_tls, timeout=3.0) as client:
                    r = await client.get(
                        f"{self.url.rstrip('/')}/api/config",
                        headers={"Authorization": f"Bearer {self.sec}"}
                    )
                if r.status_code == 200:
                    data = r.json()
                    config = data.get("config", {})
                    vault_data = data.get("vault", {})
                    smtp_meta = data.get("smtp_meta", {})
                    config_ok = True
            except Exception:
                pass
        else:
            try:
                parsed = load_config(ignore_missing=True)
                if parsed:
                    config = load_clean_json(get_active_config_path())
                    vault_data = load_vault_safe(parsed.vault_file)
                    smtp_meta = config.get("smtp", {}).get("_smtp_meta", {})
                    config_ok = True
            except Exception:
                pass

        return config, vault_data, smtp_meta, config_ok

    async def save_config(self, parsed_config, vault_parsed=None):
        """Pushes the updated configuration payload to the appropriate local/remote target."""
        if self.bmode == "remote":
            payload = {"config": parsed_config}
            if vault_parsed:
                payload["vault"] = vault_parsed

            async with httpx.AsyncClient(verify=self.verify_tls, timeout=5.0) as client:
                await client.post(
                    f"{self.url.rstrip('/')}/api/save",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.sec}"}
                )
                await client.post(
                    f"{self.url.rstrip('/')}/api/reload/config",
                    headers={"Authorization": f"Bearer {self.sec}"}
                )

            return "Configuration successfully synchronized with the remote gateway daemon."

        else:
            listeners_changed = save_unified_config(get_active_config_path(), new_config=parsed_config, new_vault=vault_parsed)
            trigger_local_backend_reload(listeners_only=listeners_changed)
            return "Configuration successfully synchronized with the local gateway daemon."
