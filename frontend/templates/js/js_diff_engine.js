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

takeSnapshot() {
    this.rawConfig = JSON.parse(this.preparePayload());
    this.rawVault = JSON.parse(this.prepareVaultPayload());
    this.rawUiConfig = {
        timezone: this.ui_tz, date_format: this.ui_fmt, relative_time: this.ui_relative,
        expand_adv: this.ui_expand_adv, trust_proxy: this.ui_trust_proxy,
        vault_sort: this.ui_vault_sort, smtp_sort: this.ui_smtp_sort, smarthost_sort: this.ui_smarthost_sort,
        ui_loglevel: this.ui_loglevel, listeners: JSON.parse(JSON.stringify(this.uiListeners)),
        backend_mode: this.ui_backend_remote ? 'remote' : 'local',
        local_config_path: this.ui_local_config_path, remote_url: this.ui_remote_url,
        remote_secret: this.ui_remote_secret, remote_verify_tls: this.ui_remote_verify_tls
    };

    this.snapshots = {
        routes: JSON.stringify(this.mappings.map(({_uid, _showToken, _showUser, _tokenAliasVal, _tokenRaw, _userAliasVal, _userRaw, ...rest}) => rest)),
        pushover: JSON.stringify({ pushGlobals: this.pushGlobals, vaultApp: this.vaultApp, vaultUser: this.vaultUser }),
        smarthost: JSON.stringify({ smarthosts: this.smarthosts, smartGlobals: this.smartGlobals, vaultSmarthost: this.vaultSmarthost }),
        server: JSON.stringify(this.smtp),
        backend: JSON.stringify({
            backend_remote: this.ui_backend_remote, local_config_path: this.ui_local_config_path,
            remote_url: this.ui_remote_url, remote_secret: this.ui_remote_secret, remote_verify_tls: this.ui_remote_verify_tls
        }),
        ui: JSON.stringify({
            ui_loglevel: this.ui_loglevel, ui_tz: this.ui_tz, ui_fmt: this.ui_fmt,
            ui_relative: this.ui_relative, ui_expand_adv: this.ui_expand_adv, ui_trust_proxy: this.ui_trust_proxy,
            ui_vault_sort: this.ui_vault_sort, ui_smtp_sort: this.ui_smtp_sort, ui_smarthost_sort: this.ui_smarthost_sort,
            uiListeners: this.uiListeners
        })
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
    const newUi = {
        timezone: this.ui_tz, date_format: this.ui_fmt, relative_time: this.ui_relative,
        expand_adv: this.ui_expand_adv, trust_proxy: this.ui_trust_proxy,
        vault_sort: this.ui_vault_sort, smtp_sort: this.ui_smtp_sort, smarthost_sort: this.ui_smarthost_sort,
        ui_loglevel: this.ui_loglevel, listeners: JSON.parse(JSON.stringify(this.uiListeners)),
        backend_mode: this.ui_backend_remote ? 'remote' : 'local',
        local_config_path: this.ui_local_config_path, remote_url: this.ui_remote_url,
        remote_secret: this.ui_remote_secret, remote_verify_tls: this.ui_remote_verify_tls
    };

    const getDiffs = (obj1, obj2, path = '') => {
        const diffs = [];
        const allKeys = new Set([...Object.keys(obj1 || {}), ...Object.keys(obj2 || {})]);
        for (const key of allKeys) {
            const val1 = obj1?.[key]; const val2 = obj2?.[key];
            const currentPath = path ? `${path}.${key}` : key;
            if (JSON.stringify(val1) !== JSON.stringify(val2)) {
                if (typeof val1 === 'object' && val1 !== null && typeof val2 === 'object' && val2 !== null) {
                    diffs.push(...getDiffs(val1, val2, currentPath));
                } else {
                    let humanKey = currentPath;
                    let m;

                    // Clean human-readable label generation using Regex to safely extract keys that contain dots
                    if ((m = currentPath.match(/^Gateway Config\.routes\.(.+?)(?:\.(?:match|method|disable_attachments|force_plaintext|token|user|device|sound|url|url_title|tags|priority|ttl|retry|expire|smarthost_alias))?$/))) {
                        humanKey = `Route Mapping Rule [${m[1]}]`;
                    } else if ((m = currentPath.match(/^Gateway Config\.smtp\.listeners\.(.+?)(?:\.(?:bind|hostname|starttls|tls_cert_file|tls_key_file))?$/))) {
                        humanKey = `SMTP Port Listener [${m[1]}]`;
                    } else if ((m = currentPath.match(/^UI\/Backend Context\.listeners\.(.+?)(?:\.(?:bind|https|tls_cert|tls_key))?$/))) {
                        humanKey = `UI Port Listener [${m[1]}]`;
                    } else if ((m = currentPath.match(/^Gateway Config\.smarthost\.aliases\.(.+?)(?:\.(?:hostname|advertised_hostname|port|starttls|disable_tls_validation|auth|username|disable_attachments|force_plaintext))?$/))) {
                        humanKey = `Smarthost Configuration [${m[1]}]`;
                    } else if ((m = currentPath.match(/^Token Vault\.app\.(.+?)(?:\.(?:token|epoch))?$/))) {
                        humanKey = `App Token Vault [${m[1]}]`;
                    } else if ((m = currentPath.match(/^Token Vault\.user\.(.+?)(?:\.(?:token|epoch))?$/))) {
                        humanKey = `User Key Vault [${m[1]}]`;
                    } else if ((m = currentPath.match(/^Token Vault\.smarthost\.(.+?)(?:\.(?:token|epoch))?$/))) {
                        humanKey = `Smarthost Vault Password [${m[1]}]`;
                    } else if (currentPath.startsWith('UI/Backend Context.')) {
                        humanKey = `UI Parameter -> ${currentPath.split('.')[1] || 'Unknown'}`;
                    } else if (currentPath.startsWith('Gateway Config.')) {
                        humanKey = `Gateway Parameter -> ${currentPath.split('.').pop()}`;
                    }

                    let displayOld = (val1 !== undefined && val1 !== '') ? val1 : 'None';
                    let displayNew = (val2 !== undefined && val2 !== '') ? val2 : 'None';

                    if (typeof displayOld === 'object' && displayOld !== null) displayOld = '[Active Configuration]';
                    if (typeof displayNew === 'object' && displayNew !== null) displayNew = '[Active Configuration]';
                    if (displayOld === '[Active Configuration]' && displayNew === 'None') displayNew = '[Deleted]';
                    if (displayOld === 'None' && displayNew === '[Active Configuration]') displayOld = '[Not Configured]';

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

                    let revertClosure = () => { this.resetTab(this.tab); };

                    if (currentPath.startsWith('UI/Backend Context.') && !currentPath.includes('.listeners.')) {
                        revertClosure = () => {
                            if (key === 'backend_mode') this.ui_backend_remote = (val1 === 'remote');
                            else if (key === 'local_config_path') this.ui_local_config_path = val1 || 'config.json';
                            else if (key === 'remote_url') this.ui_remote_url = val1 || '';
                            else if (key === 'remote_secret') this.ui_remote_secret = val1 || '';
                            else if (key === 'remote_verify_tls') this.ui_remote_verify_tls = (val1 === true);
                            else if (key === 'ui_loglevel') this.ui_loglevel = val1 || 'INFO';
                            else if (key === 'timezone') this.ui_tz = val1 || 'UTC';
                            else if (key === 'date_format') this.ui_fmt = val1 || 'YYYY-MM-DD HH:mm:ss';
                            else if (key === 'relative_time') this.ui_relative = (val1 === true);
                            else if (key === 'expand_adv') this.ui_expand_adv = (val1 === true);
                            else if (key === 'trust_proxy') this.ui_trust_proxy = (val1 === true);
                        };
                    } else if (currentPath.startsWith('Gateway Config.smtp.')) {
                        if (!currentPath.includes('listeners') && !currentPath.includes('auth')) {
                            revertClosure = () => { this.smtp[key] = val1; };
                        }
                    } else if (currentPath.startsWith('Gateway Config.pushover.')) {
                        let prop = currentPath.split('.').pop();
                        revertClosure = () => {
                            if (prop === 'attachments') this.pushGlobals.disable_attachments = (val1 === false);
                            else this.pushGlobals[prop] = val1 !== undefined ? val1 : '';
                        };
                    } else if (currentPath.startsWith('Gateway Config.smarthost.globals.')) {
                        revertClosure = () => {
                            if (key === 'alias') this.smartGlobals.alias = val1 || '';
                            if (key === 'force_plaintext') this.smartGlobals.force_plaintext = (val1 === true);
                            if (key === 'disable_attachments') this.smartGlobals.disable_attachments = (val1 === true);
                        };
                    }

                    diffs.push({
                        key: currentPath,
                        humanLabel: humanKey,
                        old: typeof displayOld === 'string' && !displayOld.startsWith('[') ? JSON.stringify(displayOld).replace(/^"|"$/g, '') : displayOld,
                        new: typeof displayNew === 'string' && !displayNew.startsWith('[') ? JSON.stringify(displayNew).replace(/^"|"$/g, '') : displayNew,
                        revert: revertClosure
                    });
                }
            }
        }
        return diffs;
    };

    if (formId === 'backend_form' || formId === 'ui_form') {
        const oldUi = { ...this.rawUiConfig }; delete oldUi.listeners;
        const newUiObj = { ...newUi }; delete newUiObj.listeners;
        this.diffModal.changes.push(...getDiffs(oldUi, newUiObj, 'UI/Backend Context'));

        const oldUiListeners = Object.fromEntries((this.rawUiConfig.listeners || []).map(x => [x.bind, x]));
        const newUiListeners = Object.fromEntries((newUi.listeners || []).map(x => [x.bind, x]));
        this.diffModal.changes.push(...getDiffs(oldUiListeners, newUiListeners, 'UI/Backend Context.listeners'));
    } else {
        if (this.tab === 'routes') {
            this.diffModal.changes.push(...getDiffs(this.rawConfig.routes || {}, newConfig.routes || {}, 'Gateway Config.routes'));
        } else if (this.tab === 'pushover') {
            this.diffModal.changes.push(...getDiffs(this.rawConfig.pushover || {}, newConfig.pushover || {}, 'Gateway Config.pushover'));

            const oldVaultApp = Object.fromEntries((this.rawVault.app || []).map(x => [x.name, x]));
            const newVaultApp = Object.fromEntries((newVault.app || []).map(x => [x.name, x]));
            this.diffModal.changes.push(...getDiffs(oldVaultApp, newVaultApp, 'Token Vault.app'));

            const oldVaultUser = Object.fromEntries((this.rawVault.user || []).map(x => [x.name, x]));
            const newVaultUser = Object.fromEntries((newVault.user || []).map(x => [x.name, x]));
            this.diffModal.changes.push(...getDiffs(oldVaultUser, newVaultUser, 'Token Vault.user'));

        } else if (this.tab === 'smarthost') {
            this.diffModal.changes.push(...getDiffs(this.rawConfig.smarthost || {}, newConfig.smarthost || {}, 'Gateway Config.smarthost'));
            this.diffModal.changes.push(...getDiffs(this.rawVault.smarthost || {}, newVault.smarthost || {}, 'Token Vault.smarthost'));
        } else if (this.tab === 'server') {
            const oldSmtp = { ...this.rawConfig.smtp }; delete oldSmtp.listeners;
            const newSmtp = { ...newConfig.smtp }; delete newSmtp.listeners;
            this.diffModal.changes.push(...getDiffs(oldSmtp, newSmtp, 'Gateway Config.smtp'));

            const oldSmtpListeners = Object.fromEntries((this.rawConfig.smtp?.listeners || []).map(x => [x.bind, x]));
            const newSmtpListeners = Object.fromEntries((newConfig.smtp?.listeners || []).map(x => [x.bind, x]));
            this.diffModal.changes.push(...getDiffs(oldSmtpListeners, newSmtpListeners, 'Gateway Config.smtp.listeners'));
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
    let complexResetTriggered = false;

    if (item.key.includes('smarthost') || item.key.includes('Smarthost')) {
        let matches = item.key.match(/(?:aliases|smarthost)\.([^.]+)/i);
        if (matches && matches[1]) {
            const shAlias = matches[1];
            const shObj = JSON.parse(this.snapshots.smarthost);

            if (shObj.smarthosts[shAlias]) this.smarthosts[shAlias] = JSON.parse(JSON.stringify(shObj.smarthosts[shAlias]));
            else delete this.smarthosts[shAlias];

            if (shObj.vaultSmarthost[shAlias]) this.vaultSmarthost[shAlias] = JSON.parse(JSON.stringify(shObj.vaultSmarthost[shAlias]));
            else delete this.vaultSmarthost[shAlias];

            this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes(shAlias));
            complexResetTriggered = true;
        }
    } else if (item.key.includes('Vault.app')) {
        this.vaultApp = JSON.parse(JSON.stringify(JSON.parse(this.snapshots.pushover).vaultApp));
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('Vault.app'));
        complexResetTriggered = true;
    } else if (item.key.includes('Vault.user')) {
        this.vaultUser = JSON.parse(JSON.stringify(JSON.parse(this.snapshots.pushover).vaultUser));
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('Vault.user'));
        complexResetTriggered = true;
    } else if (item.key.includes('smtp.listeners')) {
        this.smtp.listeners = JSON.parse(JSON.stringify(JSON.parse(this.snapshots.server).listeners || []));
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('smtp.listeners'));
        complexResetTriggered = true;
    } else if (item.key.includes('routes')) {
        this.resetTab('routes');
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('routes'));
        complexResetTriggered = true;
    } else if (item.key.includes('UI/Backend Context.listeners')) {
        // Safe reversion hook for the newly mapped UI listeners
        this.uiListeners = JSON.parse(JSON.stringify(JSON.parse(this.snapshots.ui).uiListeners || []));
        this.diffModal.changes = this.diffModal.changes.filter(c => !c.key.includes('UI/Backend Context.listeners'));
        complexResetTriggered = true;
    }

    if (!complexResetTriggered) {
        item.revert();
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
        this.ui_vault_sort = uiObj.vault_sort || 'name_asc';
        this.ui_smtp_sort = uiObj.smtp_sort || 'name_asc';
        this.ui_smarthost_sort = uiObj.smarthost_sort || 'alias_asc';
        this.uiListeners = JSON.parse(JSON.stringify(uiObj.listeners || []));
        this.tzError = false;
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
