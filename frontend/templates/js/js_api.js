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
