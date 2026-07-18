getLogLevelColor(level) {
    switch(level) {
        case 'DEBUG': return '#c678dd';
        case 'INFO': return '#98c379';
        case 'WARNING': return '#e5c07b';
        case 'ERROR': return '#e06c75';
        case 'CRITICAL': return '#be5046';
        default: return 'var(--primary-color)';
    }
},

changeDefaultRoute(e) {
    const val = e.target.value;
    if (val === 'smarthost') {
        if (!this.smartGlobals.alias) {
            alert('You must define a Default Smarthost Alias before switching the global route.');
            e.target.value = 'pushover';
            this.smtp.default_route = 'pushover';
            return;
        }
    } else {
        if (!this.pushGlobals.token || !this.pushGlobals.user) {
            alert('You must define a Default App Token and Default User Key before switching to Pushover.');
            e.target.value = 'smarthost';
            this.smtp.default_route = 'smarthost';
            return;
        }
    }
    this.smtp.default_route = val;
},

formatTime(epoch) {
    if(!epoch) return "Never";
    const d = new Date(epoch * 1000);
    if(this.ui_relative) {
        const now = new Date();
        const isFuture = d > now;
        const seconds = Math.abs(Math.floor((now - d) / 1000));
        let interval = Math.floor(seconds / 31536000);
        if (interval >= 1) return isFuture ? "in " + interval + " years" : interval + " years ago";
        interval = Math.floor(seconds / 2592000);
        if (interval >= 1) return isFuture ? "in " + interval + " months" : interval + " months ago";
        interval = Math.floor(seconds / 84600);
        if (interval >= 1) return isFuture ? "in " + interval + " days" : interval + " days ago";
        interval = Math.floor(seconds / 3600);
        if (interval >= 1) return isFuture ? "in " + interval + " hours" : interval + " hours ago";
        interval = Math.floor(seconds / 60);
        if (interval >= 1) return isFuture ? "in " + interval + " minutes" : interval + " minutes ago";
        return isFuture ? "in a few seconds" : "Just now";
    }
    return this.executeAbsoluteFormat(d);
},

getFullTime(epoch) {
    if(!epoch) return "";
    return this.executeAbsoluteFormat(new Date(epoch * 1000));
},

executeAbsoluteFormat(d) {
    const pad = num => String(num).padStart(2, '0');
    const t_str = d.toLocaleString("en-US", { timeZone: this.ui_tz });
    const localD = new Date(t_str);
    const yyyy = localD.getFullYear();
    const mm = pad(localD.getMonth() + 1);
    const dd = pad(localD.getDate());
    let hh = localD.getHours();
    const min = pad(localD.getMinutes());
    const ss = pad(localD.getSeconds());
    const ampm = hh >= 12 ? 'PM' : 'AM';

    if (this.ui_fmt.includes("hh")) {
        hh = hh % 12;
        hh = hh ? hh : 12;
        hh = pad(hh);
        return `${mm}/${dd}/${yyyy} ${hh}:${min}:${ss} ${ampm}`;
    }
    if (this.ui_fmt.startsWith("DD")) {
        return `${dd}/${mm}/${yyyy} ${pad(hh)}:${min}:${ss}`;
    }
    return `${yyyy}-${mm}-${dd} ${pad(hh)}:${min}:${ss}`;
},

_genericSort(array, col, dir, customMap = {}) {
    if (!array || !Array.isArray(array)) return [];
    return [...array].sort((a, b) => {
        let valA = customMap[col] ? customMap[col](a) : a[col];
        let valB = customMap[col] ? customMap[col](b) : b[col];

        if (valA === undefined || valA === null) valA = '';
        if (valB === undefined || valB === null) valB = '';

        let res = 0;
        if (typeof valA === 'string' && typeof valB === 'string') {
            res = valA.localeCompare(valB, undefined, { numeric: true, sensitivity: 'base' });
        } else if (typeof valA === 'boolean' && typeof valB === 'boolean') {
            res = (valA === valB) ? 0 : valA ? 1 : -1;
        } else {
            res = valA < valB ? -1 : (valA > valB ? 1 : 0);
        }
        return res * dir;
    });
},

checkTimezone() {
    if (this.ui_tz && !this.validTimezones.includes(this.ui_tz)) {
        this.errors.tz = 'Please select a valid timezone location from the list.';
        return false;
    }
    this.errors.tz = '';
    return true;
},

validateDedupeWindow() {
    const val = (this.smtp.dedupe_window || '').trim().toLowerCase();
    if (!val) {
        this.errors.dedupeWindow = '';
        return true;
    }
    const regex = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/;
    if (!regex.test(val)) {
        this.errors.dedupeWindow = 'Invalid window string format definition constraint.';
        return false;
    }
    this.errors.dedupeWindow = '';
    return true;
},

toggleDedupeTag(tag) {
    let currentKeys = Array.isArray(this.smtp.dedupe_keys) ? [...this.smtp.dedupe_keys] : ['sender', 'match_reason', 'message'];

    if (currentKeys.includes(tag)) {
        if (currentKeys.length <= 1) {
            alert("You must maintain at least one configuration property tag to compose deduplication contract hashes.");
            return;
        }
        this.smtp.dedupe_keys = currentKeys.filter(k => k !== tag);
    } else {
        currentKeys.push(tag);
        this.smtp.dedupe_keys = currentKeys;
    }
},

clone(targetObj) {
    if (!targetObj) return {};
    return JSON.parse(JSON.stringify(targetObj));
},

async _isValidNetworkTarget(val, allowCidr) {
    if (!val) return false;
    try {
        const res = await fetch('/api/validate/network', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target: val, allow_cidr: allowCidr })
        });
        if (res.ok) {
            const data = await res.json();
            return data.valid === true;
        }
        return false;
    } catch (e) {
        console.error("Network validation async boundary failure:", e);
        return false;
    }
},

async isValidIP(ip) {
    return await this._isValidNetworkTarget(ip, false);
},

async isValidIPOrCIDR(val) {
    return await this._isValidNetworkTarget(val, true);
},

async _validateCidrList(lines) {
    for (let line of lines) {
        const isValid = await this._isValidNetworkTarget(line, true);
        if (!isValid) {
            return `Invalid IP or CIDR Subnet: ${line}`;
        }
    }
    return '';
},

async _processCidrAdd(targetArray, inputVal) {
    const val = (inputVal || '').trim();
    if (!val) return { error: '', clear: true };

    const isValid = await this._isValidNetworkTarget(val, true);
    if (!isValid) {
        return { error: `Invalid IP or CIDR Subnet: ${val}`, clear: false };
    }
    if (!targetArray.includes(val)) targetArray.push(val);
    return { error: '', clear: true };
},

async addUiCidr() {
    const res = await this._processCidrAdd(this.ui_allowed_cidrs, this.uiCidrInput);
    this.errors.uiCidr = res.error;
    if (res.clear) this.uiCidrInput = '';
},

removeUiCidr(idx) {
    this.ui_allowed_cidrs.splice(idx, 1);
    this.errors.uiCidr = '';
},

async addSmtpCidr() {
    if (!this.smtp.allowed_cidrs) this.smtp.allowed_cidrs = [];
    const res = await this._processCidrAdd(this.smtp.allowed_cidrs, this.smtpCidrInput);
    this.errors.smtpCidr = res.error;
    if (res.clear) this.smtpCidrInput = '';
},

removeSmtpCidr(idx) {
    this.smtp.allowed_cidrs.splice(idx, 1);
    this.errors.smtpCidr = '';
},

async addTrustProxyCidr() {
    const res = await this._processCidrAdd(this.ui_trust_proxy_cidrs, this.uiTrustProxyCidrInput);
    this.errors.uiTrustProxyCidr = res.error;
    if (res.clear) this.uiTrustProxyCidrInput = '';
},

removeTrustProxyCidr(idx) {
    this.ui_trust_proxy_cidrs.splice(idx, 1);
    this.errors.uiTrustProxyCidr = '';
},
