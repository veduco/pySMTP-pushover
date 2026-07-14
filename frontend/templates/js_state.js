theme: localStorage.getItem('theme') || 'dark',
tab: localStorage.getItem('activeTab') || 'routes',
rawConfig: {{ config_json | safe }},
rawUiConfig: {{ ui_config_json | safe }},
smtp_meta: {{ smtp_meta_json | safe }},
vaultMeta: {{ vault_meta_json | safe }},
ui_loglevel: '{{ ui_loglevel }}',
vaultApp: [], vaultUser: [], vaultSmarthost: {}, vaultAppAliases: [], vaultUserAliases: [],
newVaultType: 'app', newVaultName: '', newVaultToken: '', showNewVaultToken: false,

queueItems: [], queueInterval: null,

ui_tz: '{{ ui_tz }}', ui_fmt: '{{ ui_fmt }}',
ui_relative: {{ 'true' if ui_relative else 'false' }},
ui_expand_adv: {{ 'true' if ui_expand_adv else 'false' }},
ui_vault_sort: '{{ ui_vault_sort }}',
ui_smtp_sort: '{{ ui_smtp_sort }}',
ui_smarthost_sort: '{{ ui_smarthost_sort }}',
vaultSortCol: 'name', vaultSortDir: 1,
smtpSortCol: 'name', smtpSortDir: 1,

listenerSortCol: 'bind', listenerSortDir: 1,
smarthostSortCol: 'alias', smarthostSortDir: 1,

uiListeners: [], uiListenerSortCol: 'bind', uiListenerSortDir: 1,

pushGlobals: {}, smartGlobals: {}, showGlobalAdv: false, mappings: [], smtp: {}, smarthosts: {},
newSmtpUser: '', newSmtpPass: '',

dragHover: null, draggedRouteIdx: null,

editModal: { open: false, type: '', subType: '', name: '', value: '', showToken: false },
smarthostModal: { open: false, mode: 'add', oldAlias: '', alias: '', hostname: '', advertised_hostname: '', port: 25, starttls: false, disable_tls_validation: false, auth: false, username: '', password: '', showPass: false, disable_attachments: false, force_plaintext: false, error: '' },
listenerModal: { open: false, mode: 'add', idx: null, ip: '0.0.0.0', port: 25, hostname: '', starttls: false, tls_cert_file: '', tls_key_file: '', error: '' },
uiListenerModal: { open: false, mode: 'add', idx: null, ip: '0.0.0.0', port: 8443, https: true, tls_cert: '', tls_key: '', error: '' },
