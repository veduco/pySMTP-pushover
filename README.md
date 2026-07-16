# SMTP to Pushover & Smarthost Gateway

## Overview

Welcome to the **SMTP to Pushover & Smarthost Gateway**! This system bridges traditional infrastructure alerting with modern mobile notification environments and smart-routing capabilities. If you have legacy servers, network switches, or custom monitoring daemons that only know how to send transactional emails, this gateway intercepts those mail streams and processes them intelligently.

The platform features a high-performance backend mail engine coupled with a sleek, real-time web administration console. It handles outbound alerts using a flexible dual-delivery execution pipeline:

* **Pushover Delivery Engine:** Transforms standard email headers and MIME multipart attachments into rich native mobile notifications via the Pushover API.
* **Smarthost SMTP Relay:** Dynamically reroutes non-critical text logs or corporate traffic to secondary upstream smarthost mail servers.

---

## Environment & Minimum Version Requirements

To run this platform exclusively via native operating system package managers without utilizing `pip`, your environment must meet the following minimum baseline constraints.

### Core Software Baselines

* **Minimum Python Version:** `Python >= 3.11` (Required for modern async task handling, native exception groups, and optimal ASGI server workers).
* **Minimum Cryptography Version:** `cryptography >= 41.0.0` (Required for secure SECP384R1 elliptic curve generation loops used in self-signed TLS fallback provisioning).
* **Minimum Gateway Library Versions:** `aiosmtpd >= 1.4.4`, `aiosmtplib >= 2.0.0`, `fastapi >= 0.100.0`, `uvicorn >= 0.22.0`.

### Minimum OS Distributions

The following operating system versions are required to ensure the software dependencies listed above are natively available out of their upstream package repositories:

* **Debian GNU/Linux:** `Debian 12 (Bookworm)` or newer.
* **Alpine Linux:** `Alpine 3.19` or newer (Core deployment configurations are verified up through `Alpine 3.24`).
* **Red Hat Enterprise Linux (RHEL):** `RHEL 9` / `Rocky Linux 9` / `AlmaLinux 9` or newer (Requires the **EPEL** repository enabled).

---

## Native Package Installation

Run the appropriate command block for your target operating system distribution to install all dependencies grouped by service type.

### 1. Debian / Ubuntu Setup (`apt`)

```bash
# Update local package indexes
sudo apt-get update

# Install Backend Service Dependencies
sudo apt-get install -y python3 python3-aiosmtpd python3-cryptography python3-passlib python3-httpx python3-aiosmtplib python3-fastapi python3-uvicorn python3-multipart

# Install Frontend Service Dependencies
sudo apt-get install -y python3 python3-fastapi python3-uvicorn python3-jinja2 python3-multipart python3-cryptography python3-urllib3 python3-httpx
```
### 2. Alpine Linux Setup (`apk`)

```bash
# Update local package indexes
apk update

# Install Backend Service Dependencies (Native Py3 Packages)
apk add py3-cryptography py3-aiosmtpd py3-passlib py3-httpx py3-aiosmtplib py3-fastapi py3-uvicorn py3-multipart

# Install Frontend Service Dependencies (Native Py3 Packages)
apk add py3-fastapi py3-uvicorn py3-jinja2 py3-multipart py3-cryptography py3-urllib3 py3-httpx
```
### 3. Red Hat Enterprise Linux / Rocky Linux (`dnf`)

```bash
# Enable the Extra Packages for Enterprise Linux (EPEL) repository
sudo dnf install -y epel-release
sudo dnf config-manager --set-enabled crb

# Install Backend Service Dependencies
sudo dnf install -y python3 python3-aiosmtpd python3-cryptography python3-passlib python3-httpx python3-aiosmtplib python3-fastapi python3-uvicorn python3-multipart

# Install Frontend Service Dependencies
sudo dnf install -y python3 python3-fastapi python3-uvicorn python3-jinja2 python3-multipart python3-cryptography python3-urllib3 python3-httpx
```
---

## Core Architecture & Features

### 1. Robust Delivery Pipeline

* **Asynchronous Queue Worker:** All incoming emails are parsed into structured payloads and instantly committed to an on-disk persistent queue directory (`data/queue`). Delivery tasks are managed by 5 concurrent worker loops using exponential backoff routines to guarantee delivery even during network drops.
* **Pushover Compliance Tuning:** The gateway enforces a strict 1-connection maximum pool when speaking to Pushover endpoints, perfectly matching upstream API limits and avoiding connection drops.
* **Zero-Downtime Signal Handling:** The backend listens for system signals (`SIGUSR2`) to execute a full hot-reload of configurations, filters, and credentials entirely in memory. It monitors listener arrays and dynamically hooks new ports or rotates TLS contexts without interrupting active client processes or dropping socket connections.

### 2. Control API Microservice

The backend runs an internal, token-authenticated FastAPI engine that strictly operates out of a protected RAM cache. When configurations are queried or updated via the Web UI, data structures are isolated using deep-copy logic to prevent raw memory mutations or security boundary pollution.

* **SSE Monitoring Stream:** Exposes a secure Server-Sent Events (SSE) telemetry line, allowing external applications or dashboards to watch queue additions, modifications, and error unlinking events live.
* **Self-Signed Fallbacks:** If custom TLS certificates are missing, the microservice automatically generates memory-bound certificates on the fly to guarantee encryption across the wire.

### 3. Enterprise Frontend Web Console

* **Dual UI Linking Modes:** The UI can function in **Local Mode** (direct filesystem reads/writes for co-located deployments) or **Remote Mode** (acting as an authenticated proxy pipeline talking across secure networks to an un-routed server core).
* **Smart Configuration Diff Engine:** Before any change hits the disk, the frontend generates a precise, interactive delta breakdown. It converts metadata arrays into strict object dictionaries to eliminate false alarms from array index shifting, masks sensitive values like keys and passwords, and prints friendly descriptive labels like `[Alias] BellaToken` or `[Deleted]`.
* **Responsive Mobile Interface:** Built with a fully flexible swipeable rail architecture, letting you control alerts, reorder route filters, manage users, and scrub delivery spools natively from any viewport.

---

## Configuration Specification

The gateway relies on three independent files to coordinate system boundaries. Below are pristine, production-ready schemas to map routing logic:

### `config.json`

```json
{
  "smtp": {
    "vault_file": "vault.json",
    "default_route": "pushover",
    "disable_persistence": false,
    "queue_dir": "data/queue",
    "hostname": "smtp.pushover.gateway",
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
        "starttls": true,
        "tls_cert_file": "/etc/ssl/certs/gateway.pem",
        "tls_key_file": "/etc/ssl/private/gateway.key"
      }
    ],
    "auth": {
      "charlie": "8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918",
      "rover": "37747f2841d83a1a5c4d320b9911e3b5df54b1d6e15dfb167a9c873fc4bb8a81"
    }
  },
  "pushover": {
    "token": "fido_app",
    "user": "max_user",
    "attachments": true,
    "force_plaintext": false
  },
  "smarthost": {
    "globals": {
      "alias": "bella_relay",
      "force_plaintext": false,
      "disable_attachments": false
    },
    "aliases": {
      "bella_relay": {
        "hostname": "smtp.sendgrid.net",
        "port": 587,
        "starttls": true,
        "auth": true,
        "username": "bella_relay_user@local.net"
      }
    }
  },
  "routes": {
    "fido@domain.com": {
      "match": "from",
      "method": "pushover",
      "token": "fido_app",
      "user": "max_user",
      "priority": "1",
      "sound": "climb"
    },
    "regex:^.*@buddy\\.net$": {
      "match": "to",
      "method": "smarthost",
      "smarthost_alias": "bella_relay",
      "force_plaintext": true,
      "disable_attachments": true
    }
  }
}
```
### `ui_config.json`

```json
{
  "listeners": [
    {
      "bind": "0.0.0.0:8443",
      "https": true,
      "tls_cert": "/etc/ssl/certs/ui.pem",
      "tls_key": "/etc/ssl/private/ui.key"
    }
  ],
  "timezone": "America/New_York",
  "date_format": "YYYY-MM-DD HH:mm:ss",
  "relative_time": true,
  "expand_adv": false,
  "vault_sort": "name_asc",
  "smtp_sort": "name_asc",
  "smarthost_sort": "alias_asc",
  "ui_loglevel": "INFO",
  "backend_mode": "local",
  "local_config_path": "config.json"
}
```
### `vault.json`

```json
{
  "app": {
    "fido_app": {
      "token": "azQxMzU3OTI0NjgxOTUzNzU5MjE0Njgx",
      "epoch": 1784160000
    }
  },
  "user": {
    "max_user": {
      "token": "dXNlcjI0NjgxOTUzNzU5MjE0NjgxOTUzNz",
      "epoch": 1784160000
    }
  },
  "smarthost": {
    "bella_relay": {
      "token": "cGFzc3dvcmQxMjM0NTY3ODkwMTIzNDU2",
      "epoch": 1784160000
    }
  }
}
```
---

## Usage & Process Management

The architecture is built for independent process execution. You can coordinate runtime operations directly or integrate them into a custom system supervisor hook:

### 1. Launching the Mail Core (Backend Daemon)

Execute the primary delivery module from your terminal pool:

```bash
python3 run_backend.py
```
Upon cold boot, the worker scans your persistent state directories, binds defined TCP listener ports, establishes background queue thread managers, and waits silently for inbound connections.

### 2. Launching the Web Interface (Frontend Panel)

Spin up the configuration panel to map routing changes:

```bash
python3 run_frontend.py
```
The interface reads your baseline parameters, attaches a socket pool for Control API proxy maps, and stands up an intuitive platform configuration environment.

> **Security Note:** Both scripts automatically audit certificate configurations. If custom pem files are missing or inaccessible, the processes safely spin up temporary, self-signed cryptography assets inside `/tmp` to enforce end-to-end transport layer security.
