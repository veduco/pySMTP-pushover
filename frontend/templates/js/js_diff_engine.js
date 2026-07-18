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
        listeners: JSON.parse(JSON.stringify(this.uiListeners || [])),
        backend_mode: this.ui_backend_remote ? 'remote' : 'local',
        local_config_path: this.ui_local_config_path,
        remote_url: this.ui_remote_url,
        remote_secret: this.ui_remote_secret,
        remote_verify_tls: this.ui_remote_verify_tls,
        allowed_cidrs: JSON.parse(JSON.stringify(this.ui_allowed_cidrs || [])),
        trust_proxy_cidrs: JSON.parse(JSON.stringify(this.ui_trust_proxy_cidrs || []))
    };
},

_getDiffs(obj1, obj2, path = '') {
    const diffs = [];
    const allKeys = new Set([...Object.keys(obj1 || {}), ...Object.keys(obj2 || {})]);
    for (const key of allKeys) {
        const val1 = obj1?.[key]; const val2 = obj2?.[key];
        const currentPath = path ? `${path}.${key}` : key;
        if (JSON.stringify(val1) !== JSON.stringify(val2)) {
            if (typeof val1 === 'object' && val1 !== null && !Array.isArray(val1) &&
                typeof val2 === 'object' && val2 !== null && !Array.isArray(val2)) {
                diffs.push(...this._getDiffs(val1, val2, currentPath));
            } else {
                let humanKey = currentPath;
                let m;

                const patternMap = [
                    { regex: /^Gateway Config\.routes\.(.+?)(?:\..+)?$/, label: m => `Route Mapping Rule [${m[1]}]` },
                    { regex: /^Gateway Config\.smtp\.listeners\.(.+?:\d+)(?:\.(?:bind|hostname|starttls|proxy_protocol|tls_cert_file|tls_key_file))?$/, label: m => `SMTP Port Listener [${m[1]}]` },
                    { regex: /^UI\/Backend Context\.listeners\.(.+?:\d+)(?:\.(?:bind|https|tls_cert|tls_key))?$/, label: m => `UI Port Listener [${m[1]}]` },
                    { regex: /^Gateway Config\.smarthost\.aliases\.(.+?)(?:\..+)?$/, label: m => `Smarthost Configuration [${m[1]}]` },
                    { regex: /^Token Vault\.app\.(.+?)(?:\..+)?$/, label: m => `App Token Vault [${m[1]}]` },
                    { regex: /^Token Vault\.user\.(.+?)(?:\..+)?$/, label: m => `User Key Vault [${m[1]}]` },
                    { regex: /^Token Vault\.smarthost\.(.+?)(?:\..+)?$/, label: m => `Smarthost Vault Password [${m[1]}]` }
                ];

                let matchedPattern = false;
                for (const entry of patternMap) {
                    if ((m = currentPath.match(entry.regex))) {
                        humanKey = entry.label(m);
                        matchedPattern = true;
                        break;
                    }
                }

                if (!matchedPattern) {
                    if (currentPath.startsWith('UI/Backend Context.')) {
                        humanKey = `UI Parameter -> ${currentPath.split('.')[1] || 'Unknown'}`;
                    } else if (currentPath.startsWith('Gateway Config.')) {
                        humanKey = `Gateway Parameter -> ${currentPath.split('.').pop()}`;
                    }
                }

                let displayOld = (val1 !== undefined && val1 !== '') ? val1 : 'None';
                let displayNew = (val2 !== undefined && val2 !== '') ? val2 : 'None';

                if (Array.isArray(displayOld) && displayOld.length === 0) displayOld = 'None';
                if (Array.isArray(displayNew) && displayNew.length === 0) displayNew = 'None';

                // Mask dictionary objects, but leave Arrays alone to be formatted
                if (typeof displayOld === 'object' && displayOld !== null && !Array.isArray(displayOld)) displayOld = '[Configured]';
                if (typeof displayNew === 'object' && displayNew !== null && !Array.isArray(displayNew)) displayNew = '[Configured]';

                if (displayOld === '[Configured]' && displayNew === 'None') displayNew = '[Deleted]';
                if (displayOld === 'None' && displayNew === '[Configured]') displayOld = '[Not Configured]';

                const isSensitive = ['token', 'user', 'password', 'secret'].includes(key) ||
                                    (currentPath.includes('.auth.') && key !== 'auth') ||
                                    currentPath.startsWith('Token Vault.smarthost.');

                if (isSensitive) {
                    const allAliases = [...(this.vaultAppAliases || []), ...(this.vaultUserAliases || [])];

                    const oldIsAlias = typeof val1 === 'string' && allAliases.includes(val1);
                    const newIsAlias = typeof val2 === 'string' && allAliases.includes(val2);

                    displayOld = (val1 && val1 !== '') ? (oldIsAlias ? `[Alias] ${val1}` : '••••••••') : 'None';
                    displayNew = (val2 && val2 !== '') ? (newIsAlias ? `[Alias] ${val2}` : '••••••••') : 'None';
                }

                diffs.push({
                    key: currentPath,
                    humanLabel: humanKey,
                    old: typeof displayOld === 'string' && !displayOld.startsWith('[') ? JSON.stringify(displayOld).replace(/^"|"$/g, '') : displayOld,
                    new: typeof displayNew === 'string' && !displayNew.startsWith('[') ? JSON.stringify(displayNew).replace(/^"|"$/g, '') : displayNew,
                    originalValue: (typeof val1 === 'object' && val1 !== null) ? JSON.parse(JSON.stringify(val1)) : val1
                });
            }
        }
    }
    return diffs;
},

preparePayload() {
    const payload = {
        smtp: JSON.parse(JSON.stringify(this.smtp)),
        pushover: { ...this.pushGlobals },
        smarthost: {
            globals: { ...this.smartGlobals },
            aliases: JSON.parse(JSON.stringify(this.smarthosts))
        },
        routes: {}
    };

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
    if (val === null || val === undefined) return '-';
    if (typeof val === 'boolean') return val ? 'True' : 'False';
    if (Array.isArray(val)) {
        return val.join('<br>');
    }

    let strVal = String(val);
    // Replace both literal newlines and escaped JSON newline characters with line breaks
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
    this.initialState = JSON.parse(JSON.stringify({
        ui: this.rawUiConfig,
        routes: { mappings: this.mappings },
        pushover: { pushGlobals: this.pushGlobals },
        smarthost: { smarthosts: this.smarthosts, smartGlobals: this.smartGlobals },
        server: { smtp: this.smtp, smtp_meta: this.smtp_meta },
        vault: { vaultApp: this.vaultApp, vaultUser: this.vaultUser, vaultSmarthost: this.vaultSmarthost, vaultAppAliases: this.vaultAppAliases, vaultUserAliases: this.vaultUserAliases }
    }));
},

requestSave(formId) {
    this.diffModal.targetForm = formId;
    this.diffModal.changes = [];

    const newConfig = JSON.parse(this.preparePayload());
    const newVault = JSON.parse(this.prepareVaultPayload());

    const newUi = this._buildUiStatePayload();

    if (formId === 'backend_form' || formId === 'ui_form') {
        const oldUi = { ...this.rawUiConfig }; delete oldUi.listeners;
        const newUiObj = { ...newUi }; delete newUiObj.listeners;
        this.diffModal.changes.push(...this._getDiffs(oldUi, newUiObj, 'UI/Backend Context'));

        const oldUiListeners = Object.fromEntries((this.rawUiConfig.listeners || []).map(x => [x.bind, x]));
        const newUiListeners = Object.fromEntries((newUi.listeners || []).map(x => [x.bind, x]));
        this.diffModal.changes.push(...this._getDiffs(oldUiListeners, newUiListeners, 'UI/Backend Context.listeners'));
    } else {
        if (this.tab === 'routes') {
            this.diffModal.changes.push(...this._getDiffs(this.rawConfig.routes || {}, newConfig.routes || {}, 'Gateway Config.routes'));
        } else if (this.tab === 'pushover') {
            this.diffModal.changes.push(...this._getDiffs(this.rawConfig.pushover || {}, newConfig.pushover || {}, 'Gateway Config.pushover'));

            const oldVaultApp = Object.fromEntries((this.rawVault.app || []).map(x => [x.name, x]));
            const newVaultApp = Object.fromEntries((newVault.app || []).map(x => [x.name, x]));
            this.diffModal.changes.push(...this._getDiffs(oldVaultApp, newVaultApp, 'Token Vault.app'));

            const oldVaultUser = Object.fromEntries((this.rawVault.user || []).map(x => [x.name, x]));
            const newVaultUser = Object.fromEntries((newVault.user || []).map(x => [x.name, x]));
            this.diffModal.changes.push(...this._getDiffs(oldVaultUser, newVaultUser, 'Token Vault.user'));

        } else if (this.tab === 'smarthost') {
            this.diffModal.changes.push(...this._getDiffs(this.rawConfig.smarthost || {}, newConfig.smarthost || {}, 'Gateway Config.smarthost'));
            this.diffModal.changes.push(...this._getDiffs(this.rawVault.smarthost || {}, newVault.smarthost || {}, 'Token Vault.smarthost'));
        } else if (this.tab === 'server') {
            const oldSmtp = { ...this.rawConfig.smtp }; delete oldSmtp.listeners;
            const newSmtp = { ...newConfig.smtp }; delete newSmtp.listeners;
            this.diffModal.changes.push(...this._getDiffs(oldSmtp, newSmtp, 'Gateway Config.smtp'));

            const oldSmtpListeners = Object.fromEntries((this.rawConfig.smtp?.listeners || []).map(x => [x.bind, x]));
            const newSmtpListeners = Object.fromEntries((newConfig.smtp?.listeners || []).map(x => [x.bind, x]));
            this.diffModal.changes.push(...this._getDiffs(oldSmtpListeners, newSmtpListeners, 'Gateway Config.smtp.listeners'));
        }
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
    const path = item.key;
    const val = item.originalValue;
    let isComplexReset = false;

    if (path.includes('smarthost.aliases') || path.includes('Token Vault.smarthost')) {
        let matches = path.match(/(?:aliases|smarthost)\.([^.]+)/i);
        if (matches && matches[1]) {
            const shAlias = matches[1];
            const shObj = JSON.parse(this.snapshots.smarthost);

            if (shObj.smarthosts[shAlias]) this.smarthosts[shAlias] = JSON.parse(JSON.stringify(shObj.smarthosts[shAlias]));
            else delete this.smarthosts[shAlias];

            if (shObj.vaultSmarthost[shAlias]) this.vaultSmarthost[shAlias] = JSON.parse(JSON.stringify(shObj.vaultSmarthost[shAlias]));
            else delete this.vaultSmarthost[shAlias];

            this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes(shAlias));
            isComplexReset = true;
        }
    } else if (path.includes('Vault.app')) {
        this.vaultApp = JSON.parse(JSON.stringify(JSON.parse(this.snapshots.pushover).vaultApp));
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('Vault.app'));
        isComplexReset = true;
    } else if (path.includes('Vault.user')) {
        this.vaultUser = JSON.parse(JSON.stringify(JSON.parse(this.snapshots.pushover).vaultUser));
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('Vault.user'));
        isComplexReset = true;
    } else if (path.includes('smtp.listeners')) {
        this.smtp.listeners = JSON.parse(JSON.stringify(JSON.parse(this.snapshots.server).listeners || []));
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('smtp.listeners'));
        isComplexReset = true;
    } else if (path.includes('routes')) {
        this.resetTab('routes');
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('routes'));
        isComplexReset = true;
    } else if (path.includes('UI/Backend Context.listeners')) {
        this.uiListeners = JSON.parse(JSON.stringify(JSON.parse(this.snapshots.ui).uiListeners || []));
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('UI/Backend Context.listeners'));
        isComplexReset = true;
    }

    if (!isComplexReset) {
        const key = path.split('.').pop();

        if (path.startsWith('UI/Backend Context.')) {
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
            else if (key === 'trust_proxy_cidrs') {
                this.ui_trust_proxy_cidrs = Array.isArray(val) ? JSON.parse(JSON.stringify(val)) : [];
            }
            else if (key === 'allowed_cidrs') {
                this.ui_allowed_cidrs = Array.isArray(val) ? JSON.parse(JSON.stringify(val)) : [];
                this.ui_allowed_cidrs_text = this.ui_allowed_cidrs.join('\n');
            }
        } else if (path.startsWith('Gateway Config.smtp.')) {
            this.smtp[key] = (typeof val === 'object' && val !== null) ? JSON.parse(JSON.stringify(val)) : val;
            if (key === 'allowed_cidrs') {
                this.smtp_cidrs_text = Array.isArray(val) ? val.join('\n') : '';
            }
        } else if (path.startsWith('Gateway Config.pushover.')) {
            if (key === 'attachments') this.pushGlobals.disable_attachments = (val === false);
            else this.pushGlobals[key] = val !== undefined ? val : '';
        } else if (path.startsWith('Gateway Config.smarthost.globals.')) {
            if (key === 'alias') this.smartGlobals.alias = val || '';
            if (key === 'force_plaintext') this.smartGlobals.force_plaintext = (val === true);
            if (key === 'disable_attachments') this.smartGlobals.disable_attachments = (val === true);
        }

        this.diffModal.changes.splice(idx, 1);
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
    const backup = JSON.parse(JSON.stringify(this.initialState));

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
        this.ui_trust_proxy_cidrs = JSON.parse(JSON.stringify(uiObj.trust_proxy_cidrs || []));
        this.uiTrustProxyCidrInput = '';
        this.uiTrustProxyCidrError = '';
        this.ui_vault_sort = uiObj.vault_sort || 'name_asc';
        this.ui_smtp_sort = uiObj.smtp_sort || 'name_asc';
        this.ui_smarthost_sort = uiObj.smarthost_sort || 'alias_asc';
        this.uiListeners = JSON.parse(JSON.stringify(uiObj.listeners || []));
        this.tzError = false;
        this.ui_allowed_cidrs = JSON.parse(JSON.stringify(uiObj.allowed_cidrs || []));
        this.ui_allowed_cidrs_text = this.ui_allowed_cidrs.join('\n');
    }

    if (tabContext === 'pushover') {
        this.pushGlobals = JSON.parse(JSON.stringify(backup.pushover.pushGlobals));
        this.vaultApp = JSON.parse(JSON.stringify(backup.vault.vaultApp));
        this.vaultUser = JSON.parse(JSON.stringify(backup.vault.vaultUser));
        this.vaultAppAliases = this.vaultApp.map(x => x.name);
        this.vaultUserAliases = this.vaultUser.map(x => x.name);
    }

    if (tabContext === 'routes') {
        this.mappings = JSON.parse(JSON.stringify(backup.routes.mappings));
    }

    if (tabContext === 'smarthost') {
        this.smarthosts = JSON.parse(JSON.stringify(backup.smarthost.smarthosts));
        this.smartGlobals = JSON.parse(JSON.stringify(backup.smarthost.smartGlobals));
        this.vaultSmarthost = JSON.parse(JSON.stringify(backup.vault.vaultSmarthost));
    }

    if (tabContext === 'server') {
        this.smtp = JSON.parse(JSON.stringify(backup.server.smtp));
        this.smtp_meta = JSON.parse(JSON.stringify(backup.server.smtp_meta));
        this.smtp_cidrs_text = (this.smtp.allowed_cidrs || []).join('\n');
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
