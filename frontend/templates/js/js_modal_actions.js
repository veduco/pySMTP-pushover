// --- VAULT ALIAS MODAL ACTIONS ---
openVaultModal(type) {
    this.modals.vault.initOpen('add', { type: type, name: '', token: '' });
},

saveVaultModal() {
    this.modals.vault.error = '';
    const f = this.modals.vault.fields;
    const name = f.name.trim(); const token = f.token.trim();

    if (!name || !token) { this.modals.vault.error = 'Both Alias Name and Token are required.'; return; }

    const targetArray = f.type === 'app' ? this.vaultApp : this.vaultUser;
    const aliasesArray = f.type === 'app' ? this.vaultAppAliases : this.vaultUserAliases;

    if (aliasesArray.includes(name)) { this.modals.vault.error = 'An alias with this name already exists.'; return; }

    targetArray.push({ name: name, token: token, epoch: Math.floor(Date.now() / 1000) });
    aliasesArray.push(name);
    this.modals.vault.open = false;
},

get canSaveVaultModal() {
    return this.modals.vault.isDirty && this.modals.vault.fields.name.trim() !== '' && this.modals.vault.fields.token.trim() !== '';
},

deleteVaultToken(type, name) {
    let isAssigned = false;
    if (type === 'app') {
        if (this.pushGlobals._isTokenAlias && this.pushGlobals.token === name) isAssigned = true;
        for (let m of this.mappings) { if (m.method === 'pushover' && m._isTokenAlias && m.token === name) isAssigned = true; }
    } else if (type === 'user') {
        if (this.pushGlobals._isUserAlias && this.pushGlobals.user === name) isAssigned = true;
        for (let m of this.mappings) { if (m.method === 'pushover' && m._isUserAlias && m.user === name) isAssigned = true; }
    }

    if (isAssigned) {
        this.alertModal.title = 'Token In Use';
        this.alertModal.message = `The ${type === 'app' ? 'App Token' : 'User Key'} "${name}" is currently assigned to a route or global fallback. Please reassign those items before deleting this alias.`;
        this.alertModal.open = true;
        return;
    }

    if (type === 'app') {
        this.vaultApp = this.vaultApp.filter(v => v.name !== name);
        this.vaultAppAliases = this.vaultApp.map(v => v.name);
    } else {
        this.vaultUser = this.vaultUser.filter(v => v.name !== name);
        this.vaultUserAliases = this.vaultUser.map(v => v.name);
    }
},

// --- SMTP USER MODAL ACTIONS ---
openSmtpUserModal() {
    this.modals.smtpUser.initOpen('add');
},

saveSmtpUserModal() {
    const f = this.modals.smtpUser.fields;
    const u = f.name.trim(); const p = f.password.trim();
    if(!u || !p) { this.modals.smtpUser.error = "Username and Password are required."; return; }
    this.smtp.auth[u] = "RAW:" + p;
    this.smtp_meta[u] = Math.floor(Date.now() / 1000);
    this.modals.smtpUser.open = false;
},

get canSaveSmtpUserModal() {
    return this.modals.smtpUser.isDirty && this.modals.smtpUser.fields.name.trim() !== '' && this.modals.smtpUser.fields.password.trim() !== '';
},

deleteSmtpUser(username) {
    if (this.smtp.auth && this.smtp.auth[username] !== undefined) {
        delete this.smtp.auth[username];
        if (this.smtp_meta && this.smtp_meta[username] !== undefined) delete this.smtp_meta[username];
        this.smtp.auth = { ...this.smtp.auth }; this.smtp_meta = { ...this.smtp_meta };
    }
},

// --- EDIT CREDENTIAL MODAL ACTIONS ---
openEditModal(type, name, subType='') {
    this.modals.edit.initOpen('edit', { type: type, subType: subType, name: name, value: '' });
},

saveEditModal() {
    const f = this.modals.edit.fields;
    const v = f.value.trim();
    if(!v) return;
    if(f.type === 'smtp') {
        this.smtp.auth[f.name] = "RAW:" + v; this.smtp_meta[f.name] = Math.floor(Date.now() / 1000);
    } else if(f.type === 'vault') {
        const target = f.subType === 'app' ? this.vaultApp : this.vaultUser;
        const idx = target.findIndex(x => x.name === f.name);
        if(idx !== -1) { target[idx].token = v; target[idx].epoch = Math.floor(Date.now() / 1000); }
    }
    this.modals.edit.open = false;
},

get canSaveEditModal() { return this.modals.edit.isDirty && this.modals.edit.fields.value.trim() !== ''; },

// --- SMARTHOST MODAL ACTIONS ---
openSmarthostModal(mode, alias = '') {
    if (mode === 'add') {
        this.modals.smarthost.initOpen('add', { oldAlias: '', alias: '', port: 25, auth: false, username: '', password: '', hostname: '', advertised_hostname: '', disable_attachments: false, force_plaintext: false });
    } else {
        const sh = this.smarthosts[alias] || {};
        this.modals.smarthost.initOpen('edit', {
            oldAlias: alias, alias: alias,
            hostname: sh.hostname || '', advertised_hostname: sh.advertised_hostname || '',
            port: sh.port || 25, starttls: sh.starttls === true, disable_tls_validation: sh.disable_tls_validation === true,
            auth: sh.auth === true, username: sh.username || '', password: '',
            disable_attachments: sh.disable_attachments === true, force_plaintext: sh.force_plaintext === true
        });
    }
},

saveSmarthostModal() {
    const f = this.modals.smarthost.fields;
    const alias = f.alias.trim();

    if (!alias) { this.modals.smarthost.error = 'Alias name is required.'; return; }
    if (this.modals.smarthost.mode === 'add' && this.smarthosts[alias]) { this.modals.smarthost.error = 'Alias name already exists.'; return; }

    const shObj = { hostname: f.hostname.trim(), port: parseInt(f.port) || 25, starttls: f.starttls };
    if (f.advertised_hostname.trim()) shObj.advertised_hostname = f.advertised_hostname.trim();
    if (f.starttls && f.disable_tls_validation) shObj.disable_tls_validation = true;
    if (f.disable_attachments) shObj.disable_attachments = true;
    if (f.force_plaintext) shObj.force_plaintext = true;

    if (f.auth) {
        shObj.auth = true;
        shObj.username = f.username.trim();
    }

    this.smarthosts[alias] = shObj;

    if (f.auth && f.password) {
        if (!this.vaultSmarthost[alias]) this.vaultSmarthost[alias] = { epoch: Math.floor(Date.now() / 1000) };
        this.vaultSmarthost[alias].token = f.password;
    } else if (!f.auth && this.vaultSmarthost[alias]) {
        delete this.vaultSmarthost[alias];
    }

    this.modals.smarthost.open = false;
},

get canSaveSmarthostModal() {
    const f = this.modals.smarthost.fields;
    if (!f.alias.trim() || !f.hostname.trim()) return false;

    if (f.auth) {
        if (!f.username.trim()) return false;
        if (this.modals.smarthost.mode === 'add') {
            if (!f.password) return false;
        } else {
            const existingVault = this.vaultSmarthost[f.oldAlias];
            const hasExistingPassword = existingVault && existingVault.token;
            if (!hasExistingPassword && !f.password) return false;
        }
    }
    if (!this.modals.smarthost.isDirty && this.modals.smarthost.mode === 'edit') return false;
    return true;
},

deleteSmarthost(alias) {
    let isAssigned = false;
    if (this.smtp.default_route === 'smarthost' && this.smartGlobals.alias === alias) isAssigned = true;
    for (let m of this.mappings) { if (m.method === 'smarthost' && m.smarthost_alias === alias) { isAssigned = true; break; } }

    if (isAssigned) {
        this.alertModal.title = 'Smarthost In Use';
        this.alertModal.message = `The Smarthost alias "${alias}" is currently assigned to a route or the global default fallback. Please reassign those items before deleting this relay.`;
        this.alertModal.open = true;
        return;
    }

    delete this.smarthosts[alias];
    if (this.vaultSmarthost[alias]) delete this.vaultSmarthost[alias];
},

// --- NETWORK LISTENER MODAL ACTIONS ---
openListenerModal(mode, idx=null) {
    if(mode === 'add') {
        this.modals.listener.initOpen('add', { idx: null, ip: '0.0.0.0', port: 25, hostname: '' });
    } else {
        const l = this.smtp.listeners[idx];
        const { ip, port } = this.parseBindString(l.bind, 25);
        this.modals.listener.initOpen('edit', {
            idx: idx, ip: ip, port: port, hostname: l.hostname || '',
            starttls: l.starttls === true, proxy_protocol: l.proxy_protocol === true,
            tls_cert_file: l.tls_cert_file || '', tls_key_file: l.tls_key_file || ''
        });
    }
},

saveListenerModal() {
    const f = this.modals.listener.fields;
    const ip = f.ip.trim() || '0.0.0.0';
    if (!this.isValidIP(ip)) { this.modals.listener.error = 'Must be a valid IPv4, IPv6, or localhost.'; return; }
    const port = f.port;
    if(!port || port < 1 || port > 65535) { this.modals.listener.error = 'Port must be between 1 and 65535.'; return; }
    const bind = ip + ':' + port;

    const existingIdx = this.smtp.listeners.findIndex(l => l.bind === bind);
    if (existingIdx !== -1 && (this.modals.listener.mode === 'add' || existingIdx !== f.idx)) {
        this.modals.listener.error = 'An SMTP listener is already bound to this address and port.';
        return;
    }

    const obj = { bind: bind, starttls: f.starttls, proxy_protocol: f.proxy_protocol };
    if(f.hostname.trim()) obj.hostname = f.hostname.trim();
    if(f.starttls) {
        if(f.tls_cert_file.trim()) obj.tls_cert_file = f.tls_cert_file.trim();
        if(f.tls_key_file.trim()) obj.tls_key_file = f.tls_key_file.trim();
    }

    if(this.modals.listener.mode === 'add') this.smtp.listeners.push(obj);
    else this.smtp.listeners[f.idx] = obj;
    this.modals.listener.open = false;
},

get canSaveListenerModal() {
    if (!this.modals.listener.isDirty && this.modals.listener.mode === 'edit') return false;
    const f = this.modals.listener.fields;
    if (!f.port || f.port < 1 || f.port > 65535) return false;
    return this.isValidIP(f.ip.trim() || '0.0.0.0');
},

openUiListenerModal(mode, idx=null) {
    if(mode === 'add') {
        this.modals.uiListener.initOpen('add', { idx: null, ip: '0.0.0.0', port: 8443 });
    } else {
        const l = this.uiListeners[idx];
        const { ip, port } = this.parseBindString(l.bind, 8443);
        this.modals.uiListener.initOpen('edit', {
            idx: idx, ip: ip, port: port, https: l.https === true, tls_cert: l.tls_cert || '', tls_key: l.tls_key || ''
        });
    }
},

saveUiListenerModal() {
    const f = this.modals.uiListener.fields;
    const ip = f.ip.trim() || '0.0.0.0';
    if (!this.isValidIP(ip)) { this.modals.uiListener.error = 'Must be a valid IPv4, IPv6, or localhost.'; return; }
    const port = f.port;
    if(!port || port < 1 || port > 65535) { this.modals.uiListener.error = 'Port must be between 1 and 65535.'; return; }
    const bind = ip + ':' + port;

    const existingIdx = this.uiListeners.findIndex(l => l.bind === bind);
    if (existingIdx !== -1 && (this.modals.uiListener.mode === 'add' || existingIdx !== f.idx)) {
        this.modals.uiListener.error = 'A UI listener is already bound to this address and port.';
        return;
    }

    const obj = { bind: bind, https: f.https };
    if(f.https) {
        if(f.tls_cert.trim()) obj.tls_cert = f.tls_cert.trim();
        if(f.tls_key.trim()) obj.tls_key = f.tls_key.trim();
    }

    if(this.modals.uiListener.mode === 'add') this.uiListeners.push(obj);
    else this.uiListeners[f.idx] = obj;
    this.modals.uiListener.open = false;
},

get canSaveUiListenerModal() {
    if (!this.modals.uiListener.isDirty && this.modals.uiListener.mode === 'edit') return false;
    const f = this.modals.uiListener.fields;
    if (!f.port || f.port < 1 || f.port > 65535) return false;
    return this.isValidIP(f.ip.trim() || '0.0.0.0');
},

deleteUiListener(idx) {
    if (this.uiListeners.length <= 1) {
        this.alertModal.title = 'Cannot Remove Listener';
        this.alertModal.message = 'You must have at least one UI listener configured to maintain access to the web panel.';
        this.alertModal.open = true;
        return;
    }

    const targetListener = this.uiListeners[idx];
    const { port: bindPort } = this.parseBindString(targetListener.bind, 8443);

    if (parseInt(bindPort) === this.activeUiPort && this.activeUiPort > 0) {
        this.alertModal.title = 'Active Listener';
        this.alertModal.message = 'You cannot remove the specific network listener that your current session is actively routed through.';
        this.alertModal.open = true;
        return;
    }
    this.uiListeners.splice(idx, 1);
},

// --- LINK EDIT MODAL ACTIONS ---
openLinkModal() {
    this.modals.link.initOpen('edit', {
        backend_remote: this.ui_backend_remote, local_config_path: this.ui_local_config_path,
        remote_url: this.ui_remote_url, remote_secret: '', remote_verify_tls: this.ui_remote_verify_tls
    });
},

saveLinkModal() {
    const f = this.modals.link.fields;
    this.ui_backend_remote = f.backend_remote;
    this.ui_local_config_path = f.local_config_path.trim();
    this.ui_remote_url = f.remote_url.trim();
    if (f.remote_secret.trim()) this.ui_remote_secret = f.remote_secret.trim();
    this.ui_remote_verify_tls = f.remote_verify_tls;
    this.modals.link.open = false;
},

get canSaveLinkModal() {
    if (!this.modals.link.isDirty) return false;
    const f = this.modals.link.fields;
    if (f.backend_remote) {
        if (!f.remote_url.trim()) return false;
        if (!f.remote_secret.trim() && (!this.ui_remote_secret || this.ui_remote_secret === '')) return false;
    } else { if (!f.local_config_path.trim()) return false; }
    return true;
},
