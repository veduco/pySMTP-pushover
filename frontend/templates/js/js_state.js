theme: localStorage.getItem('theme') || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'),
tab: localStorage.getItem('activeTab') || 'routes',
mobileMenuOpen: false,

configOk: {{ 'true' if config_ok else 'false' }},
ui_backend_remote: {{ 'true' if backend_mode == 'remote' else 'false' }},
ui_trust_proxy: ({{ ui_config_json | safe }}.trust_proxy === true),

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
dragHandleIdx: null,

defaultTestPayload: {
    from: '', to: '', type: 'multipart',
    message_plain: 'Test message from SMTP Gateway',
    message_html: '<html><body><p>Test message from SMTP Gateway</p></body></html>',
    attachments: []
},

testPayload: {
    status: '', isError: false, loading: false
},

validTimezones: [],

errors: {
    tz: '',
    uiCidr: '',
    smtpCidr: '',
    dedupeWindow: '',
    uiTrustProxyCidr: ''
},

rawConfig: {{ config_json | safe }},
rawVault: {},
rawUiConfig: {{ ui_config_json | safe }},

queueItems: [],

smtp: { listeners: [], default_route: 'pushover', loglevel: 'INFO', hostname: '', queue_dir: '', tls_cert_file: '', tls_key_file: '', disable_persistence: false, auth: {}, allowed_cidrs: [], dedupe_enabled: false, dedupe_window: '10m', dedupe_keys: ['sender', 'match_reason', 'message'] },
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

smtpCidrInput: '',

ui_trust_proxy_cidrs: ({{ ui_config_json | safe }}.trust_proxy_cidrs || []),
uiTrustProxyCidrInput: '',

ui_tz: ({{ ui_config_json | safe }}.timezone || 'UTC'),
ui_fmt: ({{ ui_config_json | safe }}.date_format || 'YYYY-MM-DD HH:mm:ss'),
ui_relative: ({{ ui_config_json | safe }}.relative_time === true),
ui_expand_adv: ({{ ui_config_json | safe }}.expand_adv === true),
ui_loglevel: ({{ ui_config_json | safe }}.ui_loglevel || 'INFO'),
ui_vault_sort: ({{ ui_config_json | safe }}.vault_sort || 'name_asc'),
ui_smtp_sort: ({{ ui_config_json | safe }}.smtp_sort || 'name_asc'),
ui_smarthost_sort: ({{ ui_config_json | safe }}.smarthost_sort || 'alias_asc'),

vaultSortCol: 'name', vaultSortDir: 1,
smtpSortCol: 'name', smtpSortDir: 1,
smarthostSortCol: 'alias', smarthostSortDir: 1,

smtpListenerSortCol: 'bind', smtpListenerSortDir: 1,
uiListenerSortCol: 'bind', uiListenerSortDir: 1,

diffModal: { open: false, changes: [], targetForm: '' },
alertModal: { open: false, title: '', message: '' },

// Bootstrapped Polymorphic Modal Component Engine Bindings
modals: {
    vault: new GatewayModal(schemaSource, '', { type: 'app', name: '', token: '' }),
    smtpUser: new GatewayModal(schemaSource, '', { name: '', password: '' }),
    edit: new GatewayModal(schemaSource, '', { type: '', subType: '', name: '', value: '' }),
    listener: new GatewayModal(schemaSource, 'gateway_config.smtp.listeners', { idx: null, ip: '0.0.0.0', port: 25 }),
    uiListener: new GatewayModal(schemaSource, 'ui_config.listeners', { idx: null, ip: '0.0.0.0', port: 8443 }),
    smarthost: new GatewayModal(schemaSource, 'gateway_config.smarthost.aliases', { oldAlias: '', alias: '', auth: false, username: '', password: '' }),
    link: new GatewayModal(schemaSource, '', { backend_remote: false, local_config_path: '', remote_url: '', remote_secret: '', remote_verify_tls: false })
},
