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
isValidIP(ip) {
    if (ip === 'localhost') return true;
    const ipv4 = /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
    const ipv6 = /^(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))$/;
    return ipv4.test(ip) || ipv6.test(ip);
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
checkTimezone() {
    if (this.ui_tz && !this.validTimezones.includes(this.ui_tz)) {
        this.tzError = 'Please select a valid timezone location from the list.';
        return false;
    }
    this.tzError = '';
    return true;
},
clone(targetObj) {
    if (!targetObj) return {};
    return JSON.parse(JSON.stringify(targetObj));
},
