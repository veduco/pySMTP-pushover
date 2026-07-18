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
    return this._genericSort(this.vaultApp, this.vaultSortCol, this.vaultSortDir);
},

get sortedVaultUser() {
    return this._genericSort(this.vaultUser, this.vaultSortCol, this.vaultSortDir);
},

get sortedSmtpAuth() {
    const arr = Object.keys(this.smtp.auth || {}).map(k => ({ name: k, epoch: this.smtp_meta[k] || 0 }));
    return this._genericSort(arr, this.smtpSortCol, this.smtpSortDir);
},

get sortedSmarthosts() {
    const arr = Object.keys(this.smarthosts).map(k => ({ alias: k, ...this.smarthosts[k] }));
    return this._genericSort(arr, this.smarthostSortCol, this.smarthostSortDir, {
        address: (s) => (s.hostname || '') + ':' + (s.port || 25)
    });
},

get sortedSmarthostKeys() {
    return this.sortedSmarthosts.map(s => s.alias);
},

get sortedUiListeners() {
    const mapped = (this.uiListeners || []).map((l, i) => ({ ...l, _idx: i }));
    return this._genericSort(mapped, this.uiListenerSortCol, this.uiListenerSortDir);
},

get sortedSmtpListeners() {
    const mapped = (this.smtp.listeners || []).map((l, i) => ({ ...l, _idx: i }));
    return this._genericSort(mapped, this.smtpListenerSortCol, this.smtpListenerSortDir);
},

get sortedListeners() {
    const mapped = (this.smtp.listeners || []).map((l, i) => ({ ...l, _idx: i }));
    return this._genericSort(mapped, this.listenerSortCol, this.listenerSortDir);
},

setUiListenerSort(col) {
    if(this.uiListenerSortCol === col) { this.uiListenerSortDir = this.uiListenerSortDir === 1 ? -1 : 1; }
    else { this.uiListenerSortCol = col; this.uiListenerSortDir = 1; }
},

// Proxy tracking properties to centralized Flux store
get hasRouteChanges() { return this.GatewayStore.isDirty('routes', this); },
get hasPushoverChanges() { return this.GatewayStore.isDirty('pushover', this); },
get hasSmarthostChanges() { return this.GatewayStore.isDirty('smarthost', this); },
get hasServerChanges() { return this.GatewayStore.isDirty('server', this); },
get hasBackendChanges() { return this.GatewayStore.isDirty('backend', this); },
get hasUiChanges() { return this.GatewayStore.isDirty('ui', this); },

get hasActiveTabChanges() {
    return this.GatewayStore.isDirty(this.tab, this);
},

get canSaveActiveTab() {
    return this.GatewayStore.isValid(this.tab, this);
},

get hasTestPayloadChanges() {
    return this.testPayload.from !== this.defaultTestPayload.from ||
           this.testPayload.to !== this.defaultTestPayload.to ||
           this.testPayload.type !== this.defaultTestPayload.type ||
           this.testPayload.message_plain !== this.defaultTestPayload.message_plain ||
           this.testPayload.message_html !== this.defaultTestPayload.message_html;
},
