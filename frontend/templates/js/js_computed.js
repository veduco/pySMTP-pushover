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

_evaluateListenerSort(listenersArray, sortColumn, sortDirection) {
    const mapped = (listenersArray || []).map((l, i) => ({ ...l, _idx: i }));
    return mapped.sort((a, b) => {
        if (sortColumn === 'bind') {
            let valA = String(a.bind || '');
            let valB = String(b.bind || '');
            return valA.localeCompare(valB, undefined, { numeric: true, sensitivity: 'base' }) * sortDirection;
        }

        let valA = a[sortColumn];
        if (valA === undefined || valA === null) valA = '';
        let valB = b[sortColumn];
        if (valB === undefined || valB === null) valB = '';

        let res = valA < valB ? -1 : (valA > valB ? 1 : 0);
        return res * sortDirection;
    });
},

get sortedUiListeners() {
    return this._evaluateListenerSort(this.uiListeners, this.uiListenerSortCol, this.uiListenerSortDir);
},

get sortedSmtpListeners() {
    return this._evaluateListenerSort(this.smtp.listeners, this.smtpListenerSortCol, this.smtpListenerSortDir);
},

get sortedListeners() {
    return this._evaluateListenerSort(this.smtp.listeners, this.listenerSortCol, this.listenerSortDir);
},

setUiListenerSort(col) {
    if(this.uiListenerSortCol === col) { this.uiListenerSortDir = this.uiListenerSortDir === 1 ? -1 : 1; }
    else { this.uiListenerSortCol = col; this.uiListenerSortDir = 1; }
},

get hasRouteChanges() {
    if (!this.snapshots || !this.snapshots.routes) return false;
    return this.snapshots.routes !== JSON.stringify(this.mappings.map(({_uid, _showToken, _showUser, _tokenAliasVal, _tokenRaw, _userAliasVal, _userRaw, ...rest}) => rest));
},

get hasPushoverChanges() {
    if (!this.snapshots || !this.snapshots.pushover) return false;
    return this.snapshots.pushover !== JSON.stringify({ pushGlobals: this.pushGlobals, vaultApp: this.vaultApp, vaultUser: this.vaultUser });
},

get hasSmarthostChanges() {
    if (!this.snapshots || !this.snapshots.smarthost) return false;
    return this.snapshots.smarthost !== JSON.stringify({ smarthosts: this.smarthosts, smartGlobals: this.smartGlobals, vaultSmarthost: this.vaultSmarthost });
},

get hasServerChanges() {
    if (!this.snapshots || !this.snapshots.server) return false;
    return this.snapshots.server !== JSON.stringify(this.smtp);
},

get hasBackendChanges() {
    if (!this.snapshots || !this.snapshots.backend) return false;
    const currentBnd = JSON.stringify({
        backend_remote: this.ui_backend_remote, local_config_path: this.ui_local_config_path,
        remote_url: this.ui_remote_url, remote_secret: this.ui_remote_secret, remote_verify_tls: this.ui_remote_verify_tls
    });
    return this.snapshots.backend !== currentBnd;
},

get hasUiChanges() {
    if (!this.snapshots || !this.snapshots.ui) return false;
    const currentUi = JSON.stringify({
        ui_loglevel: this.ui_loglevel, ui_tz: this.ui_tz, ui_fmt: this.ui_fmt,
        ui_relative: this.ui_relative, ui_expand_adv: this.ui_expand_adv, ui_trust_proxy: this.ui_trust_proxy,
        ui_vault_sort: this.ui_vault_sort, ui_smtp_sort: this.ui_smtp_sort, ui_smarthost_sort: this.ui_smarthost_sort,
        uiListeners: this.uiListeners,
        ui_allowed_cidrs: this.ui_allowed_cidrs,
        ui_trust_proxy_cidrs: this.ui_trust_proxy_cidrs
    });
    return this.snapshots.ui !== currentUi;
},

get hasActiveTabChanges() {
    if (this.tab === 'routes') return this.hasRouteChanges;
    if (this.tab === 'pushover') return this.hasPushoverChanges;
    if (this.tab === 'smarthost') return this.hasSmarthostChanges;
    if (this.tab === 'server') return this.hasServerChanges;
    if (this.tab === 'backend') return this.hasBackendChanges;
    if (this.tab === 'ui') return this.hasUiChanges;
    return false;
},

get canSaveActiveTab() {
    if (!this.hasActiveTabChanges) return false;
    if (this.tab === 'routes') {
        for (let m of this.mappings) {
            if (!m._key || m._key.trim() === '') return false;
            if (m.method === 'pushover') {
                if (!m.token || m.token.trim() === '') return false;
            } else if (m.method === 'smarthost') {
                if (!m.smarthost_alias || m.smarthost_alias.trim() === '') return false;
            }
        }
    } else if (this.tab === 'server') {
        if (this.smtpCidrError) return false;
        if (this.smtp.default_route === 'pushover') {
            if (!this.pushGlobals.token || !this.pushGlobals.user) return false;
        } else if (this.smtp.default_route === 'smarthost') {
            if (!this.smartGlobals.alias) return false;
        }
    } else if (this.tab === 'ui') {
        if (this.tzError || this.uiCidrError || this.uiTrustProxyCidrError) return false;
    }
    return true;
},

get hasTestPayloadChanges() {
    return this.testPayload.from !== this.defaultTestPayload.from ||
           this.testPayload.to !== this.defaultTestPayload.to ||
           this.testPayload.type !== this.defaultTestPayload.type ||
           this.testPayload.message_plain !== this.defaultTestPayload.message_plain ||
           this.testPayload.message_html !== this.defaultTestPayload.message_html;
},
