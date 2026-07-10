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

Unlike standard JSON, this configuration file supports comments! You can use `//`, `#`, or `/* */`.
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
    "device": "my_iphone", # Optional global device restriction
    "alerts@my-domain.com": {
      "match": "to",
      "token": "aSpecificAppTokenForAlerts"
    },
    "backup-server@local.network": {
      "match": "from",
      "user": "uADifferentUserKey",
      "token": "aSpecificAppTokenForBackups",
      "force_plaintext": true, // Ignores HTML formatting for this sender
      "device": "desktop_pc"
    }
  },
  // Infrastructure and server settings
  "smtp": {
    "auth": {
      "camera_system": "my_plaintext_password",
      "router": "$5$rounds=5000$saltstring$hashedpassword..."
    },
    "listen": "0.0.0.0:25",
    "queue_dir": "/tmp/pushover_queue",
    "enable_starttls": false,
    "max_retry_backoff": 21600,
    "loglevel": "info"
  }
}
```

### 1. The "pushover" Section

This section controls who receives the push notifications.

* **Global Fallbacks (`user`, `token`, `device`):** If you define these at the very top of the `pushover` block, any email sent to an address that isn't explicitly mapped will fall back to using these keys.
* **Email Mappings:** You can define specific email addresses. Inside each address, you must provide a `token` (and optionally a `user` or `device` if you want to override the global settings).
* **The `match` rule:**
* `"to"` (Default): Sends the notification if the email was sent *to* this address.
* `"from"`: Sends the notification if the email was sent *by* this address.
* `"both"`: Sends the notification if the address shows up in either the sender or receiver fields.


* **`force_plaintext`:** Pushover tries to render HTML emails. If an email looks terrible, you can set `"force_plaintext": true` either globally or on a specific email address. This tells the script to ignore the HTML entirely and use the raw text payload.

### 2. The "smtp" Section

This section controls the server infrastructure. All of these settings are optional and have safe defaults.

* **`auth`:** A dictionary of usernames and passwords. If you leave this empty, the server will allow anyone to send emails through it without a password. Passwords can be plain text, or you can use `mkpasswd -m sha-256` on a Linux command line to generate secure hashes.
* **`listen`:** The IP address and port to run the server on. (Default: `0.0.0.0:25`).
* **`queue_dir`:** Where to save messages on the hard drive while they are waiting to be sent to Pushover. (Default: creates a `queue` folder next to the script).
* **`enable_starttls`:** Set to `true` to allow encrypted connections.
* **`tls_cert_file` & `tls_key_file`:** Paths to your SSL certificates. If you enable STARTTLS but don't provide these files, the script will automatically generate its own self-signed certificates on the fly.
* **`hostname`:** The name the server calls itself. Used when auto-generating certificates.
* **`max_retry_backoff`:** If Pushover is down, the script waits longer and longer between each retry. This is the maximum wait time in seconds. (Default: `21600` seconds / 6 hours).
* **`loglevel`:** How much text to print to the console. Options are `debug`, `info`, `warning`, or `error`. (Default: `info`).

---

## Environment Variable Overrides

If you prefer using OS environment variables (like in a `docker-compose.yml` file), you can override any of the infrastructure settings defined in the `smtp` block, as well as the global plaintext flag.

If a setting exists in both the JSON file and an environment variable, the **environment variable always wins**.

Supported override variables:

* `QUEUE_DIR`
* `LISTEN` (e.g., `127.0.0.1:2525`)
* `ENABLE_STARTTLS` (`true` or `false`)
* `TLS_CERT_FILE`
* `TLS_KEY_FILE`
* `HOSTNAME`
* `FORCE_PLAINTEXT` (`true` or `false`)
* `MAX_RETRY_BACKOFF` (in seconds)
* `LOGLEVEL`

---

## Live Reloading (Signals)

If you need to change your configuration while the server is running, you can send signals to the process to reload settings without dropping active email connections.

* **`kill -SIGUSR2 <pid>`:** Reloads your `GATEWAY_CONFIG` file. Use this if you added new email addresses, updated Pushover tokens, changed a password, or adjusted the logging level.
* **`kill -SIGUSR1 <pid>`:** Restarts the network listener. Use this if you changed the `listen` port/IP, updated your SSL certificate files, or toggled STARTTLS.
* **`kill -SIGINT <pid>` / `SIGTERM`:** Gracefully shuts the server down. It will stop accepting new emails and wait for the background worker to finish saving any pending messages to disk before exiting.
