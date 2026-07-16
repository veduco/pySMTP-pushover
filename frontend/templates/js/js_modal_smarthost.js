openSmarthostModal(mode, alias = '') {
    this.smarthostModal.error = '';
    this.smarthostModal.showPass = false;

    if (mode === 'add') {
        this.smarthostModal.mode = 'add';
        this.smarthostModal.oldAlias = '';
        this.smarthostModal.alias = '';
        this.smarthostModal.hostname = '';
        this.smarthostModal.advertised_hostname = '';
        this.smarthostModal.port = 25;
        this.smarthostModal.starttls = false;
        this.smarthostModal.disable_tls_validation = false;
        this.smarthostModal.auth = false;
        this.smarthostModal.username = '';
        this.smarthostModal.password = '';
        this.smarthostModal.disable_attachments = false;
        this.smarthostModal.force_plaintext = false;
    } else {
        this.smarthostModal.mode = 'edit';
        this.smarthostModal.oldAlias = alias;
        this.smarthostModal.alias = alias;

        const sh = this.smarthosts[alias] || {};
        this.smarthostModal.hostname = sh.hostname || '';
        this.smarthostModal.advertised_hostname = sh.advertised_hostname || '';
        this.smarthostModal.port = sh.port || 25;
        this.smarthostModal.starttls = sh.starttls === true;
        this.smarthostModal.disable_tls_validation = sh.disable_tls_validation === true;
        this.smarthostModal.auth = sh.auth === true;
        this.smarthostModal.username = sh.username || '';

        // Blanked out to protect secrets. Backend will interpret empty string as "Retain original".
        this.smarthostModal.password = '';

        this.smarthostModal.disable_attachments = sh.disable_attachments === true;
        this.smarthostModal.force_plaintext = sh.force_plaintext === true;
    }

    this.smarthostModal.orig = this.clone(this.smarthostModal);
    this.smarthostModal.open = true;
},

clearSmarthostModal() {
    const orig = this.smarthostModal.orig;
    this.smarthostModal.alias = orig.alias;
    this.smarthostModal.hostname = orig.hostname;
    this.smarthostModal.advertised_hostname = orig.advertised_hostname;
    this.smarthostModal.port = orig.port;
    this.smarthostModal.starttls = orig.starttls;
    this.smarthostModal.disable_tls_validation = orig.disable_tls_validation;
    this.smarthostModal.auth = orig.auth;
    this.smarthostModal.username = orig.username;
    this.smarthostModal.password = orig.password;
    this.smarthostModal.disable_attachments = orig.disable_attachments;
    this.smarthostModal.force_plaintext = orig.force_plaintext;
    this.smarthostModal.error = '';
},

saveSmarthostModal() {
    this.smarthostModal.error = '';
    const alias = this.smarthostModal.alias.trim();

    if (!alias) {
        this.smarthostModal.error = 'Alias name is required.';
        return;
    }

    if (this.smarthostModal.mode === 'add' && this.smarthosts[alias]) {
        this.smarthostModal.error = 'Alias name already exists.';
        return;
    }

    const shObj = {
        hostname: this.smarthostModal.hostname.trim(),
        port: parseInt(this.smarthostModal.port) || 25,
        starttls: this.smarthostModal.starttls
    };

    if (this.smarthostModal.advertised_hostname.trim()) shObj.advertised_hostname = this.smarthostModal.advertised_hostname.trim();
    if (this.smarthostModal.starttls && this.smarthostModal.disable_tls_validation) shObj.disable_tls_validation = true;
    if (this.smarthostModal.disable_attachments) shObj.disable_attachments = true;
    if (this.smarthostModal.force_plaintext) shObj.force_plaintext = true;

    if (this.smarthostModal.auth) {
        shObj.auth = true;
        shObj.username = this.smarthostModal.username.trim();
    }

    this.smarthosts[alias] = shObj;

    if (this.smarthostModal.auth && this.smarthostModal.password) {
        if (!this.vaultSmarthost[alias]) this.vaultSmarthost[alias] = { epoch: Math.floor(Date.now() / 1000) };
        this.vaultSmarthost[alias].token = this.smarthostModal.password;
    } else if (!this.smarthostModal.auth && this.vaultSmarthost[alias]) {
        delete this.vaultSmarthost[alias];
    }

    this.smarthostModal.open = false;
},

get hasSmarthostModalChanges() {
    const o = this.smarthostModal.orig;
    const c = this.smarthostModal;
    if (!o) return false;
    return o.alias !== c.alias ||
           o.hostname !== c.hostname ||
           o.advertised_hostname !== c.advertised_hostname ||
           o.port !== c.port ||
           o.starttls !== c.starttls ||
           o.disable_tls_validation !== c.disable_tls_validation ||
           o.auth !== c.auth ||
           o.username !== c.username ||
           o.password !== c.password ||
           o.disable_attachments !== c.disable_attachments ||
           o.force_plaintext !== c.force_plaintext;
},

// Implements strict validation constraints before turning the Save button active
get canSaveSmarthostModal() {
    if (!this.smarthostModal.alias.trim()) return false;
    if (!this.smarthostModal.hostname.trim()) return false;

    if (this.smarthostModal.auth) {
        if (!this.smarthostModal.username.trim()) return false;

        if (this.smarthostModal.mode === 'add') {
            if (!this.smarthostModal.password) return false;
        } else {
            // Evaluates directly against Vault tokens to determine if a required credential is missing on edit mode
            const existingVault = this.vaultSmarthost[this.smarthostModal.oldAlias];
            const hasExistingPassword = existingVault && existingVault.token;

            if (!hasExistingPassword && !this.smarthostModal.password) return false;
        }
    }

    if (!this.hasSmarthostModalChanges && this.smarthostModal.mode === 'edit') return false;
    return true;
},

deleteSmarthost(alias) {
    let isAssigned = false;

    if (this.smtp.default_route === 'smarthost' && this.smartGlobals.alias === alias) {
        isAssigned = true;
    }

    for (let m of this.mappings) {
        if (m.method === 'smarthost' && m.smarthost_alias === alias) {
            isAssigned = true;
            break;
        }
    }

    if (isAssigned) {
        this.alertModal.title = 'Smarthost In Use';
        this.alertModal.message = `The Smarthost alias "${alias}" is currently assigned to a route or the global default fallback. Please reassign those items before deleting this relay.`;
        this.alertModal.open = true;
        return;
    }

    delete this.smarthosts[alias];
    if (this.vaultSmarthost[alias]) {
        delete this.vaultSmarthost[alias];
    }
},
