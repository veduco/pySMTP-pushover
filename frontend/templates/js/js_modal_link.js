openLinkEditModal() {
    this.linkEditModal.backend_remote = this.ui_backend_remote;
    this.linkEditModal.local_config_path = this.ui_local_config_path;
    this.linkEditModal.remote_url = this.ui_remote_url;
    this.linkEditModal.remote_secret = '';
    this.linkEditModal.remote_verify_tls = this.ui_remote_verify_tls;
    this.linkEditModal.showSecret = false;
    this.linkEditModal.orig = {
        backend_remote: this.ui_backend_remote, local_config_path: this.ui_local_config_path,
        remote_url: this.ui_remote_url, remote_secret: '', remote_verify_tls: this.ui_remote_verify_tls
    };
    this.linkEditModal.open = true;
},
saveLinkEditModal() {
    this.ui_backend_remote = this.linkEditModal.backend_remote;
    this.ui_local_config_path = this.linkEditModal.local_config_path.trim();
    this.ui_remote_url = this.linkEditModal.remote_url.trim();
    const new_sec = this.linkEditModal.remote_secret.trim();
    if (new_sec) this.ui_remote_secret = new_sec;
    this.ui_remote_verify_tls = this.linkEditModal.remote_verify_tls;
    this.linkEditModal.open = false;
},
clearLinkEditModal() {
    const o = this.linkEditModal.orig;
    this.linkEditModal.backend_remote = o.backend_remote;
    this.linkEditModal.local_config_path = o.local_config_path;
    this.linkEditModal.remote_url = o.remote_url;
    this.linkEditModal.remote_secret = '';
    this.linkEditModal.remote_verify_tls = o.remote_verify_tls;
    this.linkEditModal.showSecret = false;
},
get hasLinkModalChanges() {
    const m = this.linkEditModal; const o = m.orig;
    return m.backend_remote !== o.backend_remote || m.local_config_path !== o.local_config_path || m.remote_url !== o.remote_url || m.remote_secret !== '' || m.remote_verify_tls !== o.remote_verify_tls;
},
get canSaveLinkModal() {
    if (!this.hasLinkModalChanges) return false;
    const m = this.linkEditModal;
    if (m.backend_remote) {
        if (!m.remote_url.trim()) return false;
        if (!m.remote_secret.trim() && (!this.ui_remote_secret || this.ui_remote_secret === '')) return false;
    } else { if (!m.local_config_path.trim()) return false; }
    return true;
},
