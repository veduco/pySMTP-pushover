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
