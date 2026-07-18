theme: localStorage.getItem('theme') || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
tab: localStorage.getItem('activeTab') || 'routes',

configOk: {{ 'true' if config_ok else 'false' }},
ui_backend_remote: {{ 'true' if backend_mode == 'remote' else 'false' }},
ui_trust_proxy: {{ 'true' if ui_trust_proxy else 'false' }},

ui_local_config_path: '',
ui_remote_url: '',
ui_remote_secret: '',
ui_remote_verify_tls: false,
showRemoteSecret: false,
sseSource: null,

isReconnecting: false,
activeUiPort: {{ active_ui_port | default(0) }},

dragHover: null,
draggedRouteIdx: null,

defaultTestPayload: {
    from: '', to: '', type: 'multipart',
    message_plain: 'Test message from SMTP Gateway',
    message_html: '<html><body><p>Test message from SMTP Gateway</p></body></html>',
    attachments: []
},
testPayload: {
    status: '', isError: false, loading: false
},

linkEditModal: {
    open: false, backend_remote: false, showSecret: false,
    local_config_path: '', remote_url: '', remote_secret: '', remote_verify_tls: false,
    orig: {}
},

validTimezones: [],
tzError: false,
uiCidrError: '',
smtpCidrError: '',

rawConfig: {{ config_json | safe }},
rawVault: {},
rawUiConfig: {{ ui_config_json | safe }},

queueItems: [],

smtp: { listeners: [], default_route: 'pushover', loglevel: 'INFO', hostname: '', queue_dir: '', tls_cert_file: '', tls_key_file: '', disable_persistence: false, auth: {}, allowed_cidrs: [] },
smtp_meta: {{ smtp_meta_json | safe }},

vaultMeta: {{ vault_meta_json | safe }},
vaultApp: [], vaultUser: [], vaultSmarthost: {},
vaultAppAliases: [], vaultUserAliases: [],

mappings: [],
pushGlobals: {},
showGlobalAdv: false,

smarthosts: {},
smartGlobals: {},
uiListeners: [],

ui_allowed_cidrs: {{ ui_config_json | safe }}.allowed_cidrs || [],
uiCidrInput: '',
uiCidrError: '',

smtpCidrInput: '',
smtpCidrError: '',

ui_trust_proxy_cidrs: ({{ ui_config_json | safe }}.trust_proxy_cidrs || []),
uiTrustProxyCidrInput: '',
uiTrustProxyCidrError: '',

ui_tz: '{{ ui_tz }}', ui_fmt: '{{ ui_fmt }}',
ui_relative: {{ 'true' if ui_relative else 'false' }},
ui_expand_adv: {{ 'true' if ui_expand_adv else 'false' }},
ui_loglevel: '{{ ui_loglevel }}',
ui_vault_sort: '{{ ui_vault_sort }}',
ui_smtp_sort: '{{ ui_smtp_sort }}',
ui_smarthost_sort: '{{ ui_smarthost_sort }}',

vaultSortCol: 'name', vaultSortDir: 1,
smtpSortCol: 'name', smtpSortDir: 1,
smarthostSortCol: 'alias', smarthostSortDir: 1,

smtpListenerSortCol: 'bind', smtpListenerSortDir: 1,
uiListenerSortCol: 'bind', uiListenerSortDir: 1,

vaultModal: { open: false, type: 'app', name: '', token: '', showToken: false, error: '', orig: {} },
smtpUserModal: { open: false, name: '', password: '', showToken: false, error: '', orig: {} },
editModal: { open: false, type: '', subType: '', name: '', value: '', showToken: false, orig: {} },
listenerModal: { open: false, mode: 'add', idx: null, ip: '', port: 25, starttls: false, proxy_protocol: false, tls_cert_file: '', tls_key_file: '', hostname: '', error: '', orig: {} },
uiListenerModal: { open: false, mode: 'add', idx: null, ip: '', port: 8443, https: true, tls_cert: '', tls_key: '', error: '', orig: {} },
smarthostModal: { open: false, mode: 'add', oldAlias: '', alias: '', hostname: '', advertised_hostname: '', port: 25, starttls: false, disable_tls_validation: false, auth: false, username: '', password: '', disable_attachments: false, force_plaintext: false, showPass: false, error: '', orig: {} },

diffModal: { open: false, changes: [], targetForm: '' },
alertModal: { open: false, title: '', message: '' },
