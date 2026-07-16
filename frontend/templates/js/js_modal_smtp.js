openSmtpUserModal() {
    this.smtpUserModal.name = ''; this.smtpUserModal.password = '';
    this.smtpUserModal.showToken = false; this.smtpUserModal.error = '';
    this.smtpUserModal.orig = { name: '', password: '' };
    this.smtpUserModal.open = true;
},
saveSmtpUserModal() {
    const u = this.smtpUserModal.name.trim(); const p = this.smtpUserModal.password.trim();
    if(!u || !p) { this.smtpUserModal.error = "Username and Password are required."; return; }
    this.smtp.auth[u] = "RAW:" + p;
    this.smtp_meta[u] = Math.floor(Date.now() / 1000);
    this.smtpUserModal.open = false;
},
clearSmtpUserModal() {
    this.smtpUserModal.name = this.smtpUserModal.orig.name;
    this.smtpUserModal.password = this.smtpUserModal.orig.password;
},
openEditModal(type, name, subType='') {
    this.editModal.type = type; this.editModal.subType = subType; this.editModal.name = name;
    this.editModal.value = ''; this.editModal.showToken = false;
    this.editModal.orig = { value: '' };
    this.editModal.open = true;
},
saveEditModal() {
    if(!this.editModal.value) return;
    const v = this.editModal.value.trim();
    if(!v) return;
    if(this.editModal.type === 'smtp') { this.smtp.auth[this.editModal.name] = "RAW:" + v; this.smtp_meta[this.editModal.name] = Math.floor(Date.now() / 1000); }
    else if(this.editModal.type === 'vault') {
        const target = this.editModal.subType === 'app' ? this.vaultApp : this.vaultUser;
        const idx = target.findIndex(x => x.name === this.editModal.name);
        if(idx !== -1) { target[idx].token = v; target[idx].epoch = Math.floor(Date.now() / 1000); }
    }
    this.editModal.open = false;
},
clearEditModal() {
    this.editModal.value = this.editModal.orig.value;
},

get hasSmtpUserModalChanges() { return this.smtpUserModal.name !== this.smtpUserModal.orig.name || this.smtpUserModal.password !== this.smtpUserModal.orig.password; },
get canSaveSmtpUserModal() { return this.hasSmtpUserModalChanges && this.smtpUserModal.name.trim() !== '' && this.smtpUserModal.password.trim() !== ''; },
get hasEditModalChanges() { return this.editModal.value !== this.editModal.orig.value; },
get canSaveEditModal() { return this.hasEditModalChanges && this.editModal.value.trim() !== ''; },

deleteSmtpUser(username) {
    if (this.smtp.auth && this.smtp.auth[username] !== undefined) {
        delete this.smtp.auth[username];
        if (this.smtp_meta && this.smtp_meta[username] !== undefined) {
            delete this.smtp_meta[username];
        }
        // Force Alpine to re-evaluate properties by re-assigning references
        this.smtp.auth = { ...this.smtp.auth };
        this.smtp_meta = { ...this.smtp_meta };
    }
},
