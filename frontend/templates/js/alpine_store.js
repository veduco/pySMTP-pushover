const ALERT_TIMEOUT_MS = 5000;

let statusTimer;
document.addEventListener('htmx:afterSwap', (e) => {
    if(e.detail.target.id === 'status' && e.detail.target.innerHTML) {
        clearTimeout(statusTimer);
        statusTimer = setTimeout(() => { e.detail.target.innerHTML = ''; }, ALERT_TIMEOUT_MS);
        const component = Alpine.$data(document.querySelector('[x-data]'));
        if (component && component.takeSnapshot) component.takeSnapshot();
    }
});

// Centralized Store-Pattern Lifecycle Manager
const GatewayStore = {
    isDirty(tab, ctx) {
        if (!ctx.snapshots) return false;
        switch(tab) {
            case 'routes':
                return ctx.snapshots.routes !== JSON.stringify(ctx.mappings.map(({_showToken, _showUser, _showAdv, _tokenAliasVal, _tokenRaw, _userAliasVal, _userRaw, ...rest}) => rest));
            case 'pushover':
                return ctx.snapshots.pushover !== JSON.stringify({ pushGlobals: ctx.pushGlobals, vaultApp: ctx.vaultApp, vaultUser: ctx.vaultUser });
            case 'smarthost':
                return ctx.snapshots.smarthost !== JSON.stringify({ smarthosts: ctx.smarthosts, smartGlobals: ctx.smartGlobals, vaultSmarthost: ctx.vaultSmarthost });
            case 'server':
                return ctx.snapshots.server !== JSON.stringify(ctx.smtp);
            case 'backend':
                return ctx.snapshots.backend !== JSON.stringify({
                    backend_remote: ctx.ui_backend_remote,
                    local_config_path: ctx.ui_local_config_path,
                    primary_host: ctx.ui_primary_host,
                    remote_hosts: ctx.ui_remote_hosts
                });
            case 'ui':
                return ctx.snapshots.ui !== JSON.stringify(ctx._buildUiStatePayload());
            default:
                return false;
        }
    },

    isValid(tab, ctx) {
        // Enforce constraint mapping: Validation inherently checks against mutation changes
        if (!this.isDirty(tab, ctx)) return false;

        if (tab === 'routes') {
            for (let m of ctx.mappings) {
                if (!m._key || m._key.trim() === '') return false;
                if (m.method === 'pushover' && (!m.token || m.token.trim() === '')) return false;
                if (m.method === 'smarthost' && (!m.smarthost_alias || m.smarthost_alias.trim() === '')) return false;
            }
        } else if (tab === 'server') {
            if (ctx.errors.smtpCidr || ctx.errors.dedupeWindow || ctx.errors.floodWindow) return false;
            if (ctx.smtp.default_route === 'pushover') {
                if (!ctx.pushGlobals.token || !ctx.pushGlobals.user) return false;
            } else if (ctx.smtp.default_route === 'smarthost') {
                if (!ctx.smartGlobals.alias) return false;
            }
        } else if (tab === 'ui') {
            if (ctx.errors.tz || ctx.errors.uiCidr || ctx.errors.uiTrustProxyCidr) return false;

            // Strictly enforce OIDC requirements when the feature is toggled active
            if (ctx.ui_enable_oidc) {
                if (!ctx.ui_oidc_issuer_url || !ctx.ui_oidc_issuer_url.trim()) return false;
                if (!ctx.ui_oidc_client_id || !ctx.ui_oidc_client_id.trim()) return false;
                if (!ctx.ui_oidc_client_secret || !ctx.ui_oidc_client_secret.trim()) return false;
                if (!ctx.ui_oidc_cookie_secret || !ctx.ui_oidc_cookie_secret.trim()) return false;
            }
        }
        return true;
    }
};

document.addEventListener('alpine:init', () => {
    Alpine.data('gatewaySettings', () => ({

        GatewayStore,

        {% include "js_state.js" %}
        {% include "js_computed.js" %}
        {% include "js_utils.js" %}
        {% include "js_diff_engine.js" %}
        {% include "js_api.js" %}
        {% include "js_modal_eml.js" %}

        init() {
            this.testPayload = { ...this.defaultTestPayload, ...this.testPayload };

            // Initialize the OOP Modal Controllers
            this.modals = {
                vault: new VaultModal(this, schemaSource, '', { type: 'app', name: '', token: '' }),
                smtpUser: new SmtpUserModal(this, schemaSource, '', { name: '', password: '' }),
                edit: new EditModal(this, schemaSource, '', { type: '', subType: '', name: '', value: '' }),
                listener: new ListenerModal(this, 'smtp', schemaSource, 'gateway_config.smtp.listeners', { idx: null, ip: '0.0.0.0', port: 25 }),
                uiListener: new ListenerModal(this, 'ui', schemaSource, 'ui_config.listeners', { idx: null, ip: '0.0.0.0', port: 8443 }),
                smarthost: new SmarthostModal(this, schemaSource, 'gateway_config.smarthost.aliases', { oldAlias: '', alias: '', auth: false, username: '', password: '' }),
                host: new HostModal(this, schemaSource, '', { idx: null, alias: '', host: '', port: 6443, verify_tls: true }),
                secret: new SecretModal(this, schemaSource, '', { value: '' })
            };

            this.ui_local_config_path = this.rawUiConfig.local_config_path || 'config.json';
            this.ui_primary_host = this.rawUiConfig.primary_host || '';
            this.ui_remote_hosts = this.rawUiConfig.remote_hosts || [];
            this.ui_remote_secrets = this.rawUiConfig.remote_secrets || [];

            this.$watch('theme', val => { localStorage.setItem('theme', val); document.documentElement.setAttribute('data-theme', val); });

            this.$watch('tab', (newVal, oldVal) => {
                localStorage.setItem('activeTab', newVal);
                if (newVal === 'queue') this.connectStream();
                else if (this.sseSource) { this.sseSource.close(); this.sseSource = null; }
            });

            let ul = this.rawUiConfig.listeners;
            if(!ul || !Array.isArray(ul) || ul.length === 0) {
                ul = [{
                    bind: '0.0.0.0:' + (this.rawUiConfig.port || 8443),
                    https: this.rawUiConfig.https !== false,
                    tls_cert: this.rawUiConfig.tls_cert || '',
                    tls_key: this.rawUiConfig.tls_key || ''
                }];
            }
            this.uiListeners = ul;

            try { this.validTimezones = Intl.supportedValuesOf('timeZone'); }
            catch (e) { this.validTimezones = ['UTC', 'America/New_York', 'America/Chicago', 'Europe/London']; }

            document.documentElement.setAttribute('data-theme', this.theme);

            if (!this.configOk) {
                this.tab = 'backend';
            } else {
                if (this.tab === 'queue') this.connectStream();

                const vsParts = this.ui_vault_sort.split('_');
                this.vaultSortCol = vsParts[0]; this.vaultSortDir = vsParts[1] === 'desc' ? -1 : 1;

                const ssParts = this.ui_smtp_sort.split('_');
                this.smtpSortCol = ssParts[0]; this.smtpSortDir = ssParts[1] === 'desc' ? -1 : 1;

                const shParts = this.ui_smarthost_sort.split('_');
                this.smarthostSortCol = shParts[0]; this.smarthostSortDir = shParts[1] === 'desc' ? -1 : 1;

                for(const [k, v] of Object.entries(this.vaultMeta.app || {})) { this.vaultApp.push({ name: k, epoch: v, token: '' }); this.vaultAppAliases.push(k); }
                for(const [k, v] of Object.entries(this.vaultMeta.user || {})) { this.vaultUser.push({ name: k, epoch: v, token: '' }); this.vaultUserAliases.push(k); }
                for(const [k, v] of Object.entries(this.vaultMeta.smarthost || {})) { this.vaultSmarthost[k] = { epoch: v, token: '' }; }

                const gKeys = ['user','token','device','sound','url','url_title','tags','priority','ttl','retry','expire','attachments','force_plaintext'];
                const po = this.rawConfig.pushover || {};

                this.pushGlobals._showToken = false;
                this.pushGlobals._showUser = false;

                this.smarthosts = this.rawConfig.smarthost?.aliases || {};
                const sg = this.rawConfig.smarthost?.globals || {};
                this.smartGlobals = { alias: sg.alias || '', force_plaintext: sg.force_plaintext === true, disable_attachments: (sg.attachments === false) };

                const routes = this.rawConfig.routes || {};

                for(const [k, v] of Object.entries(routes)) {
                    let isRegex = false; let displayKey = k;
                    if (k.toLowerCase().startsWith('regex:')) { isRegex = true; displayKey = k.substring(6); }

                    const method = v.method || 'pushover';

                    if (method === 'pushover') {
                        const isTokenAlias = this.vaultAppAliases.includes(v.token);
                        const isUserAlias = this.vaultUserAliases.includes(v.user) || !v.user;

                        this.mappings.push({
                            _uid: Date.now().toString(36) + Math.random().toString(36).substr(2),
                            _key: displayKey,
                            match: v.match || 'to',
                            method: method,
                            _isRegex: isRegex,
                            _showAdv: this.ui_expand_adv,
                            _isTokenAlias: isTokenAlias,
                            _isUserAlias: isUserAlias,
                            _tokenAliasVal: isTokenAlias ? v.token : '',
                            _tokenRaw: !isTokenAlias ? v.token : '',
                            _userAliasVal: isUserAlias ? v.user : '',
                            _userRaw: !isUserAlias ? v.user : '',
                            _showToken: false,
                            _showUser: false,
                            disable_attachments: (v.attachments === false),
                            force_plaintext: (v.force_plaintext === true),
                            smarthost_alias: '',
                            ...v
                        });
                    } else {
                        this.mappings.push({
                            _uid: Date.now().toString(36) + Math.random().toString(36).substr(2),
                            _key: displayKey,
                            match: v.match || 'to',
                            method: method,
                            _isRegex: isRegex,
                            _showAdv: this.ui_expand_adv,
                            _isTokenAlias: false, _isUserAlias: false, _tokenAliasVal: '', _tokenRaw: '', _userAliasVal: '', _userRaw: '', _showToken: false, _showUser: false,
                            token: '', user: '',
                            smarthost_alias: v.smarthost_alias || '',
                            disable_attachments: (v.disable_attachments === true),
                            force_plaintext: (v.force_plaintext === true)
                        });
                    }
                }

                this.pushGlobals._isTokenAlias = this.vaultAppAliases.includes(po.token);
                this.pushGlobals._tokenAliasVal = this.pushGlobals._isTokenAlias ? po.token : '';
                this.pushGlobals._tokenRaw = !this.pushGlobals._isTokenAlias ? po.token : '';

                this.pushGlobals._isUserAlias = this.vaultUserAliases.includes(po.user);
                this.pushGlobals._userAliasVal = this.pushGlobals._isUserAlias ? po.user : '';
                this.pushGlobals._userRaw = !this.pushGlobals._isUserAlias ? po.user : '';

                for(const k of gKeys) {
                    if(k !== 'attachments' && k !== 'force_plaintext') this.pushGlobals[k] = po[k];
                }

                this.pushGlobals.disable_attachments = (po.attachments === false);
                this.pushGlobals.force_plaintext = (po.force_plaintext === true);

                this.smtp = this.rawConfig.smtp || {};

                // Dynamically inject any missing keys from the schema Source of Truth
                const smtpDefaults = schemaSource.gateway_config.smtp || {};
                for (const key in smtpDefaults) {
                    if (this.smtp[key] === undefined) {
                        this.smtp[key] = JSON.parse(JSON.stringify(smtpDefaults[key]));
                    }
                }

                // Ensure auth dictionary exists for legacy structural safety
                if (!this.smtp.auth) this.smtp.auth = {};
            }

            this.takeSnapshot();
        },

        connectStream() {
            if (this.sseSource) return;
            this.sseSource = new EventSource('/api/queue/stream');
            this.sseSource.onmessage = (e) => {
                const data = JSON.parse(e.data);
                if (data.action === 'init') {
                    this.queueItems = Object.values(data.state);
                } else if (data.action === 'add' || data.action === 'update') {
                    const idx = this.queueItems.findIndex(i => i.id === data.item.id);
                    if (idx >= 0) this.queueItems[idx] = data.item;
                    else this.queueItems.unshift(data.item);
                } else if (data.action === 'delete') {
                    this.queueItems = this.queueItems.filter(i => i.id !== data.item.id);
                } else if (data.action === 'CONFIG_RELOADED') {
                    window.location.reload();
                }
            };
        }
    }));
});
