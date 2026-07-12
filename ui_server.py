#!/usr/bin/env python3
"""
FASH Stack UI for SMTP to Pushover Gateway

================================================================================
OS PACKAGE REQUIREMENTS
================================================================================
Debian 13 (Trixie):
    $ sudo apt-get update
    $ sudo apt-get install python3 python3-fastapi python3-uvicorn python3-jinja2 python3-multipart python3-cryptography

Alpine Linux:
    $ apk update
    $ apk add python3 py3-fastapi py3-uvicorn py3-jinja2 py3-multipart py3-cryptography
================================================================================
"""

import os
import json
import signal
import uuid
import ssl
import datetime
import threading
import time
import re
import logging
import hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
import uvicorn
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization

# Dynamic Configuration Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.environ.get("GATEWAY_CONFIG", os.path.join(SCRIPT_DIR, "config.json"))
UI_CONFIG_FILE = os.environ.get("UI_CONFIG", os.path.join(SCRIPT_DIR, "ui_config.json"))
VAULT_FILE = os.environ.get("VAULT_FILE", os.path.join(SCRIPT_DIR, "vault.json"))
VAULT_META_FILE = os.environ.get("VAULT_META_FILE", os.path.join(SCRIPT_DIR, "vault_meta.json"))
SMTP_PID_FILE = "/tmp/smtp_pushover.pid"

# Global threading events for perfect signal parity with smtp_pushover.py
ui_shutdown_event = threading.Event()
ui_reload_listeners_event = threading.Event()   # USR1 parities listener reloads
ui_reload_configs_event = threading.Event()     # USR2 parities configuration reloads

class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "GET /healthcheck" not in record.getMessage()

logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

def load_clean_json(filepath):
    if not os.path.exists(filepath): return {}
    try:
        with open(filepath, 'r') as f:
            content = f.read()
        content = re.sub(r'(^|\s)/\*.*?\*/', r'\1', content, flags=re.DOTALL)
        content = re.sub(r'(^|\s)(//|#).*', r'\1', content)
        return json.loads(content)
    except Exception:
        return {}

def save_json(filepath, data):
    with open(filepath, 'w') as f: json.dump(data, f, indent=2)

def load_vault_safe(filepath):
    v = load_clean_json(filepath)
    if "app" not in v and "user" not in v:
        return {"app": v, "user": {}}
    return {"app": v.get("app", {}), "user": v.get("user", {})}

def init_vault():
    if not os.path.exists(VAULT_FILE): save_json(VAULT_FILE, {"app": {}, "user": {}})
    if not os.path.exists(VAULT_META_FILE): save_json(VAULT_META_FILE, {"app": {}, "user": {}})

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_vault()
    yield

app = FastAPI(lifespan=lifespan)

# Embedded HTML Template with full Alpine.js reactivity and Dark Mode native CSS
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pushover Gateway Setup</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <style>
        :root {
            --bg-color: #f4f4f9; --surface-color: #ffffff; --text-color: #333333;
            --border-color: #cccccc; --primary-color: #007bff; --primary-hover: #0056b3;
            --warning-color: #f59e0b; --warning-hover: #d97706;
            --danger-color: #dc3545; --danger-hover: #c82333; --input-bg: #ffffff;
            --secondary-bg: #f8f9fa;
        }
        [data-theme="dark"] {
            --bg-color: #121212; --surface-color: #1e1e1e; --text-color: #e0e0e0;
            --border-color: #444444; --primary-color: #3b82f6; --primary-hover: #2563eb;
            --warning-color: #f59e0b; --warning-hover: #d97706;
            --danger-color: #ef4444; --danger-hover: #dc2626; --input-bg: #2a2a35;
            --secondary-bg: #18181b;
        }
        body { background: var(--bg-color); color: var(--text-color); font-family: system-ui, sans-serif; transition: background 0.3s; margin: 0; padding: 2rem; box-sizing: border-box; }
        .container { max-width: 100%; box-sizing: border-box; margin: auto; background: var(--surface-color); padding: 2rem; border-radius: 8px; border: 1px solid var(--border-color); box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
        .tabs { display: flex; gap: 1rem; border-bottom: 2px solid var(--border-color); margin-bottom: 1.5rem; padding-bottom: 0.5rem; flex-wrap: wrap; }
        .tab { padding: 0.5rem 1rem; cursor: pointer; border-radius: 4px; }
        .tab.active { background: var(--primary-color); color: white; font-weight: bold; }
        .card { border: 1px solid var(--border-color); padding: 1.5rem; border-radius: 6px; margin-bottom: 1.5rem; background: var(--surface-color); }
        .adv-card { border-left: 4px solid var(--primary-color); padding: 1rem 1rem 0.5rem 1.5rem; background: var(--secondary-bg); margin-bottom: 1rem; border-radius: 0 4px 4px 0; }
        .flex-row { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; align-items: flex-end; }
        .flex-col { flex: 1; min-width: 200px; }
        label { display: block; font-weight: bold; margin-bottom: 0.25rem; font-size: 0.9rem; }
        input, select, textarea { width: 100%; padding: 0.5rem; box-sizing: border-box; background: var(--input-bg); color: var(--text-color); border: 1px solid var(--border-color); border-radius: 4px; }
        button { background: var(--primary-color); color: white; padding: 0.5rem 1rem; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; }
        button:hover { background: var(--primary-hover); }
        button.warning { background: var(--warning-color); }
        button.warning:hover { background: var(--warning-hover); }
        button.danger { background: var(--danger-color); }
        button.danger:hover { background: var(--danger-hover); }
        button.outline { background: transparent; color: var(--primary-color); border: 1px solid var(--primary-color); }
        button.outline:hover { background: var(--primary-color); color: white; }
        .header-controls { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; gap: 1rem; }
        .success { color: #10b981; font-weight: bold; margin-top: 1rem; }

        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { border: 1px solid var(--border-color); padding: 0.75rem; text-align: left; }
        th { background: var(--secondary-bg); }
        .table-col-min { width: 1%; white-space: nowrap; }
        .time-display { cursor: help; border-bottom: 1px dashed var(--text-color); }
        .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 1000; }
        .modal-content { background: var(--surface-color); padding: 2rem; border-radius: 8px; width: 400px; max-width: 90%; box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1); border: 1px solid var(--border-color); }
        .token-input { width: 42ch; max-width: 100%; }
        .auto-width { width: auto; max-width: 100%; }
        .clickable-label { display: flex; align-items: center; gap: 0.25rem; cursor: pointer; margin: 0; font-size: 0.85rem; font-weight: normal; color: var(--text-color); }

        .theme-toggle { position: relative; display: inline-flex; align-items: center; justify-content: space-between; width: 56px; height: 28px; background-color: var(--input-bg); border-radius: 14px; cursor: pointer; border: 1px solid var(--border-color); box-sizing: border-box; box-shadow: inset 0 1px 3px rgba(0,0,0,0.1); transition: background-color 0.3s; }
        .theme-toggle .toggle-circle { position: absolute; top: 1px; left: 1px; width: 24px; height: 24px; background-color: var(--primary-color); border-radius: 50%; transition: transform 0.3s cubic-bezier(0.4, 0.0, 0.2, 1); box-shadow: 0 1px 2px rgba(0,0,0,0.2); }
        [data-theme="dark"] .theme-toggle .toggle-circle { transform: translateX(28px); background-color: var(--primary-color); }
        .theme-toggle svg { stroke: var(--text-color); z-index: 1; pointer-events: none; }
    </style>
</head>
<body x-data="gatewaySettings()">
    <div class="container">
        <div class="header-controls">
            <h1>Gateway Configuration</h1>
            <div class="theme-toggle" @click="theme = (theme === 'dark' ? 'light' : 'dark')" title="Toggle Dark Mode">
                <div class="toggle-circle"></div>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px; margin-left: 5px;"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="width: 14px; height: 14px; margin-right: 5px;"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>
            </div>
        </div>

        <div class="tabs">
            <div class="tab" :class="{ 'active': tab === 'pushover' }" @click="tab = 'pushover'">Pushover Rules</div>
            <div class="tab" :class="{ 'active': tab === 'server' }" @click="tab = 'server'">SMTP Server</div>
            <div class="tab" :class="{ 'active': tab === 'vault' }" @click="tab = 'vault'">Token Vault</div>
            <div class="tab" :class="{ 'active': tab === 'ui' }" @click="tab = 'ui'">UI Settings</div>
        </div>

        <form hx-post="/save/config" hx-target="#status" @submit="document.getElementById('config_payload').value = preparePayload()">
            <input type="hidden" name="config_json" id="config_payload">

            <div x-show="tab === 'pushover'">
                <div class="card">
                    <h3>Global API Fallbacks</h3>
                    <div class="flex-row" style="margin-bottom: 0.75rem;">
                        <div style="flex: 0 0 auto;">
                            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
                                <label style="margin: 0;">Default App Token</label>
                                <label class="clickable-label"><input type="checkbox" x-model="pushGlobals._isTokenAlias" style="width: auto; margin: 0;"> (Use Alias)</label>
                            </div>
                            <template x-if="!pushGlobals._isTokenAlias"><input class="token-input" x-model="pushGlobals.token" maxlength="30" placeholder="Required for Catch-All" autocomplete="new-password" data-lpignore="true" data-bwignore="true" data-1p-ignore="true"></template>
                            <template x-if="pushGlobals._isTokenAlias">
                                <select class="auto-width" x-model="pushGlobals.token">
                                    <option value="">-- Select App Alias --</option>
                                    <template x-for="alias in vaultAppAliases" :key="alias"><option :value="alias" x-text="alias" :selected="pushGlobals.token === alias"></option></template>
                                </select>
                            </template>
                        </div>
                    </div>
                    <div class="flex-row">
                        <div style="flex: 0 0 auto;">
                            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;">
                                <label style="margin: 0;">Default User Key</label>
                                <label class="clickable-label"><input type="checkbox" x-model="pushGlobals._isUserAlias" style="width: auto; margin: 0;"> (Use Alias)</label>
                            </div>
                            <template x-if="!pushGlobals._isUserAlias"><input class="token-input" x-model="pushGlobals.user" maxlength="30" placeholder="Required for Catch-All" autocomplete="new-password" data-lpignore="true" data-bwignore="true" data-1p-ignore="true"></template>
                            <template x-if="pushGlobals._isUserAlias">
                                <select class="auto-width" x-model="pushGlobals.user">
                                    <option value="">-- Select User Alias --</option>
                                    <template x-for="alias in vaultUserAliases" :key="alias"><option :value="alias" x-text="alias" :selected="pushGlobals.user === alias"></option></template>
                                </select>
                            </template>
                        </div>
                    </div>
                    <button type="button" class="outline" @click="showGlobalAdv = !showGlobalAdv" style="margin-bottom: 1rem; margin-top: 0.5rem;"><span x-text="showGlobalAdv ? 'Hide Advanced Globals' : 'Show Advanced Globals'"></span></button>
                    <div x-show="showGlobalAdv" class="adv-card">
                        <div class="flex-row" style="margin-bottom: 1rem;">
                            <div style="flex: 0 0 auto;">
                                <label>Priority</label>
                                <select class="auto-width" x-model="pushGlobals.priority">
                                    <option value="">Default (0)</option><option value="-2">Lowest (-2)</option><option value="-1">Low (-1)</option><option value="0">Normal (0)</option><option value="1">High (1)</option><option value="2">Emergency (2)</option>
                                </select>
                            </div>
                            <div class="flex-col" style="flex: 1; min-width: 200px;"><label>Target Device</label><input x-model="pushGlobals.device" placeholder="All Devices" style="width: 100%;"></div>
                        </div>
                        <div class="flex-row" x-show="pushGlobals.priority == 2" style="margin-bottom: 1rem;">
                            <div style="flex: 0 0 auto;"><label>Retry (sec) &gt;= 30</label><input type="number" x-model.number="pushGlobals.retry" min="30" style="width: 120px;"></div>
                            <div style="flex: 0 0 auto;"><label>Expire (sec) &lt;= 10800</label><input type="number" x-model.number="pushGlobals.expire" max="10800" style="width: 120px;"></div>
                        </div>
                        <div class="flex-row" style="margin-bottom: 1rem;"><div class="flex-col" style="flex: 1; min-width: 200px;"><label>Supplementary URL</label><input x-model="pushGlobals.url" placeholder="Optional" maxlength="512" style="width: 100%;"></div></div>
                        <div class="flex-row" style="margin-bottom: 1rem;"><div style="flex: 0 0 auto;"><label>URL Title</label><input x-model="pushGlobals.url_title" placeholder="Optional" maxlength="100" style="width: 100ch; max-width: 100%;"></div></div>
                    </div>
                </div>

                <div class="card">
                    <h3>Email Maps & Routes</h3>
                    <template x-for="(map, idx) in mappings" :key="idx">
                        <div class="card" style="background: var(--bg-color);">
                            <div class="flex-row" style="align-items: flex-start;">
                                <div style="flex: 0 0 auto;"><label>Match Type</label><select class="auto-width" x-model="map.match"><option value="to">To (Recipient)</option><option value="from">From (Sender)</option><option value="both">Both</option></select></div>
                                <div style="flex: 1; min-width: 200px;">
                                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;"><label style="margin: 0;">Email Address</label><label class="clickable-label"><input type="checkbox" x-model="map._isRegex" style="width: auto; margin: 0;"> (Use Regex)</label></div>
                                    <input x-model="map._key" placeholder="user@domain.com or ^.*@domain\\.com$" autocomplete="new-password" data-lpignore="true" data-bwignore="true" data-1p-ignore="true" style="width: 100%;">
                                </div>
                                <div style="flex: 0 0 auto;">
                                    <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;"><label style="margin: 0;">App Token</label><label class="clickable-label"><input type="checkbox" x-model="map._isTokenAlias" style="width: auto; margin: 0;"> (Use Alias)</label></div>
                                    <template x-if="!map._isTokenAlias"><input class="token-input" x-model="map.token" maxlength="30" placeholder="Required Override" autocomplete="new-password" data-lpignore="true" data-bwignore="true" data-1p-ignore="true"></template>
                                    <template x-if="map._isTokenAlias">
                                        <select class="auto-width" x-model="map.token">
                                            <option value="">-- Select App Alias --</option>
                                            <template x-for="alias in vaultAppAliases" :key="alias"><option :value="alias" x-text="alias" :selected="map.token === alias"></option></template>
                                        </select>
                                    </template>
                                </div>
                            </div>
                            <button type="button" class="outline" @click="map._showAdv = !map._showAdv" style="margin-bottom: 1rem; font-size: 0.8rem; padding: 0.3rem 0.5rem;"><span x-text="map._showAdv ? 'Hide Route Settings' : 'Show Route Settings'"></span></button>
                            <div x-show="map._showAdv" class="adv-card">
                                <div class="flex-row" style="margin-bottom: 1.5rem; justify-content: flex-start;">
                                    <div style="flex: 0 0 auto;">
                                        <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.25rem;"><label style="margin: 0;">User Key Override</label><label class="clickable-label"><input type="checkbox" x-model="map._isUserAlias" style="width: auto; margin: 0;"> (Use Alias)</label></div>
                                        <template x-if="!map._isUserAlias"><input class="token-input" x-model="map.user" maxlength="30" placeholder="Inherit Global" autocomplete="new-password" data-lpignore="true" data-bwignore="true" data-1p-ignore="true"></template>
                                        <template x-if="map._isUserAlias">
                                            <select class="auto-width" x-model="map.user">
                                                <option value="">-- Inherit Global --</option>
                                                <template x-for="alias in vaultUserAliases" :key="alias"><option :value="alias" x-text="alias" :selected="map.user === alias"></option></template>
                                            </select>
                                        </template>
                                    </div>
                                    <div style="flex: 0 0 auto;"><label>Priority Override</label><select class="auto-width" x-model="map.priority"><option value="">Inherit Global</option><option value="-2">Lowest (-2)</option><option value="-1">Low (-1)</option><option value="0">Normal (0)</option><option value="1">High (1)</option><option value="2">Emergency (2)</option></select></div>
                                    <div class="flex-col" style="flex: 1; min-width: 150px;"><label>Target Device</label><input x-model="map.device" placeholder="Inherit Global" style="width: 100%;"></div>
                                </div>
                                <div class="flex-row" x-show="map.priority == 2" style="margin-bottom: 1rem;">
                                    <div style="flex: 0 0 auto;"><label>Retry (sec)</label><input type="number" x-model.number="map.retry" min="30" style="width: 120px;"></div>
                                    <div style="flex: 0 0 auto;"><label>Expire (sec)</label><input type="number" x-model.number="map.expire" max="10800" style="width: 120px;"></div>
                                </div>
                                <div class="flex-row" style="margin-bottom: 0.5rem;"><div class="flex-col" style="flex: 1; min-width: 200px;"><label>Supplementary URL</label><input x-model="map.url" placeholder="Inherit Global" maxlength="512" style="width: 100%;"></div></div>
                                <div class="flex-row" style="margin-bottom: 1rem;"><div style="flex: 0 0 auto;"><label>URL Title</label><input x-model="map.url_title" placeholder="Inherit Global" maxlength="100" style="width: 100ch; max-width: 100%;"></div></div>
                            </div>
                            <div style="text-align: right;"><button type="button" class="danger" @click="mappings.splice(idx, 1)">Remove Mapping</button></div>
                        </div>
                    </template>
                    <button type="button" @click="addMapping()">+ Add Mapping</button>
                </div>
            </div>

            <div x-show="tab === 'server'">
                <div class="card">
                    <h3>Global Configuration</h3>
                    <div class="flex-row" style="margin-bottom: 1rem;"><div style="flex: 0 0 auto;"><label>Log Level</label><select class="auto-width" x-model="smtp.loglevel"><option value="INFO">INFO</option><option value="DEBUG">DEBUG</option><option value="WARNING">WARNING</option><option value="ERROR">ERROR</option></select></div></div>
                    <div class="flex-row" style="margin-bottom: 1rem;"><div class="flex-col" style="flex: 1; min-width: 200px;"><label>Disk Queue Directory</label><input x-model="smtp.queue_dir" placeholder="/tmp/queue" style="width: 100%;"></div></div>
                    <div class="flex-row" style="margin-bottom: 1rem;"><div class="flex-col" style="flex: 1; min-width: 200px;"><label>Global Hostname (Greeting Banner)</label><input x-model="smtp.hostname" placeholder="gateway.local" style="width: 100%;"></div></div>
                    <div class="flex-row">
                        <div class="flex-col" style="flex: 1; min-width: 200px;"><label>Global TLS Cert File (Fallback)</label><input x-model="smtp.tls_cert_file" placeholder="/etc/ssl/certs/global.pem" style="width: 100%;"></div>
                        <div class="flex-col" style="flex: 1; min-width: 200px;"><label>Global TLS Key File (Fallback)</label><input x-model="smtp.tls_key_file" placeholder="/etc/ssl/private/global.key" style="width: 100%;"></div>
                    </div>
                </div>

                <div class="card">
                    <h3>SMTP Client Authentication Store</h3>
                    <div class="adv-card" style="margin-bottom: 1.5rem; border-left-color: var(--primary-color);">
                        <h4>Provision New SMTP User</h4>
                        <div class="flex-row">
                            <div class="flex-col"><input type="text" x-model="newSmtpUser" placeholder="Username" autocomplete="new-password" data-lpignore="true" data-bwignore="true" data-1p-ignore="true"></div>
                            <div class="flex-col"><input type="password" x-model="newSmtpPass" placeholder="Password" autocomplete="new-password" data-lpignore="true" data-bwignore="true" data-1p-ignore="true"></div>
                            <div style="flex: 0 0 auto; display: flex; gap: 0.5rem;"><button type="button" @click="addSmtpUser()">Add User</button><button type="button" class="outline" @click="newSmtpUser = ''; newSmtpPass = '';">Clear</button></div>
                        </div>
                    </div>
                    <hr><h4>Current SMTP Users</h4>
                    <table>
                        <thead><tr><th>Username</th><th class="table-col-min">Last Modification</th><th class="table-col-min">Actions</th></tr></thead>
                        <tbody>
                            <template x-for="(user, name) in smtp.auth" :key="name">
                                <tr>
                                    <td x-text="name" style="font-weight: bold;"></td>
                                    <td class="table-col-min"><span class="time-display" x-text="formatTime(smtp_meta[name])" :title="getFullTime(smtp_meta[name])"></span></td>
                                    <td class="table-col-min"><button type="button" class="outline" @click="openEditModal('smtp', name)">Change Password</button><button type="button" class="danger" @click="delete smtp.auth[name]; delete smtp_meta[name];">Remove</button></td>
                                </tr>
                            </template>
                        </tbody>
                    </table>
                </div>

                <div class="card">
                    <h3>TCP Listeners & Binds</h3>
                    <template x-for="(l, idx) in smtp.listeners" :key="idx">
                        <div class="card" style="background: var(--bg-color);">
                            <div class="flex-row" style="align-items: flex-end; margin-bottom: 1rem;">
                                <div style="flex: 0 0 auto;"><label>Bind Address</label><input x-model="l.bind" placeholder="0.0.0.0:25" maxlength="52" style="width: 55ch; max-width: 100%;"></div>
                                <div style="flex: 0 0 auto; padding-bottom: 0.5rem;"><label class="clickable-label"><input type="checkbox" x-model="l.starttls" style="margin: 0;"> STARTTLS</label></div>
                            </div>
                            <div class="flex-row" style="margin-bottom: 1rem;"><div class="flex-col" style="flex: 1; min-width: 200px;"><label>Hostname Override</label><input x-model="l.hostname" placeholder="Optional" style="width: 100%;"></div></div>
                            <div class="flex-row" x-show="l.starttls" style="margin-bottom: 1rem;">
                                <div class="flex-col"><label>Specific TLS Cert File</label><input x-model="l.tls_cert_file" placeholder="Leaves blank to use Global"></div>
                                <div class="flex-col"><label>Specific TLS Key File</label><input x-model="l.tls_key_file" placeholder="Leaves blank to use Global"></div>
                            </div>
                            <div style="text-align: right;"><button type="button" class="danger" @click="smtp.listeners.splice(idx, 1)">Remove Listener</button></div>
                        </div>
                    </template>
                    <button type="button" @click="addListener()">+ Add TCP Listener</button>
                </div>
            </div>

            <div x-show="tab === 'pushover' || tab === 'server'" style="margin-top: 1.5rem; display: flex; gap: 1rem;">
                <button type="submit">Save Application Configuration</button>
                <button type="button" class="warning" @click="window.location.reload()">Discard Changes & Reload from Disk</button>
            </div>
        </form>

        <div x-show="tab === 'vault'">
            <div class="card">
                <h3>API Token Vault</h3>
                <p>Store your raw Pushover tokens and User Keys here safely to map as Aliases.</p>
                <form @submit.prevent="addVaultToken()">
                    <div class="flex-row" style="gap: 1rem; align-items: flex-end; justify-content: flex-start;">
                        <div style="flex: 0 0 auto;"><label>Token Type</label><select class="auto-width" x-model="newVaultType"><option value="app">App Token</option><option value="user">User Key</option></select></div>
                        <div style="flex: 1; min-width: 150px;"><label>Alias Name</label><input type="text" x-model="newVaultName" required autocomplete="off" data-lpignore="true" data-bwignore="true" data-1p-ignore="true" style="width: 100%;"></div>
                        <div style="flex: 0 0 auto;"><label>Token Value</label><input type="password" class="token-input" x-model="newVaultToken" maxlength="30" required autocomplete="new-password" data-lpignore="true" data-bwignore="true" data-1p-ignore="true"></div>
                        <div style="flex: 0 0 auto; display: flex; gap: 0.5rem;"><button type="submit">Add Token</button><button type="button" class="outline" @click="newVaultName=''; newVaultToken='';">Clear</button></div>
                    </div>
                </form>
                <hr><h4>Current App Token Aliases</h4>
                <table style="margin-bottom: 2rem;">
                    <thead><tr><th style="width: auto;">Alias Name</th><th class="table-col-min">Last Modification</th><th class="table-col-min">Actions</th></tr></thead>
                    <tbody>
                        <template x-for="(v, idx) in vaultApp" :key="v.name">
                            <tr>
                                <td><strong x-text="v.name"></strong></td>
                                <td class="table-col-min"><span class="time-display" x-text="formatTime(v.epoch)" :title="getFullTime(v.epoch)"></span></td>
                                <td class="table-col-min"><button type="button" class="outline" @click="openEditModal('vault', v.name, 'app', idx)">Modify Secret</button><button type="button" class="danger" @click="deleteVaultToken('app', idx)">Delete</button></td>
                            </tr>
                        </template>
                    </tbody>
                </table>
                <h4>Current User Token Aliases</h4>
                <table>
                    <thead><tr><th style="width: auto;">Alias Name</th><th class="table-col-min">Last Modification</th><th class="table-col-min">Actions</th></tr></thead>
                    <tbody>
                        <template x-for="(v, idx) in vaultUser" :key="v.name">
                            <tr>
                                <td><strong x-text="v.name"></strong></td>
                                <td class="table-col-min"><span class="time-display" x-text="formatTime(v.epoch)" :title="getFullTime(v.epoch)"></span></td>
                                <td class="table-col-min"><button type="button" class="outline" @click="openEditModal('vault', v.name, 'user', idx)">Modify Secret</button><button type="button" class="danger" @click="deleteVaultToken('user', idx)">Delete</button></td>
                            </tr>
                        </template>
                    </tbody>
                </table>
            </div>
            <form hx-post="/save/vault_state" hx-target="#status" @submit="document.getElementById('vault_payload').value = prepareVaultPayload()">
                <input type="hidden" name="vault_json" id="vault_payload">
                <div style="margin-top: 1.5rem; display: flex; gap: 1rem;">
                    <button type="submit">Save Token Vault Configuration</button>
                    <button type="button" class="warning" @click="window.location.reload()">Discard Changes & Reload from Disk</button>
                </div>
            </form>
        </div>

        <div x-show="tab === 'ui'" x-data="{ httpsEnabled: {{ 'true' if ui_https else 'false' }} }">
            <form hx-post="/save/ui" hx-target="#status">
                <div class="card">
                    <h3>Web UI Settings</h3>
                    <div class="form-group" style="margin-bottom: 1rem;"><label>UI Listen Port</label><input type="number" name="port" value="{{ ui_port }}" required style="width: 120px; max-width: 100%;" oninput="if(this.value.length > 5) this.value = this.value.slice(0, 5);" min="1" max="65535"></div>
                    <div class="flex-row">
                        <div style="flex: 0 0 auto;">
                            <label>Display Timezone Location</label>
                            <select class="auto-width" name="timezone" x-model="ui_tz">
                                <option value="UTC">UTC / GMT</option><option value="America/New_York">Eastern Time</option><option value="America/Chicago">Central Time</option><option value="America/Denver">Mountain Time</option><option value="America/Los_Angeles">Pacific Time</option><option value="Europe/London">London (GMT/BST)</option>
                            </select>
                        </div>
                        <div style="flex: 0 0 auto;">
                            <label>Date Format Syntax</label>
                            <select class="auto-width" name="date_format" x-model="ui_fmt">
                                <option value="YYYY-MM-DD HH:mm:ss">ISO (YYYY-MM-DD HH:mm:ss)</option><option value="MM/DD/YYYY hh:mm:ss A">US (MM/DD/YYYY hh:mm:ss A)</option><option value="DD/MM/YYYY HH:mm:ss">UK/EU (DD/MM/YYYY HH:mm:ss)</option>
                            </select>
                        </div>
                    </div>
                    <div style="margin-bottom: 0.5rem; margin-top: 1rem;"><label class="clickable-label"><input type="checkbox" name="relative_time" x-model="ui_relative" style="width: auto; margin: 0;"> Render Coerced Relative Human Times (e.g. '3 days ago')</label></div>
                    <div style="margin-bottom: 1.5rem;"><label class="clickable-label"><input type="checkbox" name="expand_adv" x-model="ui_expand_adv" style="width: auto; margin: 0;"> Always Expand Route Settings by Default</label></div>
                    <hr><div style="margin-bottom: 1rem;"><label class="clickable-label"><input type="checkbox" name="https" x-model="httpsEnabled" style="width: auto; margin: 0;"> Enable HTTPS Bindings</label></div>
                    <div class="flex-row" x-show="httpsEnabled">
                        <div class="flex-col"><label>UI Specific TLS Cert File</label><input type="text" name="tls_cert" value="{{ ui_cert }}" placeholder="Leave blank for auto-generated UUID cert"></div>
                        <div class="flex-col"><label>UI Specific TLS Key File</label><input type="text" name="tls_key" value="{{ ui_key }}"></div>
                    </div>
                </div>
                <div style="margin-top: 1.5rem; display: flex; gap: 1rem;">
                    <button type="submit">Save UI Transformations</button>
                    <button type="button" class="warning" @click="window.location.reload()">Discard Changes & Reload from Disk</button>
                </div>
            </form>
        </div>

        <div id="status" class="success"></div>
        <div x-show="editModal.open" class="modal-overlay" style="display: none;" x-transition>
            <div class="modal-content" @click.away="editModal.open = false">
                <h3 style="margin-top: 0;" x-text="editModal.type === 'smtp' ? 'Change Password for ' + editModal.name : 'Modify Secret for ' + editModal.name"></h3>
                <div class="form-group">
                    <label x-text="editModal.type === 'smtp' ? 'New Password' : 'New Token Value'"></label>
                    <input type="password" class="token-input" x-model="editModal.value" @keyup.enter="saveEditModal()" placeholder="Enter new hidden value..." autocomplete="new-password" data-lpignore="true" data-bwignore="true" data-1p-ignore="true" :maxlength="editModal.type === 'vault' ? 30 : 256">
                </div>
                <div style="display: flex; gap: 1rem; justify-content: flex-end; margin-top: 1.5rem;">
                    <button type="button" class="outline" @click="editModal.open = false">Cancel</button><button type="button" @click="saveEditModal()">Save Changes</button>
                </div>
            </div>
        </div>
    </div>

    <script>
    document.addEventListener('alpine:init', () => {
        Alpine.data('gatewaySettings', () => ({
            theme: localStorage.getItem('theme') || 'dark',
            tab: localStorage.getItem('activeTab') || 'pushover',
            rawConfig: {{ config_json | safe }},
            smtp_meta: {{ smtp_meta_json | safe }},
            vaultMeta: {{ vault_meta_json | safe }},
            vaultApp: [], vaultUser: [], vaultAppAliases: [], vaultUserAliases: [],
            newVaultType: 'app', newVaultName: '', newVaultToken: '',
            ui_tz: '{{ ui_tz }}', ui_fmt: '{{ ui_fmt }}',
            ui_relative: {{ 'true' if ui_relative else 'false' }},
            ui_expand_adv: {{ 'true' if ui_expand_adv else 'false' }},
            pushGlobals: {}, showGlobalAdv: false, mappings: [], smtp: {},
            newSmtpUser: '', newSmtpPass: '',
            editModal: { open: false, type: '', subType: '', name: '', idx: null, value: '' },

            init() {
                this.$watch('theme', val => { localStorage.setItem('theme', val); document.documentElement.setAttribute('data-theme', val); });
                this.$watch('tab', val => localStorage.setItem('activeTab', val));
                document.documentElement.setAttribute('data-theme', this.theme);

                for(const [k, v] of Object.entries(this.vaultMeta.app || {})) { this.vaultApp.push({ name: k, epoch: v, token: '__RETAIN__' }); this.vaultAppAliases.push(k); }
                for(const [k, v] of Object.entries(this.vaultMeta.user || {})) { this.vaultUser.push({ name: k, epoch: v, token: '__RETAIN__' }); this.vaultUserAliases.push(k); }

                const gKeys = ['user','token','device','sound','url','url_title','tags','priority','ttl','retry','expire','attachments','force_plaintext','disable_persistence'];
                const po = this.rawConfig.pushover || {};
                for(const [k, v] of Object.entries(po)) {
                    if(gKeys.includes(k)) { this.pushGlobals[k] = v; } else {
                        const isTokenAlias = this.vaultAppAliases.includes(v.token);
                        const isUserAlias = this.vaultUserAliases.includes(v.user);
                        let isRegex = false; let displayKey = k;
                        if (k.toLowerCase().startsWith('regex:')) { isRegex = true; displayKey = k.substring(6); }
                        this.mappings.push({ _key: displayKey, _isRegex: isRegex, _showAdv: this.ui_expand_adv, _isTokenAlias: isTokenAlias, _isUserAlias: isUserAlias, disable_attachments: (v.attachments === false), force_plaintext: (v.force_plaintext === true), disable_persistence: (v.disable_persistence === true), ...v });
                    }
                }
                this.pushGlobals._isTokenAlias = this.vaultAppAliases.includes(po.token);
                this.pushGlobals._isUserAlias = this.vaultUserAliases.includes(po.user);
                this.pushGlobals.disable_attachments = (po.attachments === false);
                this.pushGlobals.force_plaintext = (po.force_plaintext === true);
                this.pushGlobals.disable_persistence = (po.disable_persistence === true);
                this.smtp = this.rawConfig.smtp || {};
                if(!this.smtp.listeners) this.smtp.listeners = [];
                if(!this.smtp.auth) this.smtp.auth = {};
            },
            formatTime(epoch) {
                if(!epoch) return "Never"; const d = new Date(epoch * 1000);
                if(this.ui_relative) {
                    const seconds = Math.floor((new Date() - d) / 1000); let interval = Math.floor(seconds / 31536000);
                    if (interval >= 1) return interval + " years ago"; interval = Math.floor(seconds / 2592000);
                    if (interval >= 1) return interval + " months ago"; interval = Math.floor(seconds / 84600);
                    if (interval >= 1) return interval + " days ago"; interval = Math.floor(seconds / 3600);
                    if (interval >= 1) return interval + " hours ago"; interval = Math.floor(seconds / 60);
                    if (interval >= 1) return interval + " minutes ago"; return "Just now";
                }
                return this.executeAbsoluteFormat(d);
            },
            getFullTime(epoch) { if(!epoch) return ""; return this.executeAbsoluteFormat(new Date(epoch * 1000)); },
            executeAbsoluteFormat(d) {
                const pad = num => String(num).padStart(2, '0'); const t_str = d.toLocaleString("en-US", { timeZone: this.ui_tz }); const localD = new Date(t_str);
                const yyyy = localD.getFullYear(); const mm = pad(localD.getMonth() + 1); const dd = pad(localD.getDate()); let hh = localD.getHours(); const min = pad(localD.getMinutes()); const ss = pad(localD.getSeconds()); const ampm = hh >= 12 ? 'PM' : 'AM';
                if (this.ui_fmt.includes("hh")) { hh = hh % 12; hh = hh ? hh : 12; hh = pad(hh); return `${mm}/${dd}/${yyyy} ${hh}:${min}:${ss} ${ampm}`; }
                if (this.ui_fmt.startsWith("DD")) { return `${dd}/${mm}/${yyyy} ${pad(hh)}:${min}:${ss}`; }
                return `${yyyy}-${mm}-${dd} ${pad(hh)}:${min}:${ss}`;
            },
            addMapping() { this.mappings.push({ _key: '', match: 'to', token: '', _isRegex: false, _isTokenAlias: false, _isUserAlias: false, _showAdv: this.ui_expand_adv, disable_attachments: false, force_plaintext: false, disable_persistence: false }); },
            addListener() { this.smtp.listeners.push({ bind: '0.0.0.0:25', starttls: false, tls_cert_file: '', tls_key_file: '' }); },
            addSmtpUser() { if(!this.newSmtpUser || !this.newSmtpPass) return; this.smtp.auth[this.newSmtpUser] = "RAW:" + this.newSmtpPass; this.smtp_meta[this.newSmtpUser] = Math.floor(Date.now() / 1000); this.newSmtpUser = ''; this.newSmtpPass = ''; },
            addVaultToken() {
                if(!this.newVaultName || !this.newVaultToken) return; const target = this.newVaultType === 'app' ? this.vaultApp : this.vaultUser; const existingIdx = target.findIndex(x => x.name === this.newVaultName);
                if(existingIdx >= 0) { target[existingIdx].token = this.newVaultToken; target[existingIdx].epoch = Math.floor(Date.now() / 1000); } else { target.push({name: this.newVaultName, token: this.newVaultToken, epoch: Math.floor(Date.now() / 1000)}); }
                if(this.newVaultType === 'app' && !this.vaultAppAliases.includes(this.newVaultName)) this.vaultAppAliases.push(this.newVaultName);
                if(this.newVaultType === 'user' && !this.vaultUserAliases.includes(this.newVaultName)) this.vaultUserAliases.push(this.newVaultName);
                this.newVaultName = ''; this.newVaultToken = '';
            },
            deleteVaultToken(type, idx) {
                const targetArr = type === 'app' ? this.vaultApp : this.vaultUser; const aliasName = targetArr[idx].name; let inUse = false;
                if(type === 'app') { if(this.pushGlobals._isTokenAlias && this.pushGlobals.token === aliasName) inUse = true; this.mappings.forEach(m => { if(m._isTokenAlias && m.token === aliasName) inUse = true; }); } else { if(this.pushGlobals._isUserAlias && this.pushGlobals.user === aliasName) inUse = true; this.mappings.forEach(m => { if(m._isUserAlias && m.user === aliasName) inUse = true; }); }
                if(inUse) { alert(`Error: Alias '${aliasName}' is actively assigned to an email route. Reconfigure your Pushover Rules before deleting.`); return; }
                targetArr.splice(idx, 1); if(type === 'app') this.vaultAppAliases = this.vaultAppAliases.filter(a => a !== aliasName); if(type === 'user') this.vaultUserAliases = this.vaultUserAliases.filter(a => a !== aliasName);
            },
            openEditModal(type, name, subType='', idx=null) { this.editModal.type = type; this.editModal.subType = subType; this.editModal.name = name; this.editModal.idx = idx; this.editModal.value = ''; this.editModal.open = true; },
            saveEditModal() {
                if(!this.editModal.value) return;
                if(this.editModal.type === 'smtp') { this.smtp.auth[this.editModal.name] = "RAW:" + this.editModal.value; this.smtp_meta[this.editModal.name] = Math.floor(Date.now() / 1000); } else if(this.editModal.type === 'vault') { const target = this.editModal.subType === 'app' ? this.vaultApp : this.vaultUser; target[this.editModal.idx].token = this.editModal.value; target[this.editModal.idx].epoch = Math.floor(Date.now() / 1000); }
                this.editModal.open = false;
            },
            preparePayload() {
                const finalPushover = { ...this.pushGlobals }; finalPushover.attachments = !this.pushGlobals.disable_attachments; delete finalPushover.disable_attachments; delete finalPushover._isTokenAlias; delete finalPushover._isUserAlias;
                ['priority', 'retry', 'expire', 'ttl'].forEach(p => { if (finalPushover[p] === '' || finalPushover[p] === null || finalPushover[p] === undefined) delete finalPushover[p]; else finalPushover[p] = parseInt(finalPushover[p], 10); });
                ['device', 'url', 'url_title', 'sound', 'tags', 'user'].forEach(p => { if (finalPushover[p] === '') delete finalPushover[p]; });
                this.mappings.forEach(m => {
                    if(m._key && m._key.trim() !== '') {
                        let k = m._key.trim(); if (m._isRegex && !k.toLowerCase().startsWith('regex:')) { k = 'regex:' + k; }
                        const { _key, _showAdv, _isTokenAlias, _isUserAlias, _isRegex, disable_attachments, ...rest } = m; rest.attachments = !disable_attachments;
                        ['priority', 'retry', 'expire', 'ttl'].forEach(p => { if (rest[p] === '' || rest[p] === null || rest[p] === undefined) delete rest[p]; else rest[p] = parseInt(rest[p], 10); });
                        ['device', 'url', 'url_title', 'sound', 'tags', 'user'].forEach(p => { if (rest[p] === '') delete rest[p]; }); finalPushover[k] = rest;
                    }
                });
                return JSON.stringify({ pushover: finalPushover, smtp: this.smtp, _smtp_meta: this.smtp_meta });
            },
            prepareVaultPayload() { return JSON.stringify({ app: this.vaultApp, user: this.vaultUser }); }
        }));
    });
    </script>
</body>
</html>
"""

templates = Jinja2Templates(directory=".")

def signal_smtp_app(restart_listeners=False):
    if not os.path.exists(SMTP_PID_FILE): return False
    with open(SMTP_PID_FILE, 'r') as f:
        pid = int(f.read().strip())
    try:
        os.kill(pid, signal.SIGUSR2)
        if restart_listeners:
            time.sleep(5.0)
            os.kill(pid, signal.SIGUSR1)
        return True
    except ProcessLookupError: return False

@app.get("/healthcheck", response_class=PlainTextResponse)
async def healthcheck():
    return "OK"

@app.get("/", response_class=HTMLResponse)
async def index():
    config = load_clean_json(CONFIG_FILE)
    ui_config = load_clean_json(UI_CONFIG_FILE)
    vault_entries = load_vault_safe(VAULT_META_FILE)

    auth_block = config.get("smtp", {}).get("auth", {})
    meta_block = config.get("smtp", {}).get("_smtp_meta", {})
    changed = False
    for user, pwd in list(auth_block.items()):
        if not pwd.startswith("$") and not re.match(r'^[a-fA-F0-9]{64}$', pwd):
            auth_block[user] = hashlib.sha256(pwd.encode('utf-8')).hexdigest()
            if user not in meta_block: meta_block[user] = int(time.time())
            changed = True
    if changed:
        if "smtp" not in config: config["smtp"] = {}
        config["smtp"]["auth"] = auth_block
        config["smtp"]["_smtp_meta"] = meta_block
        save_json(CONFIG_FILE, config)
        signal_smtp_app(restart_listeners=False)

    smtp_block = config.get("smtp", {})
    smtp_meta = smtp_block.get("_smtp_meta", {})

    template = templates.env.from_string(HTML_TEMPLATE)
    return template.render(
        config_json=json.dumps(config),
        smtp_meta_json=json.dumps(smtp_meta),
        vault_meta_json=json.dumps(vault_entries),
        vault_app_json=json.dumps(list(vault_entries.get("app", {}).keys())),
        vault_user_json=json.dumps(list(vault_entries.get("user", {}).keys())),
        ui_port=ui_config.get("port", 8443),
        ui_https=ui_config.get("https", True),
        ui_expand_adv=ui_config.get("expand_adv", False),
        ui_tz=ui_config.get("timezone", "UTC"),
        ui_fmt=ui_config.get("date_format", "YYYY-MM-DD HH:mm:ss"),
        ui_relative=ui_config.get("relative_time", True),
        ui_cert=ui_config.get("tls_cert", ""),
        ui_key=ui_config.get("tls_key", "")
    )

@app.post("/save/config")
async def save_config(config_json: str = Form(...)):
    try:
        parsed = json.loads(config_json)
        old_config = load_clean_json(CONFIG_FILE)
        auth_block = parsed.get("smtp", {}).get("auth", {})
        meta_block = parsed.get("_smtp_meta", {})
        for user, pwd in list(auth_block.items()):
            if str(pwd).startswith("RAW:"):
                plain = pwd[4:]
                auth_block[user] = hashlib.sha256(plain.encode('utf-8')).hexdigest()
                if user not in meta_block: meta_block[user] = int(time.time())
        parsed["smtp"]["_smtp_meta"] = meta_block
        if "_smtp_meta" in parsed: del parsed["_smtp_meta"]
        save_json(CONFIG_FILE, parsed)
        old_smtp = old_config.get("smtp", {})
        new_smtp = parsed.get("smtp", {})
        if "_smtp_meta" in old_smtp: del old_smtp["_smtp_meta"]
        if "_smtp_meta" in new_smtp: del new_smtp["_smtp_meta"]
        needs_restart = (old_smtp != new_smtp)
        signal_smtp_app(restart_listeners=needs_restart)
        return HTMLResponse("Configuration successfully synchronized with the gateway daemon.")
    except Exception as e: return HTMLResponse(f"Error compiling config structure: {e}")

@app.post("/save/vault_state")
async def save_vault_state(vault_json: str = Form(...)):
    try:
        parsed = json.loads(vault_json)
        vault_data = load_vault_safe(VAULT_FILE)
        new_data, new_meta = {"app": {}, "user": {}}, {"app": {}, "user": {}}
        for vtype in ["app", "user"]:
            for item in parsed.get(vtype, []):
                name = item["name"]; tok = item["token"]; epoch = item["epoch"]
                if tok == "__RETAIN__": new_data[vtype][name] = vault_data[vtype].get(name, "")
                else: new_data[vtype][name] = tok
                new_meta[vtype][name] = epoch
        save_json(VAULT_FILE, new_data)
        save_json(VAULT_META_FILE, new_meta)
        signal_smtp_app(restart_listeners=False)
        return HTMLResponse("Token Vault safely synchronized with the gateway daemon.")
    except Exception as e: return HTMLResponse(f"Error parsing Vault Array: {e}")

@app.post("/save/ui")
async def save_ui(
    port: int = Form(...), timezone: str = Form(...), date_format: str = Form(...),
    relative_time: bool = Form(False), expand_adv: bool = Form(False), https: bool = Form(False), tls_cert: str = Form(""), tls_key: str = Form("")
):
    ui_config = {
        "port": port, "timezone": timezone, "date_format": date_format,
        "relative_time": relative_time, "expand_adv": expand_adv, "https": https, "tls_cert": tls_cert, "tls_key": tls_key
    }
    save_json(UI_CONFIG_FILE, ui_config)
    # Native signal handler notification triggers loop rotation
    os.kill(os.getpid(), signal.SIGUSR1)
    return HTMLResponse("UI engine configuration altered successfully.")

def generate_ui_cert():
    cert_path, key_path = "/tmp/ui_cert.pem", "/tmp/ui_key.pem"
    if os.path.exists(cert_path): return cert_path, key_path
    private_key = ec.generate_private_key(ec.SECP384R1())
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, str(uuid.uuid4()))])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = x509.CertificateBuilder().subject_name(subject).issuer_name(issuer).public_key(
        private_key.public_key()
    ).serial_number(x509.random_serial_number()).not_valid_before(now).not_valid_after(
        now + datetime.timedelta(days=365)
    ).sign(private_key, hashes.SHA256())
    with open(key_path, "wb") as f: f.write(private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()))
    with open(cert_path, "wb") as f: f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path

if __name__ == "__main__":
    # Standardize OS signal parities with the gateway daemon
    signal.signal(signal.SIGINT, lambda s, f: ui_shutdown_event.set())
    signal.signal(signal.SIGTERM, lambda s, f: ui_shutdown_event.set())
    if hasattr(signal, 'SIGUSR1'): signal.signal(signal.SIGUSR1, lambda s, f: ui_reload_listeners_event.set())
    if hasattr(signal, 'SIGUSR2'): signal.signal(signal.SIGUSR2, lambda s, f: ui_reload_configs_event.set())

    while not ui_shutdown_event.is_set():
        # Configuration Hot-Reload Trigger (SIGUSR2 parity mapping)
        if ui_reload_configs_event.is_set():
            ui_reload_configs_event.clear()
            logging.info("Caught SIGUSR2 inside UI process space. Performing configurations hot-reload...")
            # Re-read configurations seamlessly from disk context. FastAPI intercepts state on pull.

        ui_config = load_clean_json(UI_CONFIG_FILE)
        port = ui_config.get("port", 8443)
        use_https = ui_config.get("https", True)

        if use_https:
            cert_file, key_file = ui_config.get("tls_cert"), ui_config.get("tls_key")
            if not cert_file or not os.path.exists(cert_file): cert_file, key_file = generate_ui_cert()
            server_config = uvicorn.Config("ui_server:app", host="0.0.0.0", port=port, ssl_keyfile=key_file, ssl_certfile=cert_file, log_level="info")
        else:
            server_config = uvicorn.Config("ui_server:app", host="0.0.0.0", port=port, log_level="info")

        server = uvicorn.Server(server_config)
        t = threading.Thread(target=server.run)
        t.start()

        # Monitor state and execution flags continuously
        while t.is_alive():
            if ui_reload_listeners_event.is_set() or ui_reload_configs_event.is_set() or ui_shutdown_event.is_set():
                server.should_exit = True
                # Clean loop control flags without dropping active processes
                if ui_reload_listeners_event.is_set():
                    ui_reload_listeners_event.clear()
                    logging.info("Caught SIGUSR1 inside UI process space. Hot-reloading network port binders...")
                break
            time.sleep(1)
        t.join()
