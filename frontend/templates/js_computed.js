setVaultSort(col) {
    if(this.vaultSortCol === col) { this.vaultSortDir = this.vaultSortDir === 1 ? -1 : 1; }
    else { this.vaultSortCol = col; this.vaultSortDir = 1; }
},
setSmtpSort(col) {
    if(this.smtpSortCol === col) { this.smtpSortDir = this.smtpSortDir === 1 ? -1 : 1; }
    else { this.smtpSortCol = col; this.smtpSortDir = 1; }
},
setSmarthostSort(col) {
    if(this.smarthostSortCol === col) { this.smarthostSortDir = this.smarthostSortDir === 1 ? -1 : 1; }
    else { this.smarthostSortCol = col; this.smarthostSortDir = 1; }
},
setListenerSort(col) {
    if(this.listenerSortCol === col) { this.listenerSortDir = this.listenerSortDir === 1 ? -1 : 1; }
    else { this.listenerSortCol = col; this.listenerSortDir = 1; }
},

get sortedVaultApp() {
    return [...this.vaultApp].sort((a, b) => {
        if(this.vaultSortCol === 'name') return a.name.localeCompare(b.name) * this.vaultSortDir;
        else return (a.epoch - b.epoch) * this.vaultSortDir;
    });
},
get sortedVaultUser() {
    return [...this.vaultUser].sort((a, b) => {
        if(this.vaultSortCol === 'name') return a.name.localeCompare(b.name) * this.vaultSortDir;
        else return (a.epoch - b.epoch) * this.vaultSortDir;
    });
},
get sortedSmtpAuth() {
    const arr = Object.keys(this.smtp.auth || {}).map(k => ({ name: k, epoch: this.smtp_meta[k] || 0 }));
    return arr.sort((a, b) => {
        if(this.smtpSortCol === 'name') return a.name.localeCompare(b.name) * this.smtpSortDir;
        else return (a.epoch - b.epoch) * this.smtpSortDir;
    });
},
get sortedSmarthosts() {
    const arr = Object.keys(this.smarthosts).map(k => ({ alias: k, ...this.smarthosts[k] }));
    return arr.sort((a, b) => {
        let res = 0;
        if (this.smarthostSortCol === 'alias') res = a.alias.localeCompare(b.alias);
        else if (this.smarthostSortCol === 'address') {
            const aAddr = (a.hostname || '') + ':' + (a.port || 25);
            const bAddr = (b.hostname || '') + ':' + (b.port || 25);
            res = aAddr.localeCompare(bAddr);
        }
        else if (this.smarthostSortCol === 'starttls') res = (a.starttls === b.starttls) ? 0 : a.starttls ? 1 : -1;
        else if (this.smarthostSortCol === 'auth') res = (a.auth === b.auth) ? 0 : a.auth ? 1 : -1;
        else if (this.smarthostSortCol === 'username') res = (a.username || '').localeCompare(b.username || '');
        else if (this.smarthostSortCol === 'disable_attachments') res = (a.disable_attachments === b.disable_attachments) ? 0 : a.disable_attachments ? 1 : -1;
        else if (this.smarthostSortCol === 'force_plaintext') res = (a.force_plaintext === b.force_plaintext) ? 0 : a.force_plaintext ? 1 : -1;
        return res * this.smarthostSortDir;
    });
},
get sortedSmarthostKeys() {
    return this.sortedSmarthosts.map(s => s.alias);
},
get sortedListeners() {
    const mapped = this.smtp.listeners.map((l, i) => ({ ...l, _idx: i }));
    return mapped.sort((a, b) => {
        let res = 0;
        if (this.listenerSortCol === 'bind') res = (a.bind || '').localeCompare(b.bind || '');
        else if (this.listenerSortCol === 'hostname') res = (a.hostname || '').localeCompare(b.hostname || '');
        else if (this.listenerSortCol === 'starttls') res = (a.starttls === b.starttls) ? 0 : a.starttls ? 1 : -1;
        return res * this.listenerSortDir;
    });
},
setUiListenerSort(col) {
    if(this.uiListenerSortCol === col) { this.uiListenerSortDir = this.uiListenerSortDir === 1 ? -1 : 1; }
    else { this.uiListenerSortCol = col; this.uiListenerSortDir = 1; }
},
get sortedUiListeners() {
    const mapped = this.uiListeners.map((l, i) => ({ ...l, _idx: i }));
    return mapped.sort((a, b) => {
        let res = 0;
        if (this.uiListenerSortCol === 'bind') res = (a.bind || '').localeCompare(b.bind || '');
        else if (this.uiListenerSortCol === 'https') res = (a.https === b.https) ? 0 : a.https ? 1 : -1;
        return res * this.uiListenerSortDir;
    });
},

// Modal Reactive State Checking
get hasVaultModalChanges() { return this.vaultModal.name !== this.vaultModal.orig.name || this.vaultModal.token !== this.vaultModal.orig.token; },
get hasSmtpUserModalChanges() { return this.smtpUserModal.name !== this.smtpUserModal.orig.name || this.smtpUserModal.password !== this.smtpUserModal.orig.password; },
get hasEditModalChanges() { return this.editModal.value !== this.editModal.orig.value; },
get hasSmarthostModalChanges() {
    const m = this.smarthostModal; const o = m.orig;
    return m.alias !== o.alias || m.hostname !== o.hostname || m.port !== o.port || m.advertised_hostname !== o.advertised_hostname || m.starttls !== o.starttls || m.disable_tls_validation !== o.disable_tls_validation || m.auth !== o.auth || m.username !== o.username || m.password !== o.password || m.disable_attachments !== o.disable_attachments || m.force_plaintext !== o.force_plaintext;
},
get hasListenerModalChanges() {
    const m = this.listenerModal; const o = m.orig;
    return m.ip !== o.ip || m.port !== o.port || m.hostname !== o.hostname || m.starttls !== o.starttls || m.tls_cert_file !== o.tls_cert_file || m.tls_key_file !== o.tls_key_file;
},
get hasUiListenerModalChanges() {
    const m = this.uiListenerModal; const o = m.orig;
    return m.ip !== o.ip || m.port !== o.port || m.https !== o.https || m.tls_cert !== o.tls_cert || m.tls_key !== o.tls_key;
},

// Granular Modal Save Validators
get canSaveVaultModal() { return this.hasVaultModalChanges && this.vaultModal.name.trim() !== '' && this.vaultModal.token.trim() !== ''; },
get canSaveSmtpUserModal() { return this.hasSmtpUserModalChanges && this.smtpUserModal.name.trim() !== '' && this.smtpUserModal.password.trim() !== ''; },
get canSaveEditModal() { return this.hasEditModalChanges && this.editModal.value.trim() !== ''; },
get canSaveSmarthostModal() {
    if (!this.hasSmarthostModalChanges) return false;
    const m = this.smarthostModal;
    if (!m.alias.trim() || !m.hostname.trim() || !m.port) return false;
    if (m.auth) {
        if (!m.username.trim()) return false;
        if (m.mode === 'add' && !m.password.trim()) return false;
    }
    return true;
},
get canSaveListenerModal() {
    if (!this.hasListenerModalChanges) return false;
    const m = this.listenerModal;
    if (!m.port) return false;
    const ip = m.ip.trim() || '0.0.0.0';
    return this.isValidIP(ip);
},
get canSaveUiListenerModal() {
    if (!this.hasUiListenerModalChanges) return false;
    const m = this.uiListenerModal;
    if (!m.port) return false;
    const ip = m.ip.trim() || '0.0.0.0';
    return this.isValidIP(ip);
},

// Core Tab Reactive State Checking
get hasUiChanges() {
    if (!this.initialState || !this.initialState.ui) return false;
    if (this.ui_loglevel !== this.initialState.ui.ui_loglevel) return true;
    if (this.ui_tz !== this.initialState.ui.ui_tz) return true;
    if (this.ui_fmt !== this.initialState.ui.ui_fmt) return true;
    if (this.ui_relative !== this.initialState.ui.ui_relative) return true;
    if (this.ui_expand_adv !== this.initialState.ui.ui_expand_adv) return true;
    if (this.ui_vault_sort !== this.initialState.ui.ui_vault_sort) return true;
    if (this.ui_smtp_sort !== this.initialState.ui.ui_smtp_sort) return true;
    if (this.ui_smarthost_sort !== this.initialState.ui.ui_smarthost_sort) return true;
    if (JSON.stringify(this.uiListeners) !== JSON.stringify(this.initialState.ui.uiListeners)) return true;
    return false;
},

get canSaveUi() {
    if (!this.hasUiChanges) return false;
    if (this.ui_tz && !this.validTimezones.includes(this.ui_tz)) return false;
    for (let l of this.uiListeners) {
        if (!l.bind || l.bind.trim() === '') return false;
    }
    return true;
},

get hasAppChanges() {
    if (!this.initialState || !this.initialState.server) return false;
    if (this.smtp.default_route !== this.initialState.server.smtp.default_route) return true;
    if (this.smtp.loglevel !== this.initialState.server.smtp.loglevel) return true;
    if (this.smtp.disable_persistence !== this.initialState.server.smtp.disable_persistence) return true;
    if (this.smtp.hostname !== this.initialState.server.smtp.hostname) return true;
    if (this.smtp.queue_dir !== this.initialState.server.smtp.queue_dir) return true;
    if (this.smtp.tls_cert_file !== this.initialState.server.smtp.tls_cert_file) return true;
    if (this.smtp.tls_key_file !== this.initialState.server.smtp.tls_key_file) return true;
    if (JSON.stringify(this.smtp.listeners) !== JSON.stringify(this.initialState.server.smtp.listeners)) return true;
    if (JSON.stringify(this.smtp.auth) !== JSON.stringify(this.initialState.server.smtp.auth)) return true;
    if (JSON.stringify(this.smarthosts) !== JSON.stringify(this.initialState.smarthost.smarthosts)) return true;
    if (JSON.stringify(this.smartGlobals) !== JSON.stringify(this.initialState.smarthost.smartGlobals)) return true;
    if (JSON.stringify(this.pushGlobals) !== JSON.stringify(this.initialState.pushover.pushGlobals)) return true;

    const currentVaultStr = JSON.stringify({ vaultApp: this.vaultApp, vaultUser: this.vaultUser, vaultSmarthost: this.vaultSmarthost });
    const initialVaultStr = JSON.stringify({ vaultApp: this.initialState.vault.vaultApp, vaultUser: this.initialState.vault.vaultUser, vaultSmarthost: this.initialState.vault.vaultSmarthost });
    if (initialVaultStr !== currentVaultStr) return true;

    const cleanOldRoutes = this.initialState.routes.mappings.map(({_uid, ...rest}) => rest);
    const cleanNewRoutes = this.mappings.map(({_uid, ...rest}) => rest);
    if (JSON.stringify(cleanOldRoutes) !== JSON.stringify(cleanNewRoutes)) return true;

    return false;
},

get canSaveApp() {
    if (!this.hasAppChanges) return false;

    // Reject save if any routing definitions are improperly formed or left entirely blank
    for (let m of this.mappings) {
        if (!m._key || m._key.trim() === '') return false;
        if (m.method === 'pushover') {
            if (!m.token || m.token.trim() === '') return false;
        } else if (m.method === 'smarthost') {
            if (!m.smarthost_alias || m.smarthost_alias.trim() === '') return false;
        }
    }

    // Guard against applying an incomplete Global Fallback parameter
    if (this.smtp.default_route === 'pushover') {
        if (!this.pushGlobals.token || !this.pushGlobals.user) return false;
    } else if (this.smtp.default_route === 'smarthost') {
        if (!this.smartGlobals.alias) return false;
    }

    return true;
},
