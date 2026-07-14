loadQueue() {
    fetch('/api/queue').then(r => r.json()).then(d => this.queueItems = d);
},
deleteQueueItem(id) {
    fetch('/api/queue/' + id, {method: 'DELETE'}).then(() => this.loadQueue());
},
retryQueueItem(id) {
    fetch('/api/queue/' + id + '/retry', {method: 'POST'}).then(() => this.loadQueue());
},
preparePayload() {
    const finalPushover = { ...this.pushGlobals }; finalPushover.attachments = !this.pushGlobals.disable_attachments; delete finalPushover.disable_attachments; delete finalPushover._isTokenAlias; delete finalPushover._isUserAlias; delete finalPushover._showToken; delete finalPushover._showUser; delete finalPushover._tokenRaw; delete finalPushover._tokenAliasVal; delete finalPushover._userRaw; delete finalPushover._userAliasVal;
    ['priority', 'retry', 'expire', 'ttl'].forEach(p => { if (finalPushover[p] === '' || finalPushover[p] === null || finalPushover[p] === undefined) delete finalPushover[p]; else finalPushover[p] = parseInt(finalPushover[p], 10); });
    ['device', 'url', 'url_title', 'sound', 'tags', 'user'].forEach(p => { if (finalPushover[p] === '') delete finalPushover[p]; });

    const finalRoutes = {};
    this.mappings.forEach(m => {
        if(m._key && m._key.trim() !== '') {
            let k = m._key.trim(); if (m._isRegex && !k.toLowerCase().startsWith('regex:')) { k = 'regex:' + k; }
            if (m.method === 'pushover') {
                const { _key, _showAdv, _uid, _isTokenAlias, _isUserAlias, _isRegex, _showToken, _showUser, _tokenRaw, _tokenAliasVal, _userRaw, _userAliasVal, smarthost_alias, disable_attachments, ...rest } = m; rest.attachments = !disable_attachments;
                ['priority', 'retry', 'expire', 'ttl'].forEach(p => { if (rest[p] === '' || rest[p] === null || rest[p] === undefined) delete rest[p]; else rest[p] = parseInt(rest[p], 10); });
                ['device', 'url', 'url_title', 'sound', 'tags', 'user'].forEach(p => { if (rest[p] === '') delete rest[p]; }); finalRoutes[k] = rest;
            } else {
                finalRoutes[k] = { match: m.match, method: 'smarthost', smarthost_alias: m.smarthost_alias, force_plaintext: m.force_plaintext, disable_attachments: m.disable_attachments };
            }
        }
    });

    const finalSmarthost = { globals: { alias: this.smartGlobals.alias, force_plaintext: this.smartGlobals.force_plaintext, disable_attachments: this.smartGlobals.disable_attachments }, aliases: this.smarthosts };
    return JSON.stringify({ pushover: finalPushover, smtp: this.smtp, routes: finalRoutes, smarthost: finalSmarthost, _smtp_meta: this.smtp_meta });
},
prepareVaultPayload() {
    const shVault = {};
    for(const k of Object.keys(this.vaultSmarthost)) {
        shVault[k] = this.vaultSmarthost[k].token;
    }
    return JSON.stringify({ app: this.vaultApp, user: this.vaultUser, smarthost: shVault });
},
