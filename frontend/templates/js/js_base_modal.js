class GatewayModal {
    constructor(app, schemaRegistry, schemaPath, customOverrides = {}) {
        this.app = app;
        this.open = false;
        this.error = '';
        this.mode = 'add';
        this.showToken = false;
        this.defaultFields = this._extractSchemaFields(schemaRegistry, schemaPath);
        this.fields = { ...this.defaultFields, ...customOverrides };
        this.orig = this.app.clone(this.fields);
    }

    _extractSchemaFields(schema, path) {
        if (!path) return {};
        const parts = path.split('.');
        let current = schema;
        for (const part of parts) {
            if (current === undefined || current === null) return {};
            current = current[part];
        }
        if (Array.isArray(current)) {
            return current[0] ? JSON.parse(JSON.stringify(current[0])) : {};
        }
        return current ? JSON.parse(JSON.stringify(current)) : {};
    }

    initOpen(mode, dynamicData = {}) {
        this.mode = mode;
        this.error = '';
        this.showToken = false;
        if (mode === 'add') {
            this.fields = this.app.clone({ ...this.defaultFields, ...dynamicData });
        } else {
            this.fields = this.app.clone(dynamicData);
        }
        this.orig = this.app.clone(this.fields);
        this.open = true;
    }

    clear() {
        this.fields = this.app.clone(this.orig);
        this.error = '';
    }

    get isDirty() {
        return JSON.stringify(this.fields) !== JSON.stringify(this.orig);
    }
}

class VaultModal extends GatewayModal {
    openModal(type) {
        this.initOpen('add', { type: type, name: '', token: '' });
    }
    save() {
        this.error = '';
        const f = this.fields;
        const name = f.name.trim(); const token = f.token.trim();
        if (!name || !token) { this.error = 'Both Alias Name and Token are required.'; return; }

        const targetArray = f.type === 'app' ? this.app.vaultApp : this.app.vaultUser;
        const aliasesArray = f.type === 'app' ? this.app.vaultAppAliases : this.app.vaultUserAliases;

        if (aliasesArray.includes(name)) { this.error = 'An alias with this name already exists.'; return; }

        targetArray.push({ name: name, token: token, epoch: Math.floor(Date.now() / 1000) });
        aliasesArray.push(name);
        this.open = false;
    }
    get canSave() {
        return this.isDirty && this.fields.name.trim() !== '' && this.fields.token.trim() !== '';
    }
    delete(type, name) {
        let isAssigned = false;
        if (type === 'app') {
            if (this.app.pushGlobals._isTokenAlias && this.app.pushGlobals.token === name) isAssigned = true;
            for (let m of this.app.mappings) { if (m.method === 'pushover' && m._isTokenAlias && m.token === name) isAssigned = true; }
        } else if (type === 'user') {
            if (this.app.pushGlobals._isUserAlias && this.app.pushGlobals.user === name) isAssigned = true;
            for (let m of this.app.mappings) { if (m.method === 'pushover' && m._isUserAlias && m.user === name) isAssigned = true; }
        }

        if (isAssigned) {
            this.app.alertModal.title = 'Token In Use';
            this.app.alertModal.message = `The ${type === 'app' ? 'App Token' : 'User Key'} "${name}" is currently assigned to a route or global fallback. Please reassign those items before deleting this alias.`;
            this.app.alertModal.open = true;
            return;
        }

        if (type === 'app') {
            this.app.vaultApp = this.app.vaultApp.filter(v => v.name !== name);
            this.app.vaultAppAliases = this.app.vaultApp.map(v => v.name);
        } else {
            this.app.vaultUser = this.app.vaultUser.filter(v => v.name !== name);
            this.app.vaultUserAliases = this.app.vaultUser.map(v => v.name);
        }
    }
}

class SmtpUserModal extends GatewayModal {
    openModal() {
        this.initOpen('add');
    }
    save() {
        const f = this.fields;
        const u = f.name.trim(); const p = f.password.trim();
        if(!u || !p) { this.error = "Username and Password are required."; return; }
        this.app.smtp.auth[u] = "RAW:" + p;
        this.app.smtp_meta[u] = Math.floor(Date.now() / 1000);
        this.open = false;
    }
    get canSave() {
        return this.isDirty && this.fields.name.trim() !== '' && this.fields.password.trim() !== '';
    }
    delete(username) {
        if (this.app.smtp.auth && this.app.smtp.auth[username] !== undefined) {
            delete this.app.smtp.auth[username];
            if (this.app.smtp_meta && this.app.smtp_meta[username] !== undefined) delete this.app.smtp_meta[username];
            this.app.smtp.auth = { ...this.app.smtp.auth }; this.app.smtp_meta = { ...this.app.smtp_meta };
        }
    }
}

class EditModal extends GatewayModal {
    openModal(type, name, subType='') {
        this.initOpen('edit', { type: type, subType: subType, name: name, value: '' });
    }
    save() {
        const f = this.fields;
        const v = f.value.trim();
        if(!v) return;
        if(f.type === 'smtp') {
            this.app.smtp.auth[f.name] = "RAW:" + v; this.app.smtp_meta[f.name] = Math.floor(Date.now() / 1000);
        } else if(f.type === 'vault') {
            const target = f.subType === 'app' ? this.app.vaultApp : this.app.vaultUser;
            const idx = target.findIndex(x => x.name === f.name);
            if(idx !== -1) { target[idx].token = v; target[idx].epoch = Math.floor(Date.now() / 1000); }
        }
        this.open = false;
    }
    get canSave() { return this.isDirty && this.fields.value.trim() !== ''; }
}

class SmarthostModal extends GatewayModal {
    openModal(mode, alias = '') {
        if (mode === 'add') {
            this.initOpen('add', { oldAlias: '', alias: '', port: 25, auth: false, username: '', password: '', hostname: '', advertised_hostname: '', disable_attachments: false, force_plaintext: false });
            this.portModified = false;
        } else {
            const sh = this.app.smarthosts[alias] || {};
            this.initOpen('edit', {
                oldAlias: alias, alias: alias,
                hostname: sh.hostname || '', advertised_hostname: sh.advertised_hostname || '',
                port: sh.port || 25, starttls: sh.starttls === true, disable_tls_validation: sh.disable_tls_validation === true,
                auth: sh.auth === true, username: sh.username || '', password: '',
                disable_attachments: sh.disable_attachments === true, force_plaintext: sh.force_plaintext === true
            });
            this.portModified = ![25, 587].includes(sh.port || 25);
        }
    }
    save() {
        const f = this.fields;
        const alias = f.alias.trim();

        if (!alias) { this.error = 'Alias name is required.'; return; }
        if (this.mode === 'add' && this.app.smarthosts[alias]) { this.error = 'Alias name already exists.'; return; }

        const shObj = { hostname: f.hostname.trim(), port: parseInt(f.port) || 25, starttls: f.starttls };
        if (f.advertised_hostname.trim()) shObj.advertised_hostname = f.advertised_hostname.trim();
        if (f.starttls && f.disable_tls_validation) shObj.disable_tls_validation = true;
        if (f.disable_attachments) shObj.disable_attachments = true;
        if (f.force_plaintext) shObj.force_plaintext = true;

        if (f.auth) {
            shObj.auth = true;
            shObj.username = f.username.trim();
        }

        this.app.smarthosts[alias] = shObj;

        if (f.auth && f.password) {
            if (!this.app.vaultSmarthost[alias]) this.app.vaultSmarthost[alias] = { epoch: Math.floor(Date.now() / 1000) };
            this.app.vaultSmarthost[alias].token = f.password;
        } else if (!f.auth && this.app.vaultSmarthost[alias]) {
            delete this.app.vaultSmarthost[alias];
        }

        this.open = false;
    }
    get canSave() {
        const f = this.fields;
        if (!f.alias.trim() || !f.hostname.trim()) return false;

        if (f.auth) {
            if (!f.username.trim()) return false;
            if (this.mode === 'add') {
                if (!f.password) return false;
            } else {
                const existingVault = this.app.vaultSmarthost[f.oldAlias];
                const hasExistingPassword = existingVault && existingVault.token;
                if (!hasExistingPassword && !f.password) return false;
            }
        }
        if (!this.isDirty && this.mode === 'edit') return false;
        return true;
    }
    delete(alias) {
        let isAssigned = false;
        if (this.app.smtp.default_route === 'smarthost' && this.app.smartGlobals.alias === alias) isAssigned = true;
        for (let m of this.app.mappings) { if (m.method === 'smarthost' && m.smarthost_alias === alias) { isAssigned = true; break; } }

        if (isAssigned) {
            this.app.alertModal.title = 'Smarthost In Use';
            this.app.alertModal.message = `The Smarthost alias "${alias}" is currently assigned to a route or the global default fallback. Please reassign those items before deleting this relay.`;
            this.app.alertModal.open = true;
            return;
        }

        delete this.app.smarthosts[alias];
        if (this.app.vaultSmarthost[alias]) delete this.app.vaultSmarthost[alias];
    }
}

class ListenerModal extends GatewayModal {
    constructor(app, listenerType, schemaRegistry, schemaPath, customOverrides) {
        super(app, schemaRegistry, schemaPath, customOverrides);
        this.listenerType = listenerType; // 'smtp' or 'ui'
    }
    openModal(mode, idx=null) {
        this.error = '';
        if (this.listenerType === 'smtp') {
            if (mode === 'add') {
                this.initOpen('add', {
                    idx: null, ip: '', port: 25, hostname: '',
                    starttls: false, proxy_protocol: false, tls_cert_file: '', tls_key_file: ''
                });
                this.portModified = false;
            } else {
                const l = this.app.smtp.listeners[idx];
                const { ip, port } = this.app.parseBindString(l.bind, 25);
                this.initOpen('edit', {
                    idx: idx, ip: ip, port: port, hostname: l.hostname || '',
                    starttls: l.starttls === true, proxy_protocol: l.proxy_protocol === true,
                    tls_cert_file: l.tls_cert_file || '', tls_key_file: l.tls_key_file || ''
                });
                this.portModified = ![25, 587].includes(port);
            }
        } else {
            if (mode === 'add') {
                this.initOpen('add', {
                    idx: null, ip: '', port: 8443,
                    https: true, tls_cert: '', tls_key: ''
                });
            } else {
                const l = this.app.uiListeners[idx];
                const { ip, port } = this.app.parseBindString(l.bind, 8443);
                this.initOpen('edit', {
                    idx: idx, ip: ip, port: port,
                    https: l.https === true, tls_cert: l.tls_cert || '', tls_key: l.tls_key || ''
                });
            }
        }
    }
    async save() {
        const f = this.fields;
        this.error = '';
        const ip = f.ip.trim() || '0.0.0.0';

        const isValid = await this.app.isValidIP(ip);
        if (!isValid) { this.error = 'Must be a valid IPv4, IPv6, or localhost.'; return; }

        const port = f.port;
        if(!port || port < 1 || port > 65535) { this.error = 'Port must be between 1 and 65535.'; return; }

        const bind = ip + ':' + port;
        const targetArray = this.listenerType === 'smtp' ? this.app.smtp.listeners : this.app.uiListeners;
        const existingIdx = targetArray.findIndex(l => l.bind === bind);

        if (existingIdx !== -1 && (this.mode === 'add' || existingIdx !== f.idx)) {
            this.error = `A ${this.listenerType === 'smtp' ? 'SMTP' : 'UI'} listener is already bound to this address and port.`;
            return;
        }

        const obj = { bind: bind };
        if (this.listenerType === 'smtp') {
            obj.starttls = f.starttls;
            obj.proxy_protocol = f.proxy_protocol;
            if(f.hostname.trim()) obj.hostname = f.hostname.trim();
            if(f.starttls) {
                if(f.tls_cert_file.trim()) obj.tls_cert_file = f.tls_cert_file.trim();
                if(f.tls_key_file.trim()) obj.tls_key_file = f.tls_key_file.trim();
            }
        } else {
            obj.https = f.https;
            if(f.https) {
                if(f.tls_cert.trim()) obj.tls_cert = f.tls_cert.trim();
                if(f.tls_key.trim()) obj.tls_key = f.tls_key.trim();
            }
        }

        if(this.mode === 'add') { targetArray.push(obj); } else { targetArray[f.idx] = obj; }
        this.open = false;
    }
    get canSave() {
        if (!this.isDirty && this.mode === 'edit') return false;
        if (!this.fields.port || this.fields.port < 1 || this.fields.port > 65535) return false;
        return true;
    }
    delete(idx) {
        if (this.listenerType === 'ui') {
            if (this.app.uiListeners.length <= 1) {
                this.app.alertModal.title = 'Cannot Remove Listener';
                this.app.alertModal.message = 'You must have at least one UI listener configured to maintain access to the web panel.';
                this.app.alertModal.open = true;
                return;
            }
            const targetListener = this.app.uiListeners[idx];
            const { port: bindPort } = this.app.parseBindString(targetListener.bind, 8443);
            if (parseInt(bindPort) === this.app.activeUiPort && this.app.activeUiPort > 0) {
                this.app.alertModal.title = 'Active Listener';
                this.app.alertModal.message = 'You cannot remove the specific network listener that your current session is actively routed through.';
                this.app.alertModal.open = true;
                return;
            }
            this.app.uiListeners.splice(idx, 1);
        } else {
            this.app.smtp.listeners.splice(idx, 1);
        }
    }
}

class HostModal extends GatewayModal {
    openModal(mode, idx=null) {
        this.error = '';
        if (mode === 'add') {
            this.initOpen('add', { idx: null, alias: '', host: '', port: 6443, verify_tls: true });
        } else {
            const h = this.app.ui_remote_hosts[idx];
            this.initOpen('edit', { idx: idx, alias: h.alias || '', host: h.host, port: h.port, verify_tls: h.verify_tls === true });
        }
    }
    async save() {
        this.error = '';
        const f = this.fields;
        const host = f.host.trim();
        if (!host) { this.error = 'Hostname or IP is required.'; return; }
        const isValid = await this.app.isValidIP(host) || /^[a-zA-Z0-9.-]+$/.test(host);
        if (!isValid) { this.error = 'Invalid Hostname or IP format.'; return; }
        const port = parseInt(f.port);
        if(!port || port < 1 || port > 65535) { this.error = 'Port must be an integer between 1 and 65535.'; return; }
        const hostStr = host + ":" + port;
        const existingIdx = this.app.ui_remote_hosts.findIndex(h => (h.host + ":" + h.port) === hostStr);

        if (existingIdx !== -1 && (this.mode === 'add' || existingIdx !== f.idx)) {
            this.error = 'A remote endpoint matching this address and port already exists.';
            return;
        }
        const alias = f.alias ? f.alias.trim() : '';
        const obj = { alias: alias, host: host, port: port, verify_tls: f.verify_tls, sync_status: 'pending', last_secret_hash: '', expected_hash: '' };

        if (this.mode === 'add') {
            this.app.ui_remote_hosts.push(obj);
        } else {
            obj.sync_status = this.app.ui_remote_hosts[f.idx].sync_status || 'pending';
            obj.last_secret_hash = this.app.ui_remote_hosts[f.idx].last_secret_hash || '';
            obj.expected_hash = this.app.ui_remote_hosts[f.idx].expected_hash || '';
            this.app.ui_remote_hosts[f.idx] = obj;
        }
        this.open = false;
    }
    get canSave() {
        const f = this.fields;
        if (!f.host.trim() || !f.port || f.port < 1 || f.port > 65535) return false;
        return this.isDirty || this.mode === 'add';
    }
    delete(idx) {
        const target = this.app.ui_remote_hosts[idx];
        const hostStr = target.host + ":" + target.port;
        if (this.app.ui_primary_host === hostStr) {
            this.app.alertModal.title = 'Cannot Remove Primary Host';
            this.app.alertModal.message = 'This node is actively set as your designated Source of Truth context. Please reassign the primary pointer to another node before deleting this entry.';
            this.app.alertModal.open = true;
            return;
        }
        this.app.ui_remote_hosts.splice(idx, 1);
    }
}

class SecretModal extends GatewayModal {
    openModal() {
        this.initOpen('edit', { value: '' });
    }
}
