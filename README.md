# Notification Gateway: SMTP to Pushover & Smarthost Relay

This script runs a lightweight, highly reliable, and modular email server (SMTP) that intercepts incoming emails and dynamically routes them. It converts local alerts into instant push notifications via the [Pushover](https://pushover.net/) API, or seamlessly relays them to upstream SMTP Smarthosts (such as Gmail, SendGrid, or corporate mail servers).

The gateway is built to serve as a bridge for legacy systems, standalone scripts, or local network hardware (routers, smart switches, NVR security cameras) that only know how to send alert data via unencrypted, port 25 plain text. Instead of struggling with modern TLS/Auth requirements on legacy hardware or cluttering your personal inbox, this gateway intercepts those emails, parses them, secures them, and routes them instantly.

---

## Key Features

* **Dual Routing Engine:** Route emails directly to mobile devices via the Pushover API, or forward them to upstream email servers via Smarthost relays.
* **Fully Decoupled Microservice Architecture:** Run the frontend UI panel and the backend core worker on completely separate machines or separate subnets. The system natively scales from a single machine up to standalone headless server pools.
* **Real-Time Event-Driven Monitoring:** The Queue Manager tab utilizes an optimized Server-Sent Events (SSE) stream backed by an internal lock-free Pub/Sub broker. Track failed or delayed messages instantly without polling overhead or thread-lock contention on the mail loop.
* **Fault-Tolerant Disk Persistence:** If the internet drops or an upstream API rate-limits you, the script saves pending notifications to disk and retries them automatically using exponential backoff. Disk persistence can also be completely disabled for pure in-memory, diskless environments.
* **Deep MIME Parsing & HTML Scrubbing:** Acts like a headless browser, actively stripping out invisible inline styling, removing garbage layout elements, and cleaning up line breaks so mobile push notifications look pristine.
* **Regex Rule Matrices:** Route alerts dynamically based on the `To:` or `From:` address. Supports case-insensitive, powerful Regular Expressions for broad pattern catching.
* **Image Attachment Handling:** Automatically extracts image file attachments from incoming emails, handling Pushover API file limits or preserving them for clean Smarthost re-forwarding.
* **Secure Local Verification:** Supports local SMTP Client Authentication restricting gateway usage to authorized network nodes, and dynamically generates on-demand `secp384r1` STARTTLS fallback encryption layers.
* **Zero-Downtime Hot Reloads:** Selective dynamic reloading allows you to rewrite routing rules, modify secrets, alter TLS certificates, or change HTTP listener port bindings on the fly via web requests or POSIX signal triggers (`SIGUSR1`, `SIGUSR2`) without dropping active connections.
* **RFC-Compliant Reverse Proxy Alignment:** Features an optional, user-configurable proxy header interpreter that respects both standard RFC 7239 `Forwarded` strings and legacy `X-Forwarded-For` chains to accurately log originating client IPs.

---

## Requirements and Installation

### Debian / Ubuntu
```bash
sudo apt-get update
sudo apt-get install python3 python3-requests python3-cryptography python3-aiosmtpd python3-passlib python3-aiohttp
# For the Web UI Panel:
sudo apt-get install python3-fastapi python3-uvicorn python3-jinja2 python3-multipart python3-httpx
```

### Alpine Linux

```bash
apk update
apk add python3 py3-requests py3-cryptography py3-aiosmtpd py3-passlib py3-aiohttp
# For the Web UI Panel:
apk add py3-fastapi py3-uvicorn py3-jinja2 py3-multipart py3-httpx
```

---

## Configuration Architecture

The platform splits configuration states into distinct layout objects to keep core infrastructure rules explicitly separated from sensitive API tokens, secrets, and local environment states.

### 1. `ui_config.json` (Control Panel & Connectivity State)

Manages presentation defaults, UI listener ports, proxy rules, and the active local/remote backend linking configuration.

```json
{
  "listeners": [
    {
      "bind": "0.0.0.0:8443",
      "https": true,
      "tls_cert": "",
      "tls_key": ""
    }
  ],
  "timezone": "America/Chicago",
  "date_format": "YYYY-MM-DD HH:mm:ss",
  "relative_time": true,
  "expand_adv": false,
  "trust_proxy": true,
  "backend_mode": "local",
  "local_config_path": "/opt/smtp-pushover/configs/config.json",
  "remote_url": "https://10.0.63.30:6443",
  "remote_secret": "",
  "remote_verify_tls": false,
  "vault_sort": "name_asc",
  "smtp_sort": "name_asc",
  "smarthost_sort": "alias_asc",
  "ui_loglevel": "INFO"
}
```

### 2. `config.json` (Core Routing & Infrastructure)

Dictates inbound TCP binds, user directories, global fallbacks, and address mapping rules.

```json
{
  "smtp": {
    "vault_file": "vault.json",
    "default_route": "pushover",
    "disable_persistence": false,
    "queue_dir": "data/queue",
    "hostname": "gateway.local",
    "max_retry_backoff": 21600,
    "max_backups": 50,
    "loglevel": "INFO",
    "listeners": [
      {
        "bind": "0.0.0.0:25",
        "starttls": false
      },
      {
        "bind": "0.0.0.0:587",
        "hostname": "secure.gateway.local",
        "starttls": true
      }
    ],
    "auth": {
      "security_admin": "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",
      "local_device": "$5$rounds=5000$saltstring$hashedpassword..."
    },
    "api": {
      "enabled": true,
      "bind": "0.0.0.0:6443",
      "secret": "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",
      "tls_cert_file": "",
      "tls_key_file": ""
    }
  },
  "pushover": {
    "user": "FidoUserAlias",
    "token": "GlobalAppAlias",
    "attachments": true,
    "force_plaintext": false
  },
  "smarthost": {
    "globals": {
      "alias": "gmail_relay",
      "force_plaintext": false,
      "disable_attachments": false
    },
    "aliases": {
      "gmail_relay": {
        "hostname": "smtp.gmail.com",
        "port": 587,
        "advertised_hostname": "gateway.local",
        "starttls": true,
        "disable_tls_validation": false,
        "auth": true,
        "username": "my_email@gmail.com",
        "disable_attachments": false,
        "force_plaintext": false
      }
    }
  },
  "routes": {
    "rover@mydomain.com": {
      "match": "to",
      "method": "pushover",
      "token": "RoverAppToken",
      "priority": 1,
      "sound": "dogbark"
    },
    "spot@mydomain.com": {
      "match": "from",
      "method": "smarthost",
      "smarthost_alias": "gmail_relay"
    },
    "regex:^bella-(alert|critical)@local\\.lan$": {
      "match": "both",
      "method": "pushover",
      "token": "BellaEmergencyToken",
      "priority": 2,
      "retry": 30,
      "expire": 3600,
      "sound": "siren"
    }
  }
}
```

### 3. `vault.json` (The Secret Store)

Stores raw, private API tokens and external passwords safely. The Web UI abstracts these parameters out of your core configuration to minimize credential exposure.

```json
{
  "app": {
    "GlobalAppAlias": "azG918237abckd...",
    "RoverAppToken": "aK81237xbcz...",
    "BellaEmergencyToken": "aB19283mknbcv..."
  },
  "user": {
    "FidoUserAlias": "uQ192837poqwe..."
  },
  "smarthost": {
    "gmail_relay": "super_secret_gmail_app_password"
  }
}
```

---

## Routing Constraints Reference

### The `routes` Blueprint

| Variable | Target Scope | Description |
| --- | --- | --- |
| `match` | Route Context | Condition constraint: `to` (recipient matching), `from` (sender validation), or `both`. |
| `method` | Route Context | The targeted relay processor: `pushover` or `smarthost`. |
| `regex:` | Address String | Prefix keys with `regex:` to instruct the routing loop to parse the text as a case-insensitive regular expression instead of an exact string. |

#### Pushover Method Parameters

| Variable | Scope Matrix | Description |
| --- | --- | --- |
| `user` | Global / Route Override | The Pushover destination user or group key (supports secure Vault Aliases). |
| `token` | Global / Route Override | Your verified Pushover application token (supports secure Vault Aliases). |
| `force_plaintext` | Global / Route Override | Disables MIME HTML cleaning entirely and forces the delivery of raw plain text data strings. |
| `attachments` | Global / Route Override | Set to `false` to block and strip media attachments from inbound envelopes. |
| `device` | Global / Route Override | Directs the alert packet to an explicit device name instead of broadcasting to all endpoints. |
| `sound` | Global / Route Override | Changes the push notification audio chime tone to any supported Pushover audio asset. |
| `priority` | Global / Route Override | Integer from `-2` (lowest urgency) up to `2` (emergency notification level). |
| `retry` | Global / Route Override | **(Required if priority is 2)**. Delay period in seconds between retries. Must be `>= 30`. |
| `expire` | Global / Route Override | **(Required if priority is 2)**. Maximum threshold in seconds before giving up. Max: `10800`. |
| `url` | Global / Route Override | A supplementary hyperlink URL appended underneath the body string (Max: `512` characters). |

#### Smarthost Method Parameters

| Variable | Scope Matrix | Description |
| --- | --- | --- |
| `smarthost_alias` | Route Context | The precise name string of the mapping defined inside the `smarthost.aliases` object tree. |
| `force_plaintext` | Global / Route Override | Instructs the relay engine to rebuild the MIME parameters, rendering strictly a clean plain text email envelope. |
| `disable_attachments` | Global / Route Override | Drops all extracted file blocks, rebuilding an unattached email envelope target. |

---

## Real-Time Process Management (Signals)

If you maintain settings directly via an execution terminal rather than the central control panel web interface, you can orchestrates live, zero-downtime hot reloads using standard OS process signaling.

| POSIX Signal | Terminal Trigger Protocol | Internal Infrastructure Lifecycle Impact |
| --- | --- | --- |
| `SIGUSR2` | `kill -SIGUSR2 <pid>` | Re-evaluates configurations from disk. Re-maps your routing tables, updates Vault keys, and dynamic checks if the HTTP Control API parameters shifted, restarting the async background thread loops if a port or token modified. |
| `SIGUSR1` | `kill -SIGUSR1 <pid>` | Audits your network port binders. Evaluates all active TCP sockets or changing certificate hashes, and executes a hot-swap restart of modified sockets without terminating unaffected server channels. |
| `SIGTERM` | `kill -SIGTERM <pid>` | Safely initiates a graceful shutdown loop, flashing standard background memory queues to persistent storage targets before dropping network interfaces. |
