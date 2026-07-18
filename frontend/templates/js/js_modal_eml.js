emlModal: { open: false, id: '', content: '', rawBytes: null, loading: false, title: '' },

async inspectEml(item) {
    this.emlModal.loading = true;
    this.emlModal.id = item.id;
    this.emlModal.title = item.title;
    this.emlModal.open = true;
    this.emlModal.content = '';
    this.emlModal.rawBytes = null;
    try {
        const res = await fetch('/api/queue/' + item.id + '/eml');
        const data = await res.json();
        if (data.raw_eml_base64) {
            // Convert Base64 back to binary array for pristine .eml assembly
            const byteString = atob(data.raw_eml_base64);
            const ia = new Uint8Array(byteString.length);
            for (let i = 0; i < byteString.length; i++) ia[i] = byteString.charCodeAt(i);

            this.emlModal.rawBytes = ia;
            this.emlModal.content = new TextDecoder('utf-8', {fatal: false}).decode(ia);
        } else {
            this.emlModal.content = 'No raw EML payload found for this item. Was disk persistence explicitly disabled on ingestion?';
        }
    } catch (e) {
        this.emlModal.content = 'Error fetching diagnostic EML structural data.';
    }
    this.emlModal.loading = false;
},

downloadEml() {
    if (!this.emlModal.rawBytes) return;
    const blob = new Blob([this.emlModal.rawBytes], { type: 'message/rfc822' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'message_' + this.emlModal.id + '.eml';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
},
