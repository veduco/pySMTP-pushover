_deepClone(obj) {
    if (obj === undefined) return undefined;
    return JSON.parse(JSON.stringify(obj));
},

_buildUiStatePayload() {
    return {
        timezone: this.ui_tz,
        date_format: this.ui_fmt,
        relative_time: this.ui_relative,
        expand_adv: this.ui_expand_adv,
        trust_proxy: this.ui_trust_proxy,
        vault_sort: this.ui_vault_sort,
        smtp_sort: this.ui_smtp_sort,
        smarthost_sort: this.ui_smarthost_sort,
        ui_loglevel: this.ui_loglevel,
        listeners: this._deepClone(this.uiListeners || []),
        backend_mode: this.ui_backend_remote ? 'remote' : 'local',
        local_config_path: this.ui_local_config_path,
        remote_url: this.ui_remote_url,
        remote_secret: this.ui_remote_secret,
        remote_verify_tls: this.ui_remote_verify_tls,
        allowed_cidrs: this._deepClone(this.ui_allowed_cidrs || []),
        trust_proxy_cidrs: this._deepClone(this.ui_trust_proxy_cidrs || [])
    };
},

_generatePatches(obj1, obj2, path = '') {
    const patches = [];
    const allKeys = new Set([...Object.keys(obj1 || {}), ...Object.keys(obj2 || {})]);

    for (const key of allKeys) {
        const val1 = obj1?.[key];
        const val2 = obj2?.[key];
        const escapedKey = key.replace(/\//g, '~1'); // JSON Pointer escaping
        const currentPath = path === '' ? `/${escapedKey}` : `${path}/${escapedKey}`;

        if (JSON.stringify(val1) !== JSON.stringify(val2)) {
            // Mask dictionary objects to recursively drill, but leave Arrays intact as distinct blocks
            if (typeof val1 === 'object' && val1 !== null && !Array.isArray(val1) &&
                typeof val2 === 'object' && val2 !== null && !Array.isArray(val2)) {
                patches.push(...this._generatePatches(val1, val2, currentPath));
            } else {
                patches.push({
                    op: val1 === undefined ? 'add' : (val2 === undefined ? 'remove' : 'replace'),
                    path: currentPath,
                    value: val2 !== undefined ? this._deepClone(val2) : undefined,
                    oldValue: val1 !== undefined ? this._deepClone(val1) : undefined
                });
            }
        }
    }
    return patches;
},

translatePatchToHuman(patchItem) {
    const path = patchItem.path || '';
    const segments = path.split('/').filter(Boolean).map(s => s.replace(/~1/g, '/'));

    const labelMap = {
        'loglevel': 'Log Level Severity',
        'timezone': 'Display Timezone',
        'date_format': 'Date Format',
        'trust_proxy': 'Trust Proxy Headers',
        'starttls': 'STARTTLS Status',
        'proxy_protocol': 'PROXY v2',
        'backend_mode': 'Backend Engine Mode',
        'local_config_path': 'Local Config Path',
        'remote_url': 'Remote API URL',
        'remote_secret': 'Remote API Secret',
        'remote_verify_tls': 'Verify Remote TLS',
        'ui_loglevel': 'UI Log Level',
        'relative_time': 'Relative Time Display',
        'expand_adv': 'Auto-Expand Advanced',
        'trust_proxy_cidrs': 'Trusted Proxy CIDRs',
        'allowed_cidrs': 'Allowed IPs/CIDRs',
        'disable_attachments': 'Disable Attachments',
        'attachments': 'Enable Attachments',
        'force_plaintext': 'Force Plaintext',
        'dedupe_enabled': 'Deduplication Status',
        'dedupe_window': 'Deduplication Cache Window',
        'dedupe_keys': 'Deduplication Keys'
    };

    if (segments[0] === 'routes' && segments[1]) {
        const field = segments[2] || 'Configuration';
        return `Route Mapping Rule [${segments[1]}] -> ${labelMap[field] || field}`;
    }
    if (segments[0] === 'smtpListeners' && segments[1]) {
        const field = segments[2] || 'Binding';
        return `SMTP Port Listener [${segments[1]}] -> ${labelMap[field] || field}`;
    }
    if (segments[0] === 'uiListeners' && segments[1]) {
        const field = segments[2] || 'Binding';
        return `UI Port Listener [${segments[1]}] -> ${labelMap[field] || field}`;
    }
    if (segments[0] === 'smarthost' && segments[1] === 'aliases' && segments[2]) {
        const field = segments[3] || 'Configuration';
        return `Smarthost [${segments[2]}] -> ${labelMap[field] || field}`;
    }
    if (segments[0] === 'vaultApp' && segments[1]) {
        return `App Token Vault [${segments[1]}]`;
    }
    if (segments[0] === 'vaultUser' && segments[1]) {
        return `User Key Vault [${segments[1]}]`;
    }
    if (segments[0] === 'vaultSmarthost' && segments[1]) {
        return `Smarthost Vault Password [${segments[1]}]`;
    }

    const leafKey = segments[segments.length - 1] || 'Unknown';
    return labelMap[leafKey] || `Parameter -> ${leafKey.charAt(0).toUpperCase() + leafKey.slice(1)}`;
},

isPathSensitive(path) {
    if (!path) return false;
    const lower = path.toLowerCase();
    return lower.includes('token') ||
           lower.includes('user') ||
           lower.includes('password') ||
           lower.includes('secret') ||
           lower.includes('auth') ||
           lower.includes('vaultsmarthost');
},

preparePayload() {
    const payload = {
        smtp: this._deepClone(this.smtp),
        pushover: { ...this.pushGlobals },
        smarthost: {
            globals: {
                alias: this.smartGlobals.alias || '',
                force_plaintext: this.smartGlobals.force_plaintext === true,
                attachments: !this.smartGlobals.disable_attachments // Map UI inverse to Schema
            },
            aliases: this._deepClone(this.smarthosts)
        },
        routes: {}
    };

    payload.pushover.attachments = !payload.pushover.disable_attachments;
    delete payload.pushover.disable_attachments;

    delete payload.pushover._isTokenAlias; delete payload.pushover._tokenAliasVal; delete payload.pushover._tokenRaw; delete payload.pushover._showToken;
    delete payload.pushover._isUserAlias; delete payload.pushover._userAliasVal; delete payload.pushover._userRaw; delete payload.pushover._showUser;

    this.mappings.forEach(m => {
        let fKey = m._isRegex ? `regex:${m._key}` : m._key;
        const rObj = { match: m.match, method: m.method, disable_attachments: m.disable_attachments, force_plaintext: m.force_plaintext };

        if (m.method === 'pushover') {
            rObj.token = m.token;
            rObj.user = m.user;
            ['device','sound','url','url_title','tags','priority','ttl','retry','expire'].forEach(k => {
                if (m[k] !== undefined && m[k] !== '') rObj[k] = m[k];
            });
        } else {
            rObj.smarthost_alias = m.smarthost_alias;
        }
        payload.routes[fKey] = rObj;
    });

    return JSON.stringify(payload);
},

prepareVaultPayload() {
    return JSON.stringify({
        app: this.vaultApp.map(x => ({ name: x.name, token: x.token, epoch: x.epoch })),
        user: this.vaultUser.map(x => ({ name: x.name, token: x.token, epoch: x.epoch })),
        smarthost: Object.fromEntries(Object.keys(this.smarthosts).map(k => [k, this.vaultSmarthost[k]?.token || '']))
    });
},

formatDiffValue(val) {
    if (val === null || val === undefined) return 'None';
    if (typeof val === 'boolean') return val ? 'True' : 'False';
    if (Array.isArray(val) && val.length === 0) return 'None';
    if (Array.isArray(val)) return val.join('<br>');
    if (typeof val === 'object' && val !== null) return '[Configured]';

    let strVal = String(val);
    if (strVal === '') return 'None';
    if (strVal.includes('\n') || strVal.includes('\\n')) {
        return strVal.replace(/\\n/g, '<br>').replace(/\n/g, '<br>');
    }
    return strVal;
},

takeSnapshot() {
    this.rawConfig = JSON.parse(this.preparePayload());
    this.rawVault = JSON.parse(this.prepareVaultPayload());
    this.rawUiConfig = this._buildUiStatePayload();

    this.snapshots = {
        routes: JSON.stringify(this.mappings.map(({_uid, _showToken, _showUser, _tokenAliasVal, _tokenRaw, _userAliasVal, _userRaw, ...rest}) => rest)),
        pushover: JSON.stringify({ pushGlobals: this.pushGlobals, vaultApp: this.vaultApp, vaultUser: this.vaultUser }),
        smarthost: JSON.stringify({ smarthosts: this.smarthosts, smartGlobals: this.smartGlobals, vaultSmarthost: this.vaultSmarthost }),
        server: JSON.stringify(this.smtp),
        backend: JSON.stringify({
            backend_remote: this.ui_backend_remote, local_config_path: this.ui_local_config_path,
            remote_url: this.ui_remote_url, remote_secret: this.ui_remote_secret, remote_verify_tls: this.ui_remote_verify_tls
        }),
        ui: JSON.stringify(this._buildUiStatePayload())
    };
    this.initialState = this._deepClone({
        ui: this.rawUiConfig,
        routes: { mappings: this.mappings },
        pushover: { pushGlobals: this.pushGlobals },
        smarthost: { smarthosts: this.smarthosts, smartGlobals: this.smartGlobals },
        server: { smtp: this.smtp, smtp_meta: this.smtp_meta },
        vault: { vaultApp: this.vaultApp, vaultUser: this.vaultUser, vaultSmarthost: this.vaultSmarthost, vaultAppAliases: this.vaultAppAliases, vaultUserAliases: this.vaultUserAliases }
    });
},

requestSave(formId) {
    this.diffModal.targetForm = formId;
    this.diffModal.changes = [];

    const newConfig = JSON.parse(this.preparePayload());
    const newVault = JSON.parse(this.prepareVaultPayload());
    const newUi = this._buildUiStatePayload();

    let rawPatches = [];

    if (formId === 'backend_form' || formId === 'ui_form') {
        const oldUi = { ...this.rawUiConfig }; delete oldUi.listeners;
        const newUiObj = { ...newUi }; delete newUiObj.listeners;
        rawPatches.push(...this._generatePatches(oldUi, newUiObj, '/ui'));

        const oldUiListeners = Object.fromEntries((this.rawUiConfig.listeners || []).map(x => [x.bind, x]));
        const newUiListeners = Object.fromEntries((newUi.listeners || []).map(x => [x.bind, x]));
        rawPatches.push(...this._generatePatches(oldUiListeners, newUiListeners, '/uiListeners'));
    } else {
        if (this.tab === 'routes') {
            rawPatches.push(...this._generatePatches(this.rawConfig.routes || {}, newConfig.routes || {}, '/routes'));
        } else if (this.tab === 'pushover') {
            rawPatches.push(...this._generatePatches(this.rawConfig.pushover || {}, newConfig.pushover || {}, '/pushover'));

            const oldVaultApp = Object.fromEntries((this.rawVault.app || []).map(x => [x.name, x]));
            const newVaultApp = Object.fromEntries((newVault.app || []).map(x => [x.name, x]));
            rawPatches.push(...this._generatePatches(oldVaultApp, newVaultApp, '/vaultApp'));

            const oldVaultUser = Object.fromEntries((this.rawVault.user || []).map(x => [x.name, x]));
            const newVaultUser = Object.fromEntries((newVault.user || []).map(x => [x.name, x]));
            rawPatches.push(...this._generatePatches(oldVaultUser, newVaultUser, '/vaultUser'));

        } else if (this.tab === 'smarthost') {
            rawPatches.push(...this._generatePatches(this.rawConfig.smarthost || {}, newConfig.smarthost || {}, '/smarthost'));
            rawPatches.push(...this._generatePatches(this.rawVault.smarthost || {}, newVault.smarthost || {}, '/vaultSmarthost'));
        } else if (this.tab === 'server') {
            const oldSmtp = { ...this.rawConfig.smtp }; delete oldSmtp.listeners;
            const newSmtp = { ...newConfig.smtp }; delete newSmtp.listeners;
            rawPatches.push(...this._generatePatches(oldSmtp, newSmtp, '/smtp'));

            const oldSmtpListeners = Object.fromEntries((this.rawConfig.smtp?.listeners || []).map(x => [x.bind, x]));
            const newSmtpListeners = Object.fromEntries((newConfig.smtp?.listeners || []).map(x => [x.bind, x]));
            rawPatches.push(...this._generatePatches(oldSmtpListeners, newSmtpListeners, '/smtpListeners'));
        }
    }

    // Translate raw generic patches down into the highly contextual UI table variables seamlessly
    for (const patch of rawPatches) {
        let displayOld = patch.oldValue;
        let displayNew = patch.value;

        if (this.isPathSensitive(patch.path)) {
            const allAliases = [...(this.vaultAppAliases || []), ...(this.vaultUserAliases || [])];
            const oldIsAlias = typeof displayOld === 'string' && allAliases.includes(displayOld);
            const newIsAlias = typeof displayNew === 'string' && allAliases.includes(displayNew);

            displayOld = (displayOld && displayOld !== '') ? (oldIsAlias ? `[Alias] ${displayOld}` : '••••••••') : 'None';
            displayNew = (displayNew && displayNew !== '') ? (newIsAlias ? `[Alias] ${displayNew}` : '••••••••') : 'None';
        }

        this.diffModal.changes.push({
            op: patch.op,
            path: patch.path,
            key: patch.path, // Ensures backward compatibility with html array looping binds
            humanLabel: this.translatePatchToHuman(patch),
            old: this.formatDiffValue(displayOld),
            new: patch.op === 'remove' ? '[Deleted]' : this.formatDiffValue(displayNew),
            originalValue: patch.oldValue
        });
    }

    if (this.diffModal.changes.length === 0) {
        this.confirmSave();
        return;
    }

    this.diffModal.open = true;
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

revertChange(idx) {
    const item = this.diffModal.changes[idx];
    const path = item.path;
    const val = item.originalValue;
    let isComplexReset = false;

    // 1. Structural Inverse Patches (Arrays / Matrix Objects / Dynamic UI tables)
    if (path.startsWith('/smarthost/aliases') || path.startsWith('/vaultSmarthost')) {
        const segments = path.split('/').filter(Boolean).map(s => s.replace(/~1/g, '/'));
        const shAlias = segments[1] === 'aliases' ? segments[2] : segments[1];
        if (shAlias) {
            const shObj = JSON.parse(this.snapshots.smarthost);

            if (shObj.smarthosts[shAlias]) this.smarthosts[shAlias] = this._deepClone(shObj.smarthosts[shAlias]);
            else delete this.smarthosts[shAlias];

            if (shObj.vaultSmarthost[shAlias]) this.vaultSmarthost[shAlias] = this._deepClone(shObj.vaultSmarthost[shAlias]);
            else delete this.vaultSmarthost[shAlias];

            this.diffModal.changes = this.diffModal.changes.filter(c => {
                const cSegments = c.path.split('/').filter(Boolean).map(s => s.replace(/~1/g, '/'));
                const cAlias = cSegments[1] === 'aliases' ? cSegments[2] : cSegments[1];
                return cAlias !== shAlias;
            });
            isComplexReset = true;
        }
    } else if (path.startsWith('/vaultApp')) {
        this.vaultApp = this._deepClone(JSON.parse(this.snapshots.pushover).vaultApp);
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/vaultApp'));
        isComplexReset = true;
    } else if (path.startsWith('/vaultUser')) {
        this.vaultUser = this._deepClone(JSON.parse(this.snapshots.pushover).vaultUser);
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/vaultUser'));
        isComplexReset = true;
    } else if (path.startsWith('/smtpListeners')) {
        this.smtp.listeners = this._deepClone(JSON.parse(this.snapshots.server).listeners || []);
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/smtpListeners'));
        isComplexReset = true;
    } else if (path.startsWith('/uiListeners')) {
        this.uiListeners = this._deepClone(JSON.parse(this.snapshots.ui).uiListeners || []);
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/uiListeners'));
        isComplexReset = true;
    } else if (path.startsWith('/routes')) {
        this.resetTab('routes');
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/routes'));
        isComplexReset = true;
    }

    // 2. Simple Scalar Inverse Patches (Primitive property mapping via target translation)
    if (!isComplexReset) {
        const segments = path.split('/').filter(Boolean).map(s => s.replace(/~1/g, '/'));
        const root = segments[0];
        const key = segments[segments.length - 1];

        if (root === 'ui') {
            if (key === 'backend_mode') this.ui_backend_remote = (val === 'remote');
            else if (key === 'local_config_path') this.ui_local_config_path = val || 'config.json';
            else if (key === 'remote_url') this.ui_remote_url = val || '';
            else if (key === 'remote_secret') this.ui_remote_secret = val || '';
            else if (key === 'remote_verify_tls') this.ui_remote_verify_tls = (val === true);
            else if (key === 'ui_loglevel') this.ui_loglevel = val || 'INFO';
            else if (key === 'timezone') this.ui_tz = val || 'UTC';
            else if (key === 'date_format') this.ui_fmt = val || 'YYYY-MM-DD HH:mm:ss';
            else if (key === 'relative_time') this.ui_relative = (val === true);
            else if (key === 'expand_adv') this.ui_expand_adv = (val === true);
            else if (key === 'trust_proxy') this.ui_trust_proxy = (val === true);
            else if (key === 'trust_proxy_cidrs') this.ui_trust_proxy_cidrs = Array.isArray(val) ? this._deepClone(val) : [];
            else if (key === 'allowed_cidrs') this.ui_allowed_cidrs = Array.isArray(val) ? this._deepClone(val) : [];
            else if (key === 'vault_sort') this.ui_vault_sort = val || 'name_asc';
            else if (key === 'smtp_sort') this.ui_smtp_sort = val || 'name_asc';
            else if (key === 'smarthost_sort') this.ui_smarthost_sort = val || 'alias_asc';
        } else if (root === 'smtp') {
            this.smtp[key] = (typeof val === 'object' && val !== null) ? this._deepClone(val) : val;
        } else if (root === 'pushover') {
            if (key === 'attachments') this.pushGlobals.disable_attachments = (val === false); // Un-invert
            else this.pushGlobals[key] = val !== undefined ? val : '';
        } else if (root === 'smarthost' && segments[1] === 'globals') {
            if (key === 'alias') this.smartGlobals.alias = val || '';
            if (key === 'force_plaintext') this.smartGlobals.force_plaintext = (val === true);
            if (key === 'attachments') this.smartGlobals.disable_attachments = (val === false); // Un-invert
        }

        const patchIndex = this.diffModal.changes.findIndex(c => c.path === path);
        if (patchIndex !== -1) this.diffModal.changes.splice(patchIndex, 1);
    }

    if (this.diffModal.changes.length === 0) {
        this.diffModal.open = false;
    }
},

discardAllChanges() {
    if (this.diffModal.targetForm === 'ui_form' || this.diffModal.targetForm === 'backend_form') {
        this.resetTab('ui');
        this.resetTab('backend');
    } else {
        this.resetTab(this.tab);
    }
    this.diffModal.open = false;
},

resetTab(tabContext) {
    if (!this.snapshots) return;
    const backup = this._deepClone(this.initialState);

    if (tabContext === 'ui' || tabContext === 'backend') {
        const uiObj = backup.ui || {};
        this.ui_backend_remote = uiObj.backend_mode === 'remote';
        this.ui_local_config_path = uiObj.local_config_path || 'config.json';
        this.ui_remote_url = uiObj.remote_url || '';
        this.ui_remote_secret = uiObj.remote_secret || '';
        this.ui_remote_verify_tls = uiObj.remote_verify_tls === true;
        this.ui_loglevel = uiObj.ui_loglevel || 'INFO';
        this.ui_tz = uiObj.timezone || 'UTC';
        this.ui_fmt = uiObj.date_format || 'YYYY-MM-DD HH:mm:ss';
        this.ui_relative = uiObj.relative_time === true;
        this.ui_expand_adv = uiObj.expand_adv === true;
        this.ui_trust_proxy = uiObj.trust_proxy === true;
        this.ui_trust_proxy_cidrs = this._deepClone(uiObj.trust_proxy_cidrs || []);
        this.uiTrustProxyCidrInput = '';
        this.uiTrustProxyCidrError = '';
        this.ui_vault_sort = uiObj.vault_sort || 'name_asc';
        this.ui_smtp_sort = uiObj.smtp_sort || 'name_asc';
        this.ui_smarthost_sort = uiObj.smarthost_sort || 'alias_asc';
        this.uiListeners = this._deepClone(uiObj.listeners || []);
        this.tzError = false;
        this.ui_allowed_cidrs = this._deepClone(uiObj.allowed_cidrs || []);
        this.uiCidrInput = '';
        this.uiCidrError = '';
    }

    if (tabContext === 'pushover') {
        this.pushGlobals = this._deepClone(backup.pushover.pushGlobals);
        this.vaultApp = this._deepClone(backup.vault.vaultApp);
        this.vaultUser = this._deepClone(backup.vault.vaultUser);
        this.vaultAppAliases = this.vaultApp.map(x => x.name);
        this.vaultUserAliases = this.vaultUser.map(x => x.name);
    }

    if (tabContext === 'routes') {
        this.mappings = this._deepClone(backup.routes.mappings);
    }

    if (tabContext === 'smarthost') {
        this.smarthosts = this._deepClone(backup.smarthost.smarthosts);
        this.smartGlobals = this._deepClone(backup.smarthost.smartGlobals);
        this.vaultSmarthost = this._deepClone(backup.vault.vaultSmarthost);
    }

    if (tabContext === 'server') {
        this.smtp = this._deepClone(backup.server.smtp);
        this.smtp_meta = this._deepClone(backup.server.smtp_meta);
        this.smtpCidrInput = '';
        this.smtpCidrError = '';
        this.dedupeWindowError = '';
    }
},

reorderRoute(oldIdx, newIdx) {
    if (oldIdx === newIdx || oldIdx === null) return;
    const item = this.mappings.splice(oldIdx, 1)[0];
    this.mappings.splice(newIdx, 0, item);
    this.draggedRouteIdx = null;
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

addMapping() {
    this.mappings.push({
        _uid: Date.now().toString(36) + Math.random().toString(36).substr(2),
        _key: '', match: 'to', method: 'pushover', token: '', user: '', _isRegex: false,
        _isTokenAlias: true, _isUserAlias: true,
        _tokenAliasVal: '', _tokenRaw: '', _userAliasVal: '', _userRaw: '', smarthost_alias: '',
        _showToken: false, _showUser: false, _showAdv: this.ui_expand_adv, disable_attachments: false, force_plaintext: false
    });
},
