let statusTimer;
document.addEventListener('htmx:afterSwap', (e) => {
    if(e.detail.target.id === 'status' && e.detail.target.innerHTML) {
        clearTimeout(statusTimer);
        statusTimer = setTimeout(() => { e.detail.target.innerHTML = ''; }, 5000);
    }
});

document.addEventListener('alpine:init', () => {
    Alpine.data('gatewaySettings', () => ({

        {% include "js_state.js" %}
        {% include "js_computed.js" %}
        {% include "js_utils.js" %}
        {% include "js_api.js" %}
        {% include "js_modals.js" %}

        init() {
            this.$watch('theme', val => { localStorage.setItem('theme', val); document.documentElement.setAttribute('data-theme', val); });
            this.$watch('tab', val => {
                localStorage.setItem('activeTab', val);
                if (val === 'queue') {
                    this.loadQueue();
                    this.queueInterval = setInterval(() => this.loadQueue(), 5000);
                } else if (this.queueInterval) {
                    clearInterval(this.queueInterval);
                }
            });

            // UI Legacy Migration
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

            document.documentElement.setAttribute('data-theme', this.theme);

            if (this.tab === 'queue') {
                this.loadQueue();
                this.queueInterval = setInterval(() => this.loadQueue(), 5000);
            }

            const vsParts = this.ui_vault_sort.split('_');
            this.vaultSortCol = vsParts[0]; this.vaultSortDir = vsParts[1] === 'desc' ? -1 : 1;

            const ssParts = this.ui_smtp_sort.split('_');
            this.smtpSortCol = ssParts[0]; this.smtpSortDir = ssParts[1] === 'desc' ? -1 : 1;

            const shParts = this.ui_smarthost_sort.split('_');
            this.smarthostSortCol = shParts[0]; this.smarthostSortDir = shParts[1] === 'desc' ? -1 : 1;

            for(const [k, v] of Object.entries(this.vaultMeta.app || {})) { this.vaultApp.push({ name: k, epoch: v, token: '__RETAIN__' }); this.vaultAppAliases.push(k); }
            for(const [k, v] of Object.entries(this.vaultMeta.user || {})) { this.vaultUser.push({ name: k, epoch: v, token: '__RETAIN__' }); this.vaultUserAliases.push(k); }
            for(const [k, v] of Object.entries(this.vaultMeta.smarthost || {})) { this.vaultSmarthost[k] = { epoch: v, token: '__RETAIN__' }; }

            const gKeys = ['user','token','device','sound','url','url_title','tags','priority','ttl','retry','expire','attachments','force_plaintext'];
            const po = this.rawConfig.pushover || {};

            this.pushGlobals._showToken = false;
            this.pushGlobals._showUser = false;

            this.smarthosts = this.rawConfig.smarthost?.aliases || {};
            const sg = this.rawConfig.smarthost?.globals || {};
            this.smartGlobals = { alias: sg.alias || '', force_plaintext: sg.force_plaintext === true, disable_attachments: sg.disable_attachments === true };

            const routes = this.rawConfig.routes || {};

            for(const [k, v] of Object.entries(routes)) {
                let isRegex = false; let displayKey = k;
                if (k.toLowerCase().startsWith('regex:')) { isRegex = true; displayKey = k.substring(6); }

                const method = v.method || 'pushover';

                if (method === 'pushover') {
                    const isTokenAlias = this.vaultAppAliases.includes(v.token);
                    const isUserAlias = this.vaultUserAliases.includes(v.user);
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
            if(!this.smtp.listeners) this.smtp.listeners = [];
            if(!this.smtp.auth) this.smtp.auth = {};
            if(!this.smtp.default_route) this.smtp.default_route = 'pushover';
            if(this.smtp.disable_persistence === undefined) this.smtp.disable_persistence = false;
        }
    }));
});
