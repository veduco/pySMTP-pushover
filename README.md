# SMTP to Pushover Gateway

This script runs a lightweight, reliable email server (SMTP) that converts incoming emails into push notifications using the [Pushover](https://pushover.net/) service.

It is designed to be a bridge for systems, scripts, network hardware (like routers or NVRs), or legacy software that only know how to send alerts via email. Instead of cluttering your inbox, this gateway catches those emails and instantly pushes them to your phone or smart watch.

## Key Features

* **No Lost Alerts:** If the internet goes down or the Pushover API rate-limits you, the script saves pending notifications to your hard drive and retries them automatically using exponential backoff until they succeed.
* **Smart Routing:** Route alerts to different Pushover apps or specific devices depending on the `To:` address or the `From:` address of the email.
* **Clean HTML:** Pushover's native HTML support is very messy. This script acts like a mini web browser, stripping out invisible formatting and fixing line breaks so your notifications look perfectly formatted.
* **Secure:** Supports SMTP Authentication (so random devices on your network can't abuse it) and STARTTLS encryption.
* **Hot-Reloading:** Update your routing rules, add new devices, or swap TLS certificates without turning the server off or dropping active connections.

---

## Requirements and Installation

You will need Python 3 installed on your system.

**Debian / Ubuntu:**
```bash
sudo apt-get update
sudo apt-get install python3 python3-pip python3-requests python3-cryptography python3-aiosmtpd python3-passlib
```

**Alpine Linux:**

```bash
apk update
apk add python3 py3-pip py3-requests py3-cryptography py3-aiosmtpd py3-passlib
```

*Note: `passlib` is technically optional. It is only required if you want to use secure Linux crypt hashes for your SMTP passwords instead of storing them in plain text.*

---

## Configuration (`GATEWAY_CONFIG`)

The entire gateway is configured using a single environment variable named `GATEWAY_CONFIG`.

You can set this variable to either:

1. **A file path** pointing to a JSON file (e.g., `GATEWAY_CONFIG=config.json`). *Highly recommended.*
2. **A raw JSON string** containing your settings.

### Inline Comments

Unlike standard JSON, this configuration file supports comments. You can use `//`, `#`, or `/* */`.
**Rule:** Comments must either be at the very beginning of a line, or have at least one space before them.

### Example Configuration File

Here is a complete example of a `config.json` file. It is broken into two main sections: `pushover` (where alerts go) and `smtp` (how the server runs).

```json
{
  /* Global routing and fallback rules */
  "pushover": {
    "user": "uYourGlobalUserKeyHere",
    "token": "aYourGlobalAppTokenHere",
    "force_plaintext": false,
    "disable_persistence": false,
    "device": "my_iphone", # Optional global device restriction
    "sound": "magic", // Override the default sound
    "alerts@my-domain.com": {
      "match": "to",
      "token": "aSpecificAppTokenForAlerts",
      "disable_persistence": true
    },
    "backup-server@local.network": {
      "match": "from",
      "user": "uADifferentUserKey",
      "token": "aSpecificAppTokenForBackups",
      "force_plaintext": true, // Ignores HTML formatting for this sender
      "device": "desktop_pc",
      "priority": 1,
      "url": "twitter://direct_message?screen_name=someuser",
      "url_title": "Reply to @someuser"
    }
  },
  // Infrastructure and server settings
  "smtp": {
    "auth": {
      "camera_system": "my_plaintext_password",
      "router": "$5$rounds=5000$saltstring$hashedpassword..."
    },
    "listeners": [
      {
        "bind": "0.0.0.0:25"
      },
      {
        "bind": "0.0.0.0:587",
        "starttls": true,
        "tls_cert_file": "/etc/ssl/certs/mail.pem",
        "tls_key_file": "/etc/ssl/private/mail.key"
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

This section controls who receives the push notifications. You can define global fallback variables at the top of the block, and then define specific email addresses with their own custom variables below.

| Variable | Scope | Description |
| --- | --- | --- |
| `user` | Global / Route | The Pushover user or group key. |
| `token` | Global / Route | Your Pushover application token. |
| `match` | Route Only | When to trigger the alert: `to` (recipient), `from` (sender), or `both`. Default is `to`. |
| `force_plaintext` | Global / Route | Set to `true` to skip HTML rendering entirely and use the raw text payload. |
| `disable_persistence` | Global / Route | Set to `true` to prevent saving the notification to the disk queue, making it memory-only. |
| `device` | Global / Route | Send the alert to a specific device name instead of all devices. |
| `sound` | Global / Route | The name of a supported Pushover sound to override your default choice. |
| `priority` | Global / Route | A number between `-2` (lowest) and `2` (emergency) to adjust alert urgency. |
| `ttl` | Global / Route | Time to Live. Number of seconds the message will stay on the device before being automatically deleted. |
| `url` | Global / Route | A supplementary URL to show alongside your message. |
| `url_title` | Global / Route | A custom title for the supplementary URL. |

### 2. The "smtp" Section

This section controls the server infrastructure. All of these settings are optional and have safe defaults.

| Variable | Default | Description |
| --- | --- | --- |
| `auth` | (None) | A dictionary mapping usernames to passwords (plain text or Linux crypt hashes). If empty, the server allows anyone to send emails. |
| `listeners` | `0.0.0.0:25` | A list of listener objects. Each object takes a `bind` string and optional STARTTLS parameters (`starttls`, `tls_cert_file`, `tls_key_file`). |
| `queue_dir` | `queue` | Directory path where pending messages are stored on the hard drive before being sent to Pushover. |
| `hostname` | (UUID) | The name the server calls itself, used when auto-generating fallback certificates. |
| `max_retry_backoff` | `21600` | Maximum wait time (in seconds) between retries if Pushover goes offline (default is 6 hours). |
| `loglevel` | `info` | Terminal output verbosity. Options are `debug`, `info`, `warning`, or `error`. |

---

## Environment Variable Overrides

If you prefer using OS environment variables (like in a `docker-compose.yml` file), you can override infrastructure settings globally. If a setting exists in both the JSON file and an environment variable, the **environment variable always wins**.

*Note on Listeners: If you use any of the four listener environment variables below, they will override the entire JSON `listeners` array and configure a single endpoint.*

| Environment Variable | JSON Equivalent | Example |
| --- | --- | --- |
| `QUEUE_DIR` | `smtp` -> `queue_dir` | `/var/lib/pushover_queue` |
| `LISTEN` | `smtp` -> `listeners` -> `bind` | `127.0.0.1:2525` |
| `STARTTLS` | `smtp` -> `listeners` -> `starttls` | `true` |
| `TLS_CERT_FILE` | `smtp` -> `listeners` -> `tls_cert_file` | `/etc/ssl/certs/mail.pem` |
| `TLS_KEY_FILE` | `smtp` -> `listeners` -> `tls_key_file` | `/etc/ssl/private/mail.key` |
| `HOSTNAME` | `smtp` -> `hostname` | `mail.example.com` |
| `FORCE_PLAINTEXT` | `pushover` -> `force_plaintext` | `true` |
| `DISABLE_PERSISTENCE` | `pushover` -> `disable_persistence` | `true` |
| `MAX_RETRY_BACKOFF` | `smtp` -> `max_retry_backoff` | `3600` |
| `LOGLEVEL` | `smtp` -> `loglevel` | `debug` |

---

## Live Reloading (Signals)

If you need to change your configuration while the server is running, you can send signals to the process to reload settings without dropping active email connections.

| Signal | Command Example | Action |
| --- | --- | --- |
| `SIGUSR2` | `kill -SIGUSR2 <pid>` | Reloads `GATEWAY_CONFIG` to apply new routing rules, tokens, or passwords without dropping connections. |
| `SIGUSR1` | `kill -SIGUSR1 <pid>` | Restarts the network listener to apply a new `bind` port or fresh TLS certificates. |
| `SIGINT` / `SIGTERM` | `kill -SIGTERM <pid>` | Gracefully shuts the server down, safely writing pending emails to disk before exiting. |
