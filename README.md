# SMTP to Pushover Gateway

This script runs a lightweight, reliable email server (SMTP) that converts incoming emails into push notifications using the [Pushover](https://pushover.net/) service.

It is designed to be a bridge for systems, scripts, network hardware (like routers or NVRs), or legacy software that only know how to send alerts via email. Instead of cluttering your inbox, this gateway catches those emails and instantly pushes them to your phone or smart watch.

## Key Features

* **Web UI Control Panel:** Features a sleek, hot-reloading FASH-stack web interface that manages your configurations securely.
* **No Lost Alerts:** If the internet goes down or the Pushover API rate-limits you, the script saves pending notifications to your hard drive and retries them automatically using exponential backoff until they succeed.
* **Smart Routing:** Route alerts to different Pushover apps or specific devices depending on the `To:` address or the `From:` address of the email. You can use exact strings or powerful Regular Expressions.
* **Image Attachments:** The gateway intercepts image files attached to incoming emails and passes them directly to Pushover (handling API size limits and conflicts automatically).
* **Clean HTML:** Pushover's native HTML support is very messy. This script acts like a mini web browser, stripping out invisible formatting and fixing line breaks so your notifications look perfectly formatted.
* **Secure:** Supports SMTP Authentication (so random devices on your network can't abuse it) and STARTTLS encryption.
* **Hot-Reloading:** Update your routing rules, add new devices, or selectively restart specific listener endpoints without turning the server off.

---

## Requirements and Installation

**Debian / Ubuntu:**
```bash
sudo apt-get update
sudo apt-get install python3 python3-requests python3-cryptography python3-aiosmtpd python3-passlib
# For the Web UI:
sudo apt-get install python3-fastapi python3-uvicorn python3-jinja2 python3-multipart

```

**Alpine Linux:**

```bash
apk update
apk add python3 py3-requests py3-cryptography py3-aiosmtpd py3-passlib
# For the Web UI:
apk add py3-fastapi py3-uvicorn py3-jinja2 py3-multipart

```

*Note: `passlib` is technically optional. It is only required if you want to use secure Linux crypt hashes for your SMTP passwords instead of storing them in plain text.*

---

## Configuration (`GATEWAY_CONFIG`)

The entire core gateway relies on the `config.json` file. To ensure compatibility with the UI Control Panel, the `GATEWAY_CONFIG` environment variable **must** point directly to a file path. **Inline JSON strings and OS environment variable overrides have been disabled.**

**Example:** `GATEWAY_CONFIG=/opt/smtp-pushover/config.json`

### The Web UI Control Panel

The UI service (`ui_server.py`) reads and manages your `config.json`. Once you log in, it provides four main tabs:

1. **Pushover Rules:** Modify your exact-match and regex email routing matrices via a dynamic web interface.
2. **SMTP Server:** Manage SMTP authentication passwords, queue directories, and TCP `listeners` (including port bindings and TLS configurations).
3. **Token Vault:** A secure JSON credential store. Define your raw Pushover tokens here as aliases, and inject those aliases securely into your Pushover Rules tab so the raw tokens are never exposed in the configuration text.
4. **UI Settings:** Toggle HTTPS on or off, adjust the port the UI listens on, or define explicit TLS certificates for the control panel itself (defaults to an auto-generated UUID certificate).

*Note: Saving changes in the UI automatically sends the required OS signals to the background worker to hot-reload the configuration seamlessly.*

---

### Understanding the `config.json` Structure

If you edit the configuration file manually instead of using the UI, here is the structure.
*(Note: Unlike standard JSON, this file supports `//` or `#` comments).*

```json
{
  /* Global routing and fallback rules */
  "pushover": {
    "user": "GLOBAL_PUSHOVER_USER_KEY",
    "token": "GLOBAL_CATCH_ALL_APP_TOKEN",
    "force_plaintext": false,
    "disable_persistence": false,
    "attachments": true,
    "device": "my_iphone", # Optional global device restriction
    "sound": "magic", // Override the default sound
    "alerts@my-domain.com": {
      "match": "to",
      "token": "aSpecificAppTokenForAlerts",
      "disable_persistence": true
    },
    "regex:^server-(alpha|beta|gamma)@local\\.lan$": {
      "match": "from",
      "token": "aSpecificAppTokenForServers",
      "priority": 2,
      "retry": 30,
      "expire": 3600,
      "tags": "server_alert,critical",
      "sound": "siren",
      "attachments": false
    }
  },
  // Infrastructure and server settings
  "smtp": {
    "auth": {
      "camera_system": "my_plaintext_password",
      "router": "$5$rounds=5000$saltstring$hashedpassword..."
    },
    "tls_cert_file": "/etc/ssl/certs/global.pem",
    "tls_key_file": "/etc/ssl/private/global.key",
    "listeners": [
      {
        "bind": "0.0.0.0:25"
      },
      {
        "bind": "0.0.0.0:587",
        "hostname": "secure.gateway.local",
        "starttls": true,
        "tls_cert_file": "/etc/ssl/certs/custom.pem",
        "tls_key_file": "/etc/ssl/private/custom.key"
      }
    ],
    "queue_dir": "/tmp/pushover_queue",
    "hostname": "gateway.local",
    "max_retry_backoff": 21600,
    "loglevel": "info"
  }
}
```

### 1. The "pushover" Section

| Variable | Scope | Description |
| --- | --- | --- |
| `user` | Global / Route | The Pushover user or group key. |
| `token` | Global / Route | Your Pushover application token (or Vault Alias). |
| `match` | Route Only | When to trigger the alert: `to` (recipient), `from` (sender), or `both`. Default is `to`. |
| `regex:` | Routing Key | Prefix your routing key with `regex:` to have the engine parse it as a case-insensitive regular expression instead of an exact string. |
| `force_plaintext` | Global / Route | Set to `true` to skip HTML rendering entirely and use the raw text payload. |
| `disable_persistence` | Global / Route | Set to `true` to prevent saving the notification to the disk queue, making it memory-only. |
| `attachments` | Global / Route | Set to `false` to strip extracted image file attachments from the Pushover payload (Default: `true`). |
| `device` | Global / Route | Send the alert to a specific device name instead of all devices. |
| `sound` | Global / Route | The name of a supported Pushover sound to override your default choice. |
| `tags` | Global / Route | A comma-separated string of arbitrary tags, used to categorize or cancel receipts. |
| `priority` | Global / Route | A number between `-2` (lowest) and `2` (emergency) to adjust alert urgency. |
| `ttl` | Global / Route | Time to Live. Number of seconds the message will stay on the device before being automatically deleted. |
| `retry` | Global / Route | **(Required if `priority` is 2)**. Number of seconds between retries. Must be `>= 30`. |
| `expire` | Global / Route | **(Required if `priority` is 2)**. Number of seconds before the notification gives up retrying. Must be `<= 10800`. |
| `url` | Global / Route | A supplementary URL to show alongside your message (Max: 512 characters). |
| `url_title` | Global / Route | A custom title for the supplementary URL (Max: 100 characters). |

*(Note: The message `title` is also dynamically truncated to a maximum of 250 characters per the API limits).*

### 2. The "smtp" Section

| Variable | Default | Description |
| --- | --- | --- |
| `auth` | (None) | A dictionary mapping usernames to passwords (plain text or Linux crypt hashes). If empty, the server allows anyone to send emails. |
| `listeners` | `0.0.0.0:25` | A list of listener objects. Each object takes a `bind` string and optional overrides (`hostname`, `starttls`, `tls_cert_file`, `tls_key_file`). |
| `queue_dir` | `queue` | Directory path where pending messages are stored on the hard drive before being sent to Pushover. |
| `hostname` | (UUID) | The fallback string used for the SMTP greeting banner and auto-generating missing TLS certificates. |
| `tls_cert_file` | (None) | Global fallback path to your SSL certificate (used for all `starttls` endpoints without explicit certs). |
| `tls_key_file` | (None) | Global fallback path to your SSL private key file. |
| `max_retry_backoff` | `21600` | Maximum wait time (in seconds) between retries if Pushover goes offline (default is 6 hours). |
| `loglevel` | `info` | Terminal output verbosity. Options are `debug`, `info`, `warning`, or `error`. |

---

## Live Reloading (Signals)

If you modify the configuration files via the terminal instead of the UI, you can manually trigger hot reloads via standard OS signals.

| Signal | Command Example | Action |
| --- | --- | --- |
| `SIGUSR2` | `kill -SIGUSR2 <pid>` | Reloads `GATEWAY_CONFIG` to apply new routing rules, tokens, or passwords without dropping network connections. |
| `SIGUSR1` | `kill -SIGUSR1 <pid>` | Re-evaluates all listener endpoints. If a specific listener's configuration (or disk certificate SHA256 hash) has changed, it selectively restarts that listener port. |
| `SIGINT` / `SIGTERM` | `kill -SIGTERM <pid>` | Gracefully shuts the server down, safely writing pending emails to disk before exiting. |
