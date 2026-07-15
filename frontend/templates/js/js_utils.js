getLogLevelColor(level) {
    switch(level) {
        case 'DEBUG': return '#c678dd';
        case 'INFO': return '#98c379';
        case 'WARNING': return '#e5c07b';
        case 'ERROR': return '#e06c75';
        case 'CRITICAL': return '#be5046';
        default: return 'var(--primary-color)';
    }
},
isValidIP(ip) {
    if (ip === 'localhost') return true;
    const ipv4 = /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
    const ipv6 = /^(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))$/;
    return ipv4.test(ip) || ipv6.test(ip);
},
reorderRoute(oldIdx, newIdx) {
    if (oldIdx === newIdx || oldIdx === null) return;
    const item = this.mappings.splice(oldIdx, 1)[0];
    this.mappings.splice(newIdx, 0, item);
    this.draggedRouteIdx = null;
},
changeDefaultRoute(e) {
    const val = e.target.value;
    if (val === 'smarthost') {
        if (!this.smartGlobals.alias) {
            alert('You must define a Default Smarthost Alias before switching the global route.');
            e.target.value = 'pushover';
            this.smtp.default_route = 'pushover';
            return;
        }
    } else {
        if (!this.pushGlobals.token || !this.pushGlobals.user) {
            alert('You must define a Default App Token and Default User Key before switching to Pushover.');
            e.target.value = 'smarthost';
            this.smtp.default_route = 'smarthost';
            return;
        }
    }
    this.smtp.default_route = val;
},
toggleAlias(obj, field) {
    const flag = field === 'token' ? '_isTokenAlias' : '_isUserAlias';
    const raw = field === 'token' ? '_tokenRaw' : '_userRaw';
    const alias = field === 'token' ? '_tokenAliasVal' : '_userAliasVal';
    if (obj[flag]) {
        obj[alias] = obj[field] || '';
        obj[field] = obj[raw] || '';
        obj[flag] = false;
    } else {
        obj[raw] = obj[field] || '';
        obj[field] = obj[alias] || '';
        obj[flag] = true;
    }
},
formatTime(epoch) {
    if(!epoch) return "Never";
    const d = new Date(epoch * 1000);
    if(this.ui_relative) {
        const now = new Date();
        const isFuture = d > now;
        const seconds = Math.abs(Math.floor((now - d) / 1000));
        let interval = Math.floor(seconds / 31536000);
        if (interval >= 1) return isFuture ? "in " + interval + " years" : interval + " years ago";
        interval = Math.floor(seconds / 2592000);
        if (interval >= 1) return isFuture ? "in " + interval + " months" : interval + " months ago";
        interval = Math.floor(seconds / 84600);
        if (interval >= 1) return isFuture ? "in " + interval + " days" : interval + " days ago";
        interval = Math.floor(seconds / 3600);
        if (interval >= 1) return isFuture ? "in " + interval + " hours" : interval + " hours ago";
        interval = Math.floor(seconds / 60);
        if (interval >= 1) return isFuture ? "in " + interval + " minutes" : interval + " minutes ago";
        return isFuture ? "in a few seconds" : "Just now";
    }
    return this.executeAbsoluteFormat(d);
},
getFullTime(epoch) { if(!epoch) return ""; return this.executeAbsoluteFormat(new Date(epoch * 1000)); },
executeAbsoluteFormat(d) {
    const pad = num => String(num).padStart(2, '0'); const t_str = d.toLocaleString("en-US", { timeZone: this.ui_tz }); const localD = new Date(t_str);
    const yyyy = localD.getFullYear(); const mm = pad(localD.getMonth() + 1); const dd = pad(localD.getDate()); let hh = localD.getHours(); const min = pad(localD.getMinutes()); const ss = pad(localD.getSeconds()); const ampm = hh >= 12 ? 'PM' : 'AM';
    if (this.ui_fmt.includes("hh")) { hh = hh % 12; hh = hh ? hh : 12; hh = pad(hh); return `${mm}/${dd}/${yyyy} ${hh}:${min}:${ss} ${ampm}`; }
    if (this.ui_fmt.startsWith("DD")) { return `${dd}/${mm}/${yyyy} ${pad(hh)}:${min}:${ss}`; }
    return `${yyyy}-${mm}-${dd} ${pad(hh)}:${min}:${ss}`;
},
addMapping() {
    this.mappings.push({
        _uid: Date.now().toString(36) + Math.random().toString(36).substr(2),
        _key: '', match: 'to', method: 'pushover', token: '', user: '', _isRegex: false,
        _isTokenAlias: true, _isUserAlias: true,
        _tokenAliasVal: '', _tokenRaw: '', _userAliasVal: '', _userRaw: '', smarthost_alias: '',
        _showToken: false, _showUser: false, _showAdv: this.ui_expand_adv, disable_attachments: false, force_plaintext: false
    });
},

checkTimezone() {
    if (this.ui_tz && !this.validTimezones.includes(this.ui_tz)) {
        this.tzError = 'Please select a valid timezone location from the list.';
        return false;
    }
    this.tzError = '';
    return true;
},

takeSnapshot() {
    this.initialState = JSON.parse(JSON.stringify({
        ui: {
            ui_loglevel: this.ui_loglevel, ui_tz: this.ui_tz, ui_fmt: this.ui_fmt,
            ui_relative: this.ui_relative, ui_expand_adv: this.ui_expand_adv,
            ui_vault_sort: this.ui_vault_sort, ui_smtp_sort: this.ui_smtp_sort,
            ui_smarthost_sort: this.ui_smarthost_sort, uiListeners: this.uiListeners
        },
        routes: { mappings: this.mappings },
        pushover: { pushGlobals: this.pushGlobals },
        smarthost: { smarthosts: this.smarthosts, smartGlobals: this.smartGlobals },
        server: { smtp: this.smtp, smtp_meta: this.smtp_meta },
        vault: { vaultApp: this.vaultApp, vaultUser: this.vaultUser, vaultSmarthost: this.vaultSmarthost, vaultAppAliases: this.vaultAppAliases, vaultUserAliases: this.vaultUserAliases }
    }));
},

resetTab(tabContext) {
    if (!this.initialState || Object.keys(this.initialState).length === 0) return;

    if (tabContext === 'ui') {
        this.ui_loglevel = this.initialState.ui.ui_loglevel;
        this.ui_tz = this.initialState.ui.ui_tz;
        this.ui_fmt = this.initialState.ui.ui_fmt;
        this.ui_relative = this.initialState.ui.ui_relative;
        this.ui_expand_adv = this.initialState.ui.ui_expand_adv;
        this.ui_vault_sort = this.initialState.ui.ui_vault_sort;
        this.ui_smtp_sort = this.initialState.ui.ui_smtp_sort;
        this.ui_smarthost_sort = this.initialState.ui.ui_smarthost_sort;
        this.uiListeners = JSON.parse(JSON.stringify(this.initialState.ui.uiListeners));
    } else if (tabContext === 'routes') {
        this.mappings = JSON.parse(JSON.stringify(this.initialState.routes.mappings));
    } else if (tabContext === 'pushover') {
        this.pushGlobals = JSON.parse(JSON.stringify(this.initialState.pushover.pushGlobals));
        this.vaultApp = JSON.parse(JSON.stringify(this.initialState.vault.vaultApp));
        this.vaultUser = JSON.parse(JSON.stringify(this.initialState.vault.vaultUser));
        this.vaultAppAliases = JSON.parse(JSON.stringify(this.initialState.vault.vaultAppAliases));
        this.vaultUserAliases = JSON.parse(JSON.stringify(this.initialState.vault.vaultUserAliases));
    } else if (tabContext === 'smarthost') {
        this.smarthosts = JSON.parse(JSON.stringify(this.initialState.smarthost.smarthosts));
        this.smartGlobals = JSON.parse(JSON.stringify(this.initialState.smarthost.smartGlobals));
        this.vaultSmarthost = JSON.parse(JSON.stringify(this.initialState.vault.vaultSmarthost));
    } else if (tabContext === 'server') {
        this.smtp = JSON.parse(JSON.stringify(this.initialState.server.smtp));
        this.smtp_meta = JSON.parse(JSON.stringify(this.initialState.server.smtp_meta));
    }
},

requestSave(formId) {
    let detectedChanges = [];

    if (formId === 'ui_form') {
        if (this.ui_loglevel !== this.initialState.ui.ui_loglevel) detectedChanges.push({ key: 'UI Log Level', old: this.initialState.ui.ui_loglevel, new: this.ui_loglevel, revert: () => this.ui_loglevel = this.initialState.ui.ui_loglevel });
        if (this.ui_tz !== this.initialState.ui.ui_tz) detectedChanges.push({ key: 'Display Timezone', old: this.initialState.ui.ui_tz, new: this.ui_tz, revert: () => this.ui_tz = this.initialState.ui.ui_tz });
        if (this.ui_fmt !== this.initialState.ui.ui_fmt) detectedChanges.push({ key: 'Date Format', old: this.initialState.ui.ui_fmt, new: this.ui_fmt, revert: () => this.ui_fmt = this.initialState.ui.ui_fmt });
        if (this.ui_relative !== this.initialState.ui.ui_relative) detectedChanges.push({ key: 'Relative Human Times', old: this.initialState.ui.ui_relative ? 'Enabled' : 'Disabled', new: this.ui_relative ? 'Enabled' : 'Disabled', revert: () => this.ui_relative = this.initialState.ui.ui_relative });
        if (this.ui_expand_adv !== this.initialState.ui.ui_expand_adv) detectedChanges.push({ key: 'Always Expand Routes', old: this.initialState.ui.ui_expand_adv ? 'Enabled' : 'Disabled', new: this.ui_expand_adv ? 'Enabled' : 'Disabled', revert: () => this.ui_expand_adv = this.initialState.ui.ui_expand_adv });
        if (this.ui_vault_sort !== this.initialState.ui.ui_vault_sort) detectedChanges.push({ key: 'Token Default Sort', old: this.initialState.ui.ui_vault_sort, new: this.ui_vault_sort, revert: () => this.ui_vault_sort = this.initialState.ui.ui_vault_sort });
        if (this.ui_smtp_sort !== this.initialState.ui.ui_smtp_sort) detectedChanges.push({ key: 'SMTP Users Sort', old: this.initialState.ui.ui_smtp_sort, new: this.ui_smtp_sort, revert: () => this.ui_smtp_sort = this.initialState.ui.ui_smtp_sort });
        if (this.ui_smarthost_sort !== this.initialState.ui.ui_smarthost_sort) detectedChanges.push({ key: 'Smarthost Sort', old: this.initialState.ui.ui_smarthost_sort, new: this.ui_smarthost_sort, revert: () => this.ui_smarthost_sort = this.initialState.ui.ui_smarthost_sort });
        if (JSON.stringify(this.uiListeners) !== JSON.stringify(this.initialState.ui.uiListeners)) detectedChanges.push({ key: 'UI Network Listeners', old: 'Modified', new: 'Modified', revert: () => this.uiListeners = JSON.parse(JSON.stringify(this.initialState.ui.uiListeners)) });
    } else if (formId === 'app_form') {
        if (this.smtp.default_route !== this.initialState.server.smtp.default_route) detectedChanges.push({ key: 'Default Catch-All Route', old: this.initialState.server.smtp.default_route, new: this.smtp.default_route, revert: () => this.smtp.default_route = this.initialState.server.smtp.default_route });
        if (this.smtp.loglevel !== this.initialState.server.smtp.loglevel) detectedChanges.push({ key: 'Gateway Log Level', old: this.initialState.server.smtp.loglevel, new: this.smtp.loglevel, revert: () => this.smtp.loglevel = this.initialState.server.smtp.loglevel });
        if (this.smtp.disable_persistence !== this.initialState.server.smtp.disable_persistence) detectedChanges.push({ key: 'Disk Persistence', old: this.initialState.server.smtp.disable_persistence ? 'Disabled' : 'Enabled', new: this.smtp.disable_persistence ? 'Disabled' : 'Enabled', revert: () => this.smtp.disable_persistence = this.initialState.server.smtp.disable_persistence });
        if (this.smtp.hostname !== this.initialState.server.smtp.hostname) detectedChanges.push({ key: 'Global Hostname', old: this.initialState.server.smtp.hostname || '(Empty)', new: this.smtp.hostname || '(Empty)', revert: () => this.smtp.hostname = this.initialState.server.smtp.hostname });
        if (this.smtp.queue_dir !== this.initialState.server.smtp.queue_dir) detectedChanges.push({ key: 'Queue Directory', old: this.initialState.server.smtp.queue_dir, new: this.smtp.queue_dir, revert: () => this.smtp.queue_dir = this.initialState.server.smtp.queue_dir });
        if (this.smtp.tls_cert_file !== this.initialState.server.smtp.tls_cert_file) detectedChanges.push({ key: 'Global TLS Cert', old: this.initialState.server.smtp.tls_cert_file || '(Auto)', new: this.smtp.tls_cert_file || '(Auto)', revert: () => this.smtp.tls_cert_file = this.initialState.server.smtp.tls_cert_file });
        if (this.smtp.tls_key_file !== this.initialState.server.smtp.tls_key_file) detectedChanges.push({ key: 'Global TLS Key', old: this.initialState.server.smtp.tls_key_file || '(Auto)', new: this.smtp.tls_key_file || '(Auto)', revert: () => this.smtp.tls_key_file = this.initialState.server.smtp.tls_key_file });

        if (JSON.stringify(this.smtp.listeners) !== JSON.stringify(this.initialState.server.smtp.listeners)) detectedChanges.push({ key: 'TCP Listeners', old: 'Modified', new: 'Modified', revert: () => this.smtp.listeners = JSON.parse(JSON.stringify(this.initialState.server.smtp.listeners)) });
        if (JSON.stringify(this.smtp.auth) !== JSON.stringify(this.initialState.server.smtp.auth)) detectedChanges.push({ key: 'SMTP Users', old: 'Modified', new: 'Modified', revert: () => { this.smtp.auth = JSON.parse(JSON.stringify(this.initialState.server.smtp.auth)); this.smtp_meta = JSON.parse(JSON.stringify(this.initialState.server.smtp_meta)); } });
        if (JSON.stringify(this.smarthosts) !== JSON.stringify(this.initialState.smarthost.smarthosts)) detectedChanges.push({ key: 'Smarthost Servers', old: 'Modified', new: 'Modified', revert: () => this.smarthosts = JSON.parse(JSON.stringify(this.initialState.smarthost.smarthosts)) });
        if (JSON.stringify(this.smartGlobals) !== JSON.stringify(this.initialState.smarthost.smartGlobals)) detectedChanges.push({ key: 'Smarthost Globals', old: 'Modified', new: 'Modified', revert: () => this.smartGlobals = JSON.parse(JSON.stringify(this.initialState.smarthost.smartGlobals)) });
        if (JSON.stringify(this.pushGlobals) !== JSON.stringify(this.initialState.pushover.pushGlobals)) detectedChanges.push({ key: 'Pushover Globals', old: 'Modified', new: 'Modified', revert: () => this.pushGlobals = JSON.parse(JSON.stringify(this.initialState.pushover.pushGlobals)) });

        const currentVaultStr = JSON.stringify({ vaultApp: this.vaultApp, vaultUser: this.vaultUser, vaultSmarthost: this.vaultSmarthost });
        const initialVaultStr = JSON.stringify({ vaultApp: this.initialState.vault.vaultApp, vaultUser: this.initialState.vault.vaultUser, vaultSmarthost: this.initialState.vault.vaultSmarthost });
        if (initialVaultStr !== currentVaultStr) detectedChanges.push({ key: 'Token Vault (Secrets)', old: 'Modified', new: 'Modified', revert: () => {
            this.vaultApp = JSON.parse(JSON.stringify(this.initialState.vault.vaultApp));
            this.vaultUser = JSON.parse(JSON.stringify(this.initialState.vault.vaultUser));
            this.vaultSmarthost = JSON.parse(JSON.stringify(this.initialState.vault.vaultSmarthost));
            this.vaultAppAliases = JSON.parse(JSON.stringify(this.initialState.vault.vaultAppAliases));
            this.vaultUserAliases = JSON.parse(JSON.stringify(this.initialState.vault.vaultUserAliases));
        } });

        const cleanOldRoutes = this.initialState.routes.mappings.map(({_uid, ...rest}) => rest);
        const cleanNewRoutes = this.mappings.map(({_uid, ...rest}) => rest);
        if (JSON.stringify(cleanOldRoutes) !== JSON.stringify(cleanNewRoutes)) detectedChanges.push({ key: 'Email Routes & Mappings', old: 'Modified', new: 'Modified', revert: () => this.mappings = JSON.parse(JSON.stringify(this.initialState.routes.mappings)) });
    }

    if (detectedChanges.length > 0) {
        this.diffModal.changes = detectedChanges;
        this.diffModal.targetForm = formId;
        this.diffModal.open = true;
    }
},

discardAllChanges() {
    if (this.diffModal.targetForm === 'ui_form') {
        this.resetTab('ui');
    } else {
        ['routes', 'pushover', 'smarthost', 'server'].forEach(t => this.resetTab(t));
    }
    this.diffModal.open = false;
},

revertChange(idx) {
    this.diffModal.changes[idx].revert();
    this.diffModal.changes.splice(idx, 1);
    if (this.diffModal.changes.length === 0) {
        this.diffModal.open = false;
    }
},

confirmSave() {
    if (this.diffModal.targetForm === 'ui_form') {
        if (!this.checkTimezone()) {
            this.diffModal.open = false;
            return;
        }
    }
    this.diffModal.open = false;
    const f = document.getElementById(this.diffModal.targetForm);
    if (f) htmx.trigger(f, 'submit');
},
