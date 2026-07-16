saveVaultModal() {
    this.vaultModal.error = '';
    const name = this.vaultModal.name.trim();
    const token = this.vaultModal.token.trim();

    if (!name || !token) {
        this.vaultModal.error = 'Both Alias Name and Token are required.';
        return;
    }

    const targetArray = this.vaultModal.type === 'app' ? this.vaultApp : this.vaultUser;
    const aliasesArray = this.vaultModal.type === 'app' ? this.vaultAppAliases : this.vaultUserAliases;

    if (aliasesArray.includes(name)) {
        this.vaultModal.error = 'An alias with this name already exists.';
        return;
    }

    targetArray.push({
        name: name,
        token: token,
        epoch: Math.floor(Date.now() / 1000)
    });
    aliasesArray.push(name);

    this.vaultModal.open = false;
},

clearVaultModal() {
    this.vaultModal.name = '';
    this.vaultModal.token = '';
    this.vaultModal.error = '';
},

get hasVaultModalChanges() {
    return this.vaultModal.name.trim() !== '' || this.vaultModal.token.trim() !== '';
},

get canSaveVaultModal() {
    return this.vaultModal.name.trim() !== '' && this.vaultModal.token.trim() !== '';
},

deleteVaultToken(type, name) {
    let isAssigned = false;

    // Validates against active Pushover route configurations and fallbacks
    if (type === 'app') {
        if (this.pushGlobals._isTokenAlias && this.pushGlobals.token === name) isAssigned = true;
        for (let m of this.mappings) {
            if (m.method === 'pushover' && m._isTokenAlias && m.token === name) isAssigned = true;
        }
    } else if (type === 'user') {
        if (this.pushGlobals._isUserAlias && this.pushGlobals.user === name) isAssigned = true;
        for (let m of this.mappings) {
            if (m.method === 'pushover' && m._isUserAlias && m.user === name) isAssigned = true;
        }
    }

    if (isAssigned) {
        // Triggers the modern standardized modal instead of the clunky browser confirm()
        this.alertModal.title = 'Token In Use';
        this.alertModal.message = `The ${type === 'app' ? 'App Token' : 'User Key'} "${name}" is currently assigned to a route or global fallback. Please reassign those items before deleting this alias.`;
        this.alertModal.open = true;
        return;
    }

    if (type === 'app') {
        this.vaultApp = this.vaultApp.filter(v => v.name !== name);
        this.vaultAppAliases = this.vaultApp.map(v => v.name);
    } else {
        this.vaultUser = this.vaultUser.filter(v => v.name !== name);
        this.vaultUserAliases = this.vaultUser.map(v => v.name);
    }
},
