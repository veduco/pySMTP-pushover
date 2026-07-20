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
        listeners: this.clone(this.uiListeners || []),
        backend_mode: this.ui_backend_remote ? 'remote' : 'local',
        local_config_path: this.ui_local_config_path,
        primary_host: this.ui_primary_host,
        remote_hosts: this.clone(this.ui_remote_hosts || []),
        remote_secrets: this.clone(this.ui_remote_secrets || []),
        allowed_cidrs: this.clone(this.ui_allowed_cidrs || []),
        trust_proxy_cidrs: this.clone(this.ui_trust_proxy_cidrs || [])
    };
},

_generatePatches(obj1, obj2, path = '') {
    const patches = [];
    const allKeys = new Set([...Object.keys(obj1 || {}), ...Object.keys(obj2 || {})]);

    for (const key of allKeys) {
        // Strip transient background synchronization pointers from the diff evaluator
        if (['sync_status', 'last_secret_hash', 'expected_hash'].includes(key)) continue;

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
                    value: val2 !== undefined ? this.clone(val2) : undefined,
                    oldValue: val1 !== undefined ? this.clone(val1) : undefined
                });
            }
        }
    }
    return patches;
},

translatePatchToHuman(patchItem) {
    const path = patchItem.path || '';

    // Natively intercept mapping order alterations
    if (path === '/route_mappings_order') return 'Route Mapping Execution Order';

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
        'primary_host': 'Primary Configuration Host',
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
        'dedupe_keys': 'Deduplication Keys',
        '_key': 'Target Address / Pattern',
        '_isRegex': 'Regex Enabled',
        'match': 'Match Target',
        'method': 'Routing Method',
        'smarthost_alias': 'Smarthost Alias',
        'priority': 'Priority',
        'device': 'Target Device',
        'sound': 'Alert Sound',
        'url': 'Supplementary URL',
        'url_title': 'URL Title',
        'retry': 'Retry Interval',
        'expire': 'Expiration Time',
        'token': 'App Token',
        'user': 'User Key'
    };

    if (segments[0] === 'route_mappings' && segments[1]) {
        const uid = segments[1];
        const field = segments[2] || 'Configuration';

        // Extract the correct human-readable route string, prioritizing the original state for labels
        let oldMap = null;
        if (this.snapshots && this.snapshots.routes) {
            const oldArray = JSON.parse(this.snapshots.routes);
            oldMap = oldArray.find(m => m._uid === uid);
        }
        const newMap = this.mappings.find(m => m._uid === uid);

        const targetMap = oldMap || newMap || {};
        const routeKey = targetMap._isRegex ? `regex:${targetMap._key || ''}` : (targetMap._key || '');

        const mappedField = labelMap[field] || field;
        return `Route Mapping Rule [${routeKey}] -> ${mappedField}`;
    }
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
    if (segments[0] === 'remoteHosts' && segments[1]) {
        const field = segments[2] || 'Configuration';
        return `Remote Sync Node [${segments[1]}] -> ${labelMap[field] || field}`;
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
        smtp: this.clone(this.smtp),
        pushover: { ...this.pushGlobals },
        smarthost: {
            globals: {
                alias: this.smartGlobals.alias || '',
                force_plaintext: this.smartGlobals.force_plaintext === true,
                attachments: !this.smartGlobals.disable_attachments // Map UI inverse to Schema
            },
            aliases: this.clone(this.smarthosts)
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

formatDiffValue(val, path = '', op = 'replace') {
    if (op === 'remove') return '[Deleted]';

    // Allow tracking order elements to bypass stringification blocks safely
    if (path === '/route_mappings_order') return val;

    // Intercept the primary_host pointer to resolve the human-friendly alias dynamically
    if (path === '/ui/primary_host' && typeof val === 'string' && val !== '') {
        // Cross-reference current live list and the unmodified snapshot safely
        let foundHost = this.ui_remote_hosts.find(h => (h.host + ':' + h.port) === val);
        if (!foundHost && this.snapshots && this.snapshots.backend) {
            const oldBackend = JSON.parse(this.snapshots.backend);
            foundHost = (oldBackend.remote_hosts || []).find(h => (h.host + ':' + h.port) === val);
        }
        if (foundHost && foundHost.alias && foundHost.alias.trim() !== '') {
            return `${foundHost.alias} [${val}]`;
        }
        return val;
    }

    // Declarative Vault masking enforcement
    if (this.isPathSensitive(path)) {
        const allAliases = [...(this.vaultAppAliases || []), ...(this.vaultUserAliases || [])];
        const isAlias = typeof val === 'string' && allAliases.includes(val);
        if (val && val !== '') {
            return isAlias ? `[Alias] ${val}` : '••••••••';
        }
        return 'None';
    }

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
        routes: JSON.stringify(this.mappings.map(({_showToken, _showUser, _showAdv, _tokenAliasVal, _tokenRaw, _userAliasVal, _userRaw, ...rest}) => rest)),
        pushover: JSON.stringify({ pushGlobals: this.pushGlobals, vaultApp: this.vaultApp, vaultUser: this.vaultUser }),
        smarthost: JSON.stringify({ smarthosts: this.smarthosts, smartGlobals: this.smartGlobals, vaultSmarthost: this.vaultSmarthost }),
        server: JSON.stringify(this.smtp),
        backend: JSON.stringify({
            backend_remote: this.ui_backend_remote, local_config_path: this.ui_local_config_path,
            primary_host: this.ui_primary_host, remote_hosts: this.ui_remote_hosts
        }),
        ui: JSON.stringify(this._buildUiStatePayload())
    };
    this.initialState = this.clone({
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
        const oldUi = { ...this.rawUiConfig }; delete oldUi.listeners; delete oldUi.remote_hosts;
        const newUiObj = { ...newUi }; delete newUiObj.listeners; delete newUiObj.remote_hosts;
        rawPatches.push(...this._generatePatches(oldUi, newUiObj, '/ui'));

        const oldUiListeners = Object.fromEntries((this.rawUiConfig.listeners || []).map(x => [x.bind, x]));
        const newUiListeners = Object.fromEntries((newUi.listeners || []).map(x => [x.bind, x]));
        rawPatches.push(...this._generatePatches(oldUiListeners, newUiListeners, '/uiListeners'));

        const oldHosts = Object.fromEntries((this.rawUiConfig.remote_hosts || []).map(x => [x.host + ":" + x.port, x]));
        const newHosts = Object.fromEntries((newUi.remote_hosts || []).map(x => [x.host + ":" + x.port, x]));
        rawPatches.push(...this._generatePatches(oldHosts, newHosts, '/remoteHosts'));

    } else {
        if (this.tab === 'routes') {
            // Diff internal mapping configurations natively via hidden UIDs
            const oldMappings = JSON.parse(this.snapshots.routes || '[]');
            const newMappings = this.mappings.map(({_showToken, _showUser, _showAdv, _tokenAliasVal, _tokenRaw, _userAliasVal, _userRaw, ...rest}) => rest);

            const oldMappingsDict = Object.fromEntries(oldMappings.map(m => [m._uid, m]));
            const newMappingsDict = Object.fromEntries(newMappings.map(m => [m._uid, m]));

            rawPatches.push(...this._generatePatches(oldMappingsDict, newMappingsDict, '/route_mappings'));

            // Capture positional ordering changes explicitly by filtering out non-shared elements first
            const oldUids = oldMappings.map(m => m._uid);
            const newUids = newMappings.map(m => m._uid);

            const oldSharedOrder = oldUids.filter(uid => newUids.includes(uid)).join(',');
            const newSharedOrder = newUids.filter(uid => oldUids.includes(uid)).join(',');

            if (oldSharedOrder !== newSharedOrder) {
                rawPatches.push({
                    op: 'replace',
                    path: '/route_mappings_order',
                    value: 'Reordered',
                    oldValue: 'Original Order'
                });
            }

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

    // Consolidated patch routing formatting
    for (const patch of rawPatches) {
        this.diffModal.changes.push({
            op: patch.op,
            path: patch.path,
            key: patch.path,
            humanLabel: this.translatePatchToHuman(patch),
            old: this.formatDiffValue(patch.oldValue, patch.path, 'replace'),
            new: this.formatDiffValue(patch.value, patch.path, patch.op),
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

// Declarative mapping schema for UI structural reversions
_schemaRestoreMaps: {
    ui: {
        backend_mode: { prop: 'ui_backend_remote', coerce: v => v === 'remote' },
        local_config_path: { prop: 'ui_local_config_path', fallback: 'config.json' },
        primary_host: { prop: 'ui_primary_host', fallback: '' },
        remote_verify_tls: { prop: 'ui_remote_verify_tls', coerce: v => v === true },
        ui_loglevel: { prop: 'ui_loglevel', fallback: 'INFO' },
        timezone: { prop: 'ui_tz', fallback: 'UTC' },
        date_format: { prop: 'ui_fmt', fallback: 'YYYY-MM-DD HH:mm:ss' },
        relative_time: { prop: 'ui_relative', coerce: v => v === true },
        expand_adv: { prop: 'ui_expand_adv', coerce: v => v === true },
        trust_proxy: { prop: 'ui_trust_proxy', coerce: v => v === true },
        trust_proxy_cidrs: { prop: 'ui_trust_proxy_cidrs', isArray: true },
        allowed_cidrs: { prop: 'ui_allowed_cidrs', isArray: true },
        vault_sort: { prop: 'ui_vault_sort', fallback: 'name_asc' },
        smtp_sort: { prop: 'ui_smtp_sort', fallback: 'name_asc' },
        smarthost_sort: { prop: 'ui_smarthost_sort', fallback: 'alias_asc' }
    },
    pushover: {
        attachments: { prop: 'disable_attachments', target: 'pushGlobals', coerce: v => v === false },
        '*': { target: 'pushGlobals', fallback: '' }
    },
    smarthost_globals: {
        alias: { prop: 'alias', target: 'smartGlobals', fallback: '' },
        force_plaintext: { prop: 'force_plaintext', target: 'smartGlobals', coerce: v => v === true },
        attachments: { prop: 'disable_attachments', target: 'smartGlobals', coerce: v => v === false }
    }
},

_applySchemaRestore(domain, key, val) {
    const mapGroup = this._schemaRestoreMaps[domain];
    if (!mapGroup) return false;

    let rule = mapGroup[key] || mapGroup['*'];
    if (!rule) return false;

    const targetObj = rule.target ? this[rule.target] : this;
    const targetProp = rule.prop || key;

    if (rule.coerce) {
        targetObj[targetProp] = rule.coerce(val);
    } else if (rule.isArray) {
        targetObj[targetProp] = Array.isArray(val) ? this.clone(val) : [];
    } else {
        targetObj[targetProp] = val !== undefined && val !== null ? val : rule.fallback;
    }
    return true;
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

            if (shObj.smarthosts[shAlias]) this.smarthosts[shAlias] = this.clone(shObj.smarthosts[shAlias]);
            else delete this.smarthosts[shAlias];

            if (shObj.vaultSmarthost[shAlias]) this.vaultSmarthost[shAlias] = this.clone(shObj.vaultSmarthost[shAlias]);
            else delete this.vaultSmarthost[shAlias];

            this.diffModal.changes = this.diffModal.changes.filter(c => {
                const cSegments = c.path.split('/').filter(Boolean).map(s => s.replace(/~1/g, '/'));
                const cAlias = cSegments[1] === 'aliases' ? cSegments[2] : cSegments[1];
                return cAlias !== shAlias;
            });
            isComplexReset = true;
        }
    } else if (path.startsWith('/vaultApp')) {
        this.vaultApp = this.clone(JSON.parse(this.snapshots.pushover).vaultApp);
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/vaultApp'));
        isComplexReset = true;
    } else if (path.startsWith('/vaultUser')) {
        this.vaultUser = this.clone(JSON.parse(this.snapshots.pushover).vaultUser);
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/vaultUser'));
        isComplexReset = true;
    } else if (path.startsWith('/smtpListeners')) {
        this.smtp.listeners = this.clone(JSON.parse(this.snapshots.server).listeners || []);
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/smtpListeners'));
        isComplexReset = true;
    } else if (path.startsWith('/uiListeners')) {
        this.uiListeners = this.clone(JSON.parse(this.snapshots.ui).uiListeners || []);
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/uiListeners'));
        isComplexReset = true;
    } else if (path.startsWith('/remoteHosts')) {
        this.ui_remote_hosts = this.clone(JSON.parse(this.snapshots.backend).remote_hosts || []);
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/remoteHosts'));
        isComplexReset = true;
    } else if (path.startsWith('/route_mappings') || path === '/route_mappings_order') {
        this.resetTab('routes');
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/route_mappings') && c.path !== '/route_mappings_order');
        isComplexReset = true;
    } else if (path.startsWith('/routes')) {
        this.resetTab('routes');
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.path.startsWith('/routes'));
        isComplexReset = true;
    }

    // 2. Simple Scalar Inverse Patches routed via Schema Dict Evaluation
    if (!isComplexReset) {
        const segments = path.split('/').filter(Boolean).map(s => s.replace(/~1/g, '/'));
        const root = segments[0];
        const key = segments[segments.length - 1];

        if (root === 'ui') {
            this._applySchemaRestore('ui', key, val);
        } else if (root === 'smtp') {
            this.smtp[key] = (typeof val === 'object' && val !== null) ? this.clone(val) : val;
        } else if (root === 'pushover') {
            this._applySchemaRestore('pushover', key, val);
        } else if (root === 'smarthost' && segments[1] === 'globals') {
            this._applySchemaRestore('smarthost_globals', key, val);
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
    const backup = this.clone(this.initialState);

    // Schema-driven hydration mapping clears all raw hardcoded parameter logic
    if (tabContext === 'ui' || tabContext === 'backend') {
        const uiObj = backup.ui || {};
        Object.keys(this._schemaRestoreMaps.ui).forEach(k => this._applySchemaRestore('ui', k, uiObj[k]));

        this.uiListeners = this.clone(uiObj.listeners || []);
        this.ui_remote_hosts = this.clone(uiObj.remote_hosts || []);
        this.ui_primary_host = uiObj.primary_host || '';
        this.uiTrustProxyCidrInput = '';
        this.errors.uiTrustProxyCidr = '';
        this.errors.tz = '';
        this.uiCidrInput = '';
        this.errors.uiCidr = '';
    }

    if (tabContext === 'pushover') {
        this.pushGlobals = this.clone(backup.pushover.pushGlobals);
        this.vaultApp = this.clone(backup.vault.vaultApp);
        this.vaultUser = this.clone(backup.vault.vaultUser);
        this.vaultAppAliases = this.vaultApp.map(x => x.name);
        this.vaultUserAliases = this.vaultUser.map(x => x.name);
    }

    if (tabContext === 'routes') {
        this.mappings = this.clone(backup.routes.mappings);
    }

    if (tabContext === 'smarthost') {
        this.smarthosts = this.clone(backup.smarthost.smarthosts);
        this.smartGlobals = this.clone(backup.smarthost.smartGlobals);
        this.vaultSmarthost = this.clone(backup.vault.vaultSmarthost);
    }

    if (tabContext === 'server') {
        this.smtp = this.clone(backup.server.smtp);
        this.smtp_meta = this.clone(backup.server.smtp_meta);
        this.smtpCidrInput = '';
        this.errors.smtpCidr = '';
        this.errors.dedupeWindow = '';
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
