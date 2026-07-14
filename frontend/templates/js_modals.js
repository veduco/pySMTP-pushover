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
    this.listenerModal.open = true;
},
saveListenerModal() {
    const ip = this.listenerModal.ip.trim() || '0.0.0.0';
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
deleteSmarthost(alias) {
    let inUse = false;
    if(this.smtp.default_route === 'smarthost' && this.smartGlobals.alias === alias) inUse = true;
    this.mappings.forEach(m => { if(m.method === 'smarthost' && m.smarthost_alias === alias) inUse = true; });
    if(inUse) { alert(`Error: Alias '${alias}' is actively assigned to an email route. Reconfigure your Routes before deleting.`); return; }
    delete this.smarthosts[alias];
    if(this.vaultSmarthost[alias]) delete this.vaultSmarthost[alias];
},
addSmtpUser() { if(!this.newSmtpUser || !this.newSmtpPass) return; this.smtp.auth[this.newSmtpUser] = "RAW:" + this.newSmtpPass; this.smtp_meta[this.newSmtpUser] = Math.floor(Date.now() / 1000); this.newSmtpUser = ''; this.newSmtpPass = ''; },
addVaultToken() {
    if(!this.newVaultName || !this.newVaultToken) return;
    const nName = this.newVaultName.trim(); const nTok = this.newVaultToken.trim();
    if(!nName || !nTok) return;
    const target = this.newVaultType === 'app' ? this.vaultApp : this.vaultUser;
    const existingIdx = target.findIndex(x => x.name === nName);

    if(existingIdx >= 0) { target[existingIdx].token = nTok; target[existingIdx].epoch = Math.floor(Date.now() / 1000); }
    else { target.push({name: nName, token: nTok, epoch: Math.floor(Date.now() / 1000)}); }

    if(this.newVaultType === 'app' && !this.vaultAppAliases.includes(nName)) this.vaultAppAliases.push(nName);
    if(this.newVaultType === 'user' && !this.vaultUserAliases.includes(nName)) this.vaultUserAliases.push(nName);
    this.newVaultName = ''; this.newVaultToken = ''; this.showNewVaultToken = false;
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
openEditModal(type, name, subType='') { this.editModal.type = type; this.editModal.subType = subType; this.editModal.name = name; this.editModal.value = ''; this.editModal.showToken = false; this.editModal.open = true; },
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
