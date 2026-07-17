openListenerModal(mode, idx=null) {
    this.listenerModal.mode = mode; this.listenerModal.idx = idx; this.listenerModal.error = '';
    if(mode === 'add') {
        this.listenerModal.ip = '0.0.0.0'; this.listenerModal.port = 25; this.listenerModal.hostname = '';
        this.listenerModal.starttls = false; this.listenerModal.tls_cert_file = ''; this.listenerModal.tls_key_file = '';
    } else {
        const l = this.smtp.listeners[idx];
        let ip = '0.0.0.0'; let port = 25;
        if(l.bind && l.bind.includes(':')) { const parts = l.bind.split(':'); ip = parts[0]; port = parseInt(parts[1]); }
        this.listenerModal.ip = ip; this.listenerModal.port = port; this.listenerModal.hostname = l.hostname || '';
        this.listenerModal.starttls = l.starttls === true; this.listenerModal.tls_cert_file = l.tls_cert_file || ''; this.listenerModal.tls_key_file = l.tls_key_file || '';
    }
    this.listenerModal.orig = { ip: this.listenerModal.ip, port: this.listenerModal.port, hostname: this.listenerModal.hostname, starttls: this.listenerModal.starttls, tls_cert_file: this.listenerModal.tls_cert_file, tls_key_file: this.listenerModal.tls_key_file };
    this.listenerModal.open = true;
},
saveListenerModal() {
    const ip = this.listenerModal.ip.trim() || '0.0.0.0';
    if (!this.isValidIP(ip)) { this.listenerModal.error = 'Must be a valid IPv4, IPv6, or localhost.'; return; }
    const port = this.listenerModal.port;
    if(!port || port < 1 || port > 65535) { this.listenerModal.error = 'Port must be between 1 and 65535.'; return; }
    const bind = ip + ':' + port; const obj = { bind: bind, starttls: this.listenerModal.starttls };
    if(this.listenerModal.hostname.trim()) obj.hostname = this.listenerModal.hostname.trim();
    if(this.listenerModal.starttls) {
        if(this.listenerModal.tls_cert_file.trim()) obj.tls_cert_file = this.listenerModal.tls_cert_file.trim();
        if(this.listenerModal.tls_key_file.trim()) obj.tls_key_file = this.listenerModal.tls_key_file.trim();
    }
    if(this.listenerModal.mode === 'add') { this.smtp.listeners.push(obj); } else { this.smtp.listeners[this.listenerModal.idx] = obj; }
    this.listenerModal.open = false;
},
clearListenerModal() {
    this.listenerModal.ip = this.listenerModal.orig.ip; this.listenerModal.port = this.listenerModal.orig.port; this.listenerModal.hostname = this.listenerModal.orig.hostname;
    this.listenerModal.starttls = this.listenerModal.orig.starttls; this.listenerModal.tls_cert_file = this.listenerModal.orig.tls_cert_file; this.listenerModal.tls_key_file = this.listenerModal.orig.tls_key_file;
    this.listenerModal.error = '';
},
openUiListenerModal(mode, idx=null) {
    this.uiListenerModal.mode = mode; this.uiListenerModal.idx = idx; this.uiListenerModal.error = '';
    if(mode === 'add') {
        this.uiListenerModal.ip = '0.0.0.0'; this.uiListenerModal.port = 8443;
        this.uiListenerModal.https = true; this.uiListenerModal.tls_cert = ''; this.uiListenerModal.tls_key = '';
    } else {
        const l = this.uiListeners[idx];
        let ip = '0.0.0.0'; let port = 8443;
        if(l.bind && l.bind.includes(':')) { const parts = l.bind.split(':'); ip = parts[0]; port = parseInt(parts[1]); }
        this.uiListenerModal.ip = ip; this.uiListenerModal.port = port;
        this.uiListenerModal.https = l.https === true;
        this.uiListenerModal.tls_cert = l.tls_cert || ''; this.uiListenerModal.tls_key = l.tls_key || '';
    }
    this.uiListenerModal.orig = { ip: this.uiListenerModal.ip, port: this.uiListenerModal.port, https: this.uiListenerModal.https, tls_cert: this.uiListenerModal.tls_cert, tls_key: this.uiListenerModal.tls_key };
    this.uiListenerModal.open = true;
},
saveUiListenerModal() {
    const ip = this.uiListenerModal.ip.trim() || '0.0.0.0';
    if (!this.isValidIP(ip)) { this.uiListenerModal.error = 'Must be a valid IPv4, IPv6, or localhost.'; return; }
    const port = this.uiListenerModal.port;
    if(!port || port < 1 || port > 65535) { this.uiListenerModal.error = 'Port must be between 1 and 65535.'; return; }
    const bind = ip + ':' + port; const obj = { bind: bind, https: this.uiListenerModal.https };
    if(this.uiListenerModal.https) {
        if(this.uiListenerModal.tls_cert.trim()) obj.tls_cert = this.uiListenerModal.tls_cert.trim();
        if(this.uiListenerModal.tls_key.trim()) obj.tls_key = this.uiListenerModal.tls_key.trim();
    }
    if(this.uiListenerModal.mode === 'add') { this.uiListeners.push(obj); } else { this.uiListeners[this.uiListenerModal.idx] = obj; }
    this.uiListenerModal.open = false;
},
clearUiListenerModal() {
    this.uiListenerModal.ip = this.uiListenerModal.orig.ip; this.uiListenerModal.port = this.uiListenerModal.orig.port; this.uiListenerModal.https = this.uiListenerModal.orig.https;
    this.uiListenerModal.tls_cert = this.uiListenerModal.orig.tls_cert; this.uiListenerModal.tls_key = this.uiListenerModal.orig.tls_key;
    this.uiListenerModal.error = '';
},

get hasListenerModalChanges() {
    const m = this.listenerModal; const o = m.orig;
    return m.ip !== o.ip || String(m.port) !== String(o.port) || m.hostname !== o.hostname || m.starttls !== o.starttls || m.tls_cert_file !== o.tls_cert_file || m.tls_key_file !== o.tls_key_file;
},
get canSaveListenerModal() {
    if (!this.hasListenerModalChanges) return false;
    const m = this.listenerModal;
    if (!m.port || m.port < 1 || m.port > 65535) return false;
    const ip = m.ip.trim() || '0.0.0.0';
    return this.isValidIP(ip);
},
get hasUiListenerModalChanges() {
    const m = this.uiListenerModal; const o = m.orig;
    return m.ip !== o.ip || String(m.port) !== String(o.port) || m.https !== o.https || m.tls_cert !== o.tls_cert || m.tls_key !== o.tls_key;
},
get canSaveUiListenerModal() {
    if (!this.hasUiListenerModalChanges) return false;
    const m = this.uiListenerModal;
    if (!m.port || m.port < 1 || m.port > 65535) return false;
    const ip = m.ip.trim() || '0.0.0.0';
    return this.isValidIP(ip);
},

deleteUiListener(idx) {
    if (this.uiListeners.length <= 1) {
        this.alertModal.title = 'Cannot Remove Listener';
        this.alertModal.message = 'You must have at least one UI listener configured to maintain access to the web panel.';
        this.alertModal.open = true;
        return;
    }

    const targetListener = this.uiListeners[idx];
    const bindPort = targetListener.bind.includes(':') ? targetListener.bind.split(':')[1] : '8443';

    if (parseInt(bindPort) === this.activeUiPort && this.activeUiPort > 0) {
        this.alertModal.title = 'Active Listener';
        this.alertModal.message = 'You cannot remove the specific network listener that your current session is actively routed through.';
        this.alertModal.open = true;
        return;
    }

    this.uiListeners.splice(idx, 1);
},
