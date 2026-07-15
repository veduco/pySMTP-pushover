openVaultModal(type) {
    this.vaultModal.type = type;
    this.vaultModal.name = '';
    this.vaultModal.token = '';
    this.vaultModal.showToken = false;
    this.vaultModal.error = '';
    this.vaultModal.orig = { name: '', token: '' };
    this.vaultModal.open = true;
},
saveVaultModal() {
    const nName = this.vaultModal.name.trim();
    const nTok = this.vaultModal.token.trim();
    if(!nName || !nTok) { this.vaultModal.error = "Alias Name and Token are required."; return; }

    const target = this.vaultModal.type === 'app' ? this.vaultApp : this.vaultUser;
    const existingIdx = target.findIndex(x => x.name === nName);

    if(existingIdx >= 0) { target[existingIdx].token = nTok; target[existingIdx].epoch = Math.floor(Date.now() / 1000); }
    else { target.push({name: nName, token: nTok, epoch: Math.floor(Date.now() / 1000)}); }

    if(this.vaultModal.type === 'app' && !this.vaultAppAliases.includes(nName)) this.vaultAppAliases.push(nName);
    if(this.vaultModal.type === 'user' && !this.vaultUserAliases.includes(nName)) this.vaultUserAliases.push(nName);
    this.vaultModal.open = false;
},
clearVaultModal() {
    this.vaultModal.name = this.vaultModal.orig.name;
    this.vaultModal.token = this.vaultModal.orig.token;
},

openSmtpUserModal() {
    this.smtpUserModal.name = '';
    this.smtpUserModal.password = '';
    this.smtpUserModal.showToken = false;
    this.smtpUserModal.error = '';
    this.smtpUserModal.orig = { name: '', password: '' };
    this.smtpUserModal.open = true;
},
saveSmtpUserModal() {
    const u = this.smtpUserModal.name.trim();
    const p = this.smtpUserModal.password.trim();
    if(!u || !p) { this.smtpUserModal.error = "Username and Password are required."; return; }
    this.smtp.auth[u] = "RAW:" + p;
    this.smtp_meta[u] = Math.floor(Date.now() / 1000);
    this.smtpUserModal.open = false;
},
clearSmtpUserModal() {
    this.smtpUserModal.name = this.smtpUserModal.orig.name;
    this.smtpUserModal.password = this.smtpUserModal.orig.password;
},

openEditModal(type, name, subType='') {
    this.editModal.type = type;
    this.editModal.subType = subType;
    this.editModal.name = name;
    this.editModal.value = '';
    this.editModal.showToken = false;
    this.editModal.orig = { value: '' };
    this.editModal.open = true;
},
saveEditModal() {
    if(!this.editModal.value) return;
    const v = this.editModal.value.trim();
    if(!v) return;
    if(this.editModal.type === 'smtp') { this.smtp.auth[this.editModal.name] = "RAW:" + v; this.smtp_meta[this.editModal.name] = Math.floor(Date.now() / 1000); }
    else if(this.editModal.type === 'vault') {
        const target = this.editModal.subType === 'app' ? this.vaultApp : this.vaultUser;
        const idx = target.findIndex(x => x.name === this.editModal.name);
        if(idx !== -1) { target[idx].token = v; target[idx].epoch = Math.floor(Date.now() / 1000); }
    }
    this.editModal.open = false;
},
clearEditModal() {
    this.editModal.value = this.editModal.orig.value;
},

openListenerModal(mode, idx=null) {
    this.listenerModal.mode = mode;
    this.listenerModal.idx = idx;
    this.listenerModal.error = '';
    if(mode === 'add') {
        this.listenerModal.ip = '0.0.0.0'; this.listenerModal.port = 25; this.listenerModal.hostname = '';
        this.listenerModal.starttls = false; this.listenerModal.tls_cert_file = ''; this.listenerModal.tls_key_file = '';
    } else {
        const l = this.smtp.listeners[idx];
        let ip = '0.0.0.0'; let port = 25;
        if(l.bind && l.bind.includes(':')) {
            const parts = l.bind.split(':');
            ip = parts[0]; port = parseInt(parts[1]);
        }
        this.listenerModal.ip = ip; this.listenerModal.port = port; this.listenerModal.hostname = l.hostname || '';
        this.listenerModal.starttls = l.starttls === true; this.listenerModal.tls_cert_file = l.tls_cert_file || ''; this.listenerModal.tls_key_file = l.tls_key_file || '';
    }
    this.listenerModal.orig = {
        ip: this.listenerModal.ip, port: this.listenerModal.port, hostname: this.listenerModal.hostname,
        starttls: this.listenerModal.starttls, tls_cert_file: this.listenerModal.tls_cert_file, tls_key_file: this.listenerModal.tls_key_file
    };
    this.listenerModal.open = true;
},
saveListenerModal() {
    const ip = this.listenerModal.ip.trim() || '0.0.0.0';
    if (!this.isValidIP(ip)) { this.listenerModal.error = 'Must be a valid IPv4, IPv6, or localhost.'; return; }

    const port = this.listenerModal.port;
    if(!port || port < 1 || port > 65535) { this.listenerModal.error = 'Port must be between 1 and 65535.'; return; }

    const bind = ip + ':' + port;
    const obj = { bind: bind, starttls: this.listenerModal.starttls };
    if(this.listenerModal.hostname.trim()) obj.hostname = this.listenerModal.hostname.trim();
    if(this.listenerModal.starttls) {
        if(this.listenerModal.tls_cert_file.trim()) obj.tls_cert_file = this.listenerModal.tls_cert_file.trim();
        if(this.listenerModal.tls_key_file.trim()) obj.tls_key_file = this.listenerModal.tls_key_file.trim();
    }
    if(this.listenerModal.mode === 'add') { this.smtp.listeners.push(obj); }
    else { this.smtp.listeners[this.listenerModal.idx] = obj; }
    this.listenerModal.open = false;
},
clearListenerModal() {
    this.listenerModal.ip = this.listenerModal.orig.ip;
    this.listenerModal.port = this.listenerModal.orig.port;
    this.listenerModal.hostname = this.listenerModal.orig.hostname;
    this.listenerModal.starttls = this.listenerModal.orig.starttls;
    this.listenerModal.tls_cert_file = this.listenerModal.orig.tls_cert_file;
    this.listenerModal.tls_key_file = this.listenerModal.orig.tls_key_file;
    this.listenerModal.error = '';
},

openSmarthostModal(mode, alias='') {
    this.smarthostModal.mode = mode;
    this.smarthostModal.oldAlias = alias;
    this.smarthostModal.error = '';
    this.smarthostModal.showPass = false;
    if(mode === 'add') {
        this.smarthostModal.alias = ''; this.smarthostModal.hostname = ''; this.smarthostModal.advertised_hostname = ''; this.smarthostModal.port = 25;
        this.smarthostModal.starttls = false; this.smarthostModal.disable_tls_validation = false; this.smarthostModal.auth = false;
        this.smarthostModal.username = ''; this.smarthostModal.password = ''; this.smarthostModal.disable_attachments = false; this.smarthostModal.force_plaintext = false;
    } else {
        const sh = this.smarthosts[alias];
        this.smarthostModal.alias = alias; this.smarthostModal.hostname = sh.hostname || ''; this.smarthostModal.advertised_hostname = sh.advertised_hostname || ''; this.smarthostModal.port = parseInt(sh.port) || 25;
        this.smarthostModal.starttls = sh.starttls === true; this.smarthostModal.disable_tls_validation = sh.disable_tls_validation === true; this.smarthostModal.auth = sh.auth === true;
        this.smarthostModal.username = sh.username || ''; this.smarthostModal.password = '';
        this.smarthostModal.disable_attachments = sh.disable_attachments === true; this.smarthostModal.force_plaintext = sh.force_plaintext === true;
    }
    this.smarthostModal.orig = {
        alias: this.smarthostModal.alias, hostname: this.smarthostModal.hostname, advertised_hostname: this.smarthostModal.advertised_hostname, port: this.smarthostModal.port,
        starttls: this.smarthostModal.starttls, disable_tls_validation: this.smarthostModal.disable_tls_validation, auth: this.smarthostModal.auth,
        username: this.smarthostModal.username, password: this.smarthostModal.password, disable_attachments: this.smarthostModal.disable_attachments, force_plaintext: this.smarthostModal.force_plaintext
    };
    this.smarthostModal.open = true;
},
saveSmarthostModal() {
    const alias = this.smarthostModal.alias.trim();
    if(!alias) { this.smarthostModal.error = 'Alias Name is required.'; return; }
    if(this.smarthostModal.mode === 'add' && this.smarthosts[alias]) { this.smarthostModal.error = 'Alias Name already exists.'; return; }
    const host = this.smarthostModal.hostname.trim();
    if(!host) { this.smarthostModal.error = 'Hostname is required.'; return; }
    const port = this.smarthostModal.port;
    if(!port || port < 1 || port > 65535) { this.smarthostModal.error = 'Port must be between 1 and 65535.'; return; }

    const user = this.smarthostModal.username.trim();
    const pass = this.smarthostModal.password.trim();
    if(this.smarthostModal.auth) {
        if(!user) { this.smarthostModal.error = 'Username is required when Auth is enabled.'; return; }
        if(this.smarthostModal.mode === 'add' && !pass) { this.smarthostModal.error = 'Password is required when Auth is enabled.'; return; }
    }

    if(this.smarthostModal.mode === 'edit' && this.smarthostModal.oldAlias !== alias) {
        delete this.smarthosts[this.smarthostModal.oldAlias];
        const vToken = this.vaultSmarthost[this.smarthostModal.oldAlias];
        if(vToken) { this.vaultSmarthost[alias] = vToken; delete this.vaultSmarthost[this.smarthostModal.oldAlias]; }
        if(this.smartGlobals.alias === this.smarthostModal.oldAlias) this.smartGlobals.alias = alias;
        this.mappings.forEach(m => { if(m.method === 'smarthost' && m.smarthost_alias === this.smarthostModal.oldAlias) m.smarthost_alias = alias; });
    }

    this.smarthosts[alias] = {
        hostname: host, port: port, advertised_hostname: this.smarthostModal.advertised_hostname.trim(),
        starttls: this.smarthostModal.starttls, disable_tls_validation: this.smarthostModal.disable_tls_validation,
        auth: this.smarthostModal.auth, disable_attachments: this.smarthostModal.disable_attachments, force_plaintext: this.smarthostModal.force_plaintext
    };
    if(this.smarthostModal.auth) {
        this.smarthosts[alias].username = user;
        if(pass) this.vaultSmarthost[alias] = { token: pass, epoch: Math.floor(Date.now() / 1000) };
    } else {
        if(this.vaultSmarthost[alias]) delete this.vaultSmarthost[alias];
    }
    this.smarthostModal.open = false;
},
clearSmarthostModal() {
    const o = this.smarthostModal.orig;
    this.smarthostModal.alias = o.alias;
    this.smarthostModal.hostname = o.hostname;
    this.smarthostModal.advertised_hostname = o.advertised_hostname;
    this.smarthostModal.port = o.port;
    this.smarthostModal.starttls = o.starttls;
    this.smarthostModal.disable_tls_validation = o.disable_tls_validation;
    this.smarthostModal.auth = o.auth;
    this.smarthostModal.username = o.username;
    this.smarthostModal.password = o.password;
    this.smarthostModal.disable_attachments = o.disable_attachments;
    this.smarthostModal.force_plaintext = o.force_plaintext;
    this.smarthostModal.error = '';
},

deleteSmarthost(alias) {
    let inUse = false;
    if(this.smtp.default_route === 'smarthost' && this.smartGlobals.alias === alias) inUse = true;
    this.mappings.forEach(m => { if(m.method === 'smarthost' && m.smarthost_alias === alias) inUse = true; });
    if(inUse) { alert(`Error: Alias '${alias}' is actively assigned to an email route. Reconfigure your Routes before deleting.`); return; }
    delete this.smarthosts[alias];
    if(this.vaultSmarthost[alias]) delete this.vaultSmarthost[alias];
},

deleteVaultToken(type, aliasName) {
    const targetArr = type === 'app' ? this.vaultApp : this.vaultUser;
    const idx = targetArr.findIndex(x => x.name === aliasName);
    if(idx === -1) return;
    let inUse = false;
    if(type === 'app') { if(this.smtp.default_route === 'pushover' && this.pushGlobals._isTokenAlias && this.pushGlobals.token === aliasName) inUse = true; this.mappings.forEach(m => { if(m.method === 'pushover' && m._isTokenAlias && m.token === aliasName) inUse = true; }); }
    else { if(this.smtp.default_route === 'pushover' && this.pushGlobals._isUserAlias && this.pushGlobals.user === aliasName) inUse = true; this.mappings.forEach(m => { if(m.method === 'pushover' && m._isUserAlias && m.user === aliasName) inUse = true; }); }
    if(inUse) { alert(`Error: Alias '${aliasName}' is actively assigned to an email route. Reconfigure your Routes before deleting.`); return; }
    targetArr.splice(idx, 1);
    if(type === 'app') this.vaultAppAliases = this.vaultAppAliases.filter(a => a !== aliasName);
    if(type === 'user') this.vaultUserAliases = this.vaultUserAliases.filter(a => a !== aliasName);
},

openUiListenerModal(mode, idx=null) {
    this.uiListenerModal.mode = mode;
    this.uiListenerModal.idx = idx;
    this.uiListenerModal.error = '';
    if(mode === 'add') {
        this.uiListenerModal.ip = '0.0.0.0'; this.uiListenerModal.port = 8443;
        this.uiListenerModal.https = true; this.uiListenerModal.tls_cert = ''; this.uiListenerModal.tls_key = '';
    } else {
        const l = this.uiListeners[idx];
        let ip = '0.0.0.0'; let port = 8443;
        if(l.bind && l.bind.includes(':')) {
            const parts = l.bind.split(':');
            ip = parts[0]; port = parseInt(parts[1]);
        }
        this.uiListenerModal.ip = ip; this.uiListenerModal.port = port;
        this.uiListenerModal.https = l.https === true;
        this.uiListenerModal.tls_cert = l.tls_cert || ''; this.uiListenerModal.tls_key = l.tls_key || '';
    }
    this.uiListenerModal.orig = {
        ip: this.uiListenerModal.ip, port: this.uiListenerModal.port, https: this.uiListenerModal.https,
        tls_cert: this.uiListenerModal.tls_cert, tls_key: this.uiListenerModal.tls_key
    };
    this.uiListenerModal.open = true;
},
saveUiListenerModal() {
    const ip = this.uiListenerModal.ip.trim() || '0.0.0.0';
    if (!this.isValidIP(ip)) { this.uiListenerModal.error = 'Must be a valid IPv4, IPv6, or localhost.'; return; }

    const port = this.uiListenerModal.port;
    if(!port || port < 1 || port > 65535) { this.uiListenerModal.error = 'Port must be between 1 and 65535.'; return; }

    const bind = ip + ':' + port;
    const obj = { bind: bind, https: this.uiListenerModal.https };
    if(this.uiListenerModal.https) {
        if(this.uiListenerModal.tls_cert.trim()) obj.tls_cert = this.uiListenerModal.tls_cert.trim();
        if(this.uiListenerModal.tls_key.trim()) obj.tls_key = this.uiListenerModal.tls_key.trim();
    }
    if(this.uiListenerModal.mode === 'add') { this.uiListeners.push(obj); }
    else { this.uiListeners[this.uiListenerModal.idx] = obj; }
    this.uiListenerModal.open = false;
},
clearUiListenerModal() {
    this.uiListenerModal.ip = this.uiListenerModal.orig.ip;
    this.uiListenerModal.port = this.uiListenerModal.orig.port;
    this.uiListenerModal.https = this.uiListenerModal.orig.https;
    this.uiListenerModal.tls_cert = this.uiListenerModal.orig.tls_cert;
    this.uiListenerModal.tls_key = this.uiListenerModal.orig.tls_key;
    this.uiListenerModal.error = '';
},
