class GatewayModal {
    constructor(schemaRegistry, schemaPath, customOverrides = {}) {
        // Protected Transient UI States (Never sink to disk layer)
        this.open = false;
        this.error = '';
        this.mode = 'add';
        this.showToken = false;

        // Dynamic structural provisioning directly from the JSON backend schema
        this.defaultFields = this._extractSchemaFields(schemaRegistry, schemaPath);

        // Override baseline arrays/properties with context-specific frontend needs
        this.fields = { ...this.defaultFields, ...customOverrides };
        this.orig = JSON.parse(JSON.stringify(this.fields));
    }

    _extractSchemaFields(schema, path) {
        if (!path) return {};
        const parts = path.split('.');
        let current = schema;
        for (const part of parts) {
            if (current === undefined || current === null) return {};
            current = current[part];
        }

        if (Array.isArray(current)) {
            // Safely clone the index 0 array parameter definition shape
            return current[0] ? JSON.parse(JSON.stringify(current[0])) : {};
        }
        return current ? JSON.parse(JSON.stringify(current)) : {};
    }

    initOpen(mode, dynamicData = {}) {
        this.mode = mode;
        this.error = '';
        this.showToken = false;

        // Enforce safe structural boundaries before opening
        if (mode === 'add') {
            this.fields = JSON.parse(JSON.stringify({ ...this.defaultFields, ...dynamicData }));
        } else {
            this.fields = JSON.parse(JSON.stringify(dynamicData));
        }

        this.orig = JSON.parse(JSON.stringify(this.fields));
        this.open = true;
    }

    clear() {
        this.fields = JSON.parse(JSON.stringify(this.orig));
        this.error = '';
    }

    get isDirty() {
        return JSON.stringify(this.fields) !== JSON.stringify(this.orig);
    }
}
