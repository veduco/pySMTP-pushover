confirmSave() {
    if (this.diffModal.targetForm === 'ui_form') {
        if (!this.checkTimezone()) {
            this.diffModal.open = false;
            return;
        }
    }

    this.diffModal.open = false;

    setTimeout(() => {
        const formEl = document.getElementById(this.diffModal.targetForm);
        if (formEl) htmx.trigger(formEl, 'confirmedSave');
    }, 150);
},

performReconnect() {
    this.isReconnecting = true;

    setTimeout(() => {
        const checkServer = async () => {
            try {
                const res = await fetch('/?ping=' + Date.now(), { method: 'GET', cache: 'no-store' });
                if (res.ok) {
                    window.location.reload();
                } else {
                    setTimeout(checkServer, 500);
                }
            } catch (e) {
                setTimeout(checkServer, 500);
            }
        };

        checkServer();
    }, 1500);
},

clearTestPayload() {
    this.testPayload.from = this.defaultTestPayload.from;
    this.testPayload.to = this.defaultTestPayload.to;
    this.testPayload.type = this.defaultTestPayload.type;
    this.testPayload.message_plain = this.defaultTestPayload.message_plain;
    this.testPayload.message_html = this.defaultTestPayload.message_html;
    this.testPayload.status = '';
    this.testPayload.isError = false;
},

async sendTestPayload() {
    this.testPayload.loading = true;
    this.testPayload.status = '';
    this.testPayload.isError = false;

    try {
        const res = await fetch('/api/queue/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                from: this.testPayload.from,
                to: this.testPayload.to,
                type: this.testPayload.type,
                message_plain: this.testPayload.message_plain,
                message_html: this.testPayload.message_html
            })
        });

        const data = await res.json();
        if (res.ok) {
            this.testPayload.status = 'Payload injected successfully! Check Queue Stream.';
            this.testPayload.isError = false;
            setTimeout(() => { this.testPayload.status = ''; }, ALERT_TIMEOUT_MS);
        } else {
            this.testPayload.status = data.error || 'Failed to inject payload.';
            this.testPayload.isError = true;
        }
    } catch (e) {
        this.testPayload.status = 'Network error during injection.';
        this.testPayload.isError = true;
    } finally {
        this.testPayload.loading = false;
    }
},
