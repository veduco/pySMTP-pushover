setVaultSort(col) {
    if(this.vaultSortCol === col) { this.vaultSortDir = this.vaultSortDir === 1 ? -1 : 1; }
    else { this.vaultSortCol = col; this.vaultSortDir = 1; }
},
setSmtpSort(col) {
    if(this.smtpSortCol === col) { this.smtpSortDir = this.smtpSortDir === 1 ? -1 : 1; }
    else { this.smtpSortCol = col; this.smtpSortDir = 1; }
},
setSmarthostSort(col) {
    if(this.smarthostSortCol === col) { this.smarthostSortDir = this.smarthostSortDir === 1 ? -1 : 1; }
    else { this.smarthostSortCol = col; this.smarthostSortDir = 1; }
},
setListenerSort(col) {
    if(this.listenerSortCol === col) { this.listenerSortDir = this.listenerSortDir === 1 ? -1 : 1; }
    else { this.listenerSortCol = col; this.listenerSortDir = 1; }
},

get sortedVaultApp() {
    return [...this.vaultApp].sort((a, b) => {
        if(this.vaultSortCol === 'name') return a.name.localeCompare(b.name) * this.vaultSortDir;
        else return (a.epoch - b.epoch) * this.vaultSortDir;
    });
},
get sortedVaultUser() {
    return [...this.vaultUser].sort((a, b) => {
        if(this.vaultSortCol === 'name') return a.name.localeCompare(b.name) * this.vaultSortDir;
        else return (a.epoch - b.epoch) * this.vaultSortDir;
    });
},
get sortedSmtpAuth() {
    const arr = Object.keys(this.smtp.auth || {}).map(k => ({ name: k, epoch: this.smtp_meta[k] || 0 }));
    return arr.sort((a, b) => {
        if(this.smtpSortCol === 'name') return a.name.localeCompare(b.name) * this.smtpSortDir;
        else return (a.epoch - b.epoch) * this.smtpSortDir;
    });
},
get sortedSmarthosts() {
    const arr = Object.keys(this.smarthosts).map(k => ({ alias: k, ...this.smarthosts[k] }));
    return arr.sort((a, b) => {
        let res = 0;
        if (this.smarthostSortCol === 'alias') res = a.alias.localeCompare(b.alias);
        else if (this.smarthostSortCol === 'address') {
            const aAddr = (a.hostname || '') + ':' + (a.port || 25);
            const bAddr = (b.hostname || '') + ':' + (b.port || 25);
            res = aAddr.localeCompare(bAddr);
        }
        else if (this.smarthostSortCol === 'starttls') res = (a.starttls === b.starttls) ? 0 : a.starttls ? 1 : -1;
        else if (this.smarthostSortCol === 'auth') res = (a.auth === b.auth) ? 0 : a.auth ? 1 : -1;
        else if (this.smarthostSortCol === 'username') res = (a.username || '').localeCompare(b.username || '');
        else if (this.smarthostSortCol === 'disable_attachments') res = (a.disable_attachments === b.disable_attachments) ? 0 : a.disable_attachments ? 1 : -1;
        else if (this.smarthostSortCol === 'force_plaintext') res = (a.force_plaintext === b.force_plaintext) ? 0 : a.force_plaintext ? 1 : -1;
        return res * this.smarthostSortDir;
    });
},
get sortedSmarthostKeys() {
    return this.sortedSmarthosts.map(s => s.alias);
},
get sortedListeners() {
    const mapped = this.smtp.listeners.map((l, i) => ({ ...l, _idx: i }));
    return mapped.sort((a, b) => {
        let res = 0;
        if (this.listenerSortCol === 'bind') res = (a.bind || '').localeCompare(b.bind || '');
        else if (this.listenerSortCol === 'hostname') res = (a.hostname || '').localeCompare(b.hostname || '');
        else if (this.listenerSortCol === 'starttls') res = (a.starttls === b.starttls) ? 0 : a.starttls ? 1 : -1;
        return res * this.listenerSortDir;
    });
},
