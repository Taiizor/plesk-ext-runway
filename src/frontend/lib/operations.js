// Copyright 2026 Taiizor. Licensed under the MIT License.

const PATH_FIELDS = ['shared_paths', 'exclude_paths'];
const NUMBER_FIELDS = ['history_limit', 'min_free_mb', 'release_limit', 'release_max_mb'];

/** Public helper settings become editable values; an existing signing secret is never returned. */
export const operationsValues = options => ({
    ...options,
    shared_paths: (options.shared_paths || []).join('\n'),
    exclude_paths: (options.exclude_paths || []).join('\n'),
    notification_secret: '',
    clear_notification_secret: false,
});

export const operationsBody = values => {
    const result = { ...values };
    delete result.has_notification_secret;
    PATH_FIELDS.forEach(key => {
        result[key] = String(values[key] || '').split(/\r?\n/).map(value => value.trim()).filter(Boolean);
    });
    NUMBER_FIELDS.forEach(key => {
        const value = String(values[key]).trim();
        result[key] = /^\d+$/.test(value) ? Number(value) : value;
    });
    return result;
};

/** Recovery is configuration only; reject oversized input before parsing it in the panel. */
export const recoveryBundle = text => {
    if (typeof text !== 'string' || new TextEncoder().encode(text).length > 512 * 1024) {
        throw new Error('Invalid recovery data');
    }
    const bundle = JSON.parse(text);
    if (!bundle || bundle.schema !== 1 || !bundle.application || !bundle.operations) {
        throw new Error('Invalid recovery data');
    }
    return bundle;
};

export const downloadJson = (name, data) => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = name;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
};
