// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Formatting helpers shared by the pages. Everything tolerates missing values (the backend
 * may omit fields), returning null so callers can render a dash.
 */

const isPlainObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);

/**
 * Default build/start commands of a runtime for a listen mode and toolchain, from the
 * "defaults" of api/app: defaults[runtime].variants["<tcp|unix>|<toolchain>"] (toolchain ""
 * unless the runtime's defaults depend on it), falling back to defaults[runtime] itself.
 * Returns null when the runtime has no defaults.
 */
export const runtimeDefaults = (defaults, runtime, listen, toolchain) => {
    const base = isPlainObject(defaults) && isPlainObject(defaults[runtime]) ? defaults[runtime] : null;
    if (!base) {
        return null;
    }
    const variants = isPlainObject(base.variants) ? base.variants : {};
    const mode = listen === 'unix' ? 'unix' : 'tcp';
    return variants[`${mode}|${toolchain || ''}`] || variants[`${mode}|`] || base;
};

/** Whether the default start command of a runtime/toolchain can listen on a Unix socket. */
export const unixSupported = (defaults, runtime, toolchain) => {
    const variant = runtimeDefaults(defaults, runtime, 'unix', toolchain);
    return !variant || variant.unix_supported !== false;
};

/**
 * Whether any installed toolchain of a runtime can serve a sample app on a Unix socket (the
 * helper picks a suitable toolchain, e.g. FrankenPHP for PHP).
 */
export const unixPossible = (defaults, runtime, installed) => {
    const base = isPlainObject(defaults) && isPlainObject(defaults[runtime]) ? defaults[runtime] : null;
    const variants = base && isPlainObject(base.variants) ? base.variants : {};
    const keys = (Array.isArray(installed) ? installed : [])
        .map(item => `unix|${item && item.id}`)
        .filter(key => isPlainObject(variants[key]));
    if (keys.length) {
        return keys.some(key => variants[key].unix_supported !== false);
    }
    return unixSupported(defaults, runtime, '');
};

export const formatBytes = value => {
    const bytes = Number(value);
    if (value === null || value === undefined || value === '' || !isFinite(bytes) || bytes < 0) {
        return null;
    }
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
    let size = bytes;
    let unit = 0;
    while (size >= 1024 && unit < units.length - 1) {
        size /= 1024;
        unit++;
    }
    return `${unit === 0 ? size : size.toFixed(size < 10 ? 1 : 0)} ${units[unit]}`;
};

/**
 * Parses ISO 8601 times of the helper ("2026-11-11T14:27:27+00:00") and systemd timestamps
 * ("Wed 2026-11-11 14:27:27 UTC"). Returns a Date or null.
 */
export const parseTime = value => {
    if (!value || typeof value !== 'string') {
        return null;
    }
    let text = value.trim();
    const systemd = text.match(/^(?:[A-Za-z]{3} )?(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?: (UTC|GMT))?$/);
    if (systemd) {
        text = `${systemd[1]}T${systemd[2]}${systemd[3] ? 'Z' : ''}`;
    }
    const time = Date.parse(text);
    return isNaN(time) ? null : new Date(time);
};

export const formatTime = value => {
    const date = parseTime(value);
    if (!date) {
        return value ? String(value) : null;
    }
    try {
        return date.toLocaleString();
    } catch (e) {
        return date.toISOString();
    }
};

/**
 * Application state of the domain page from api/app/status (same rules as the overview,
 * App::uiState): notConfigured, disabled, suspended, tampered, running, starting, stopping,
 * failed or stopped.
 */
export const appState = (status, configured) => {
    if (!configured || !status || status.configured === false) {
        return 'notConfigured';
    }
    if (status.enabled === false) {
        return 'disabled';
    }
    if (status.suspended) {
        return 'suspended';
    }
    if (status.tampered) {
        return 'tampered';
    }
    const map = {
        active: 'running',
        activating: 'starting',
        reloading: 'starting',
        deactivating: 'stopping',
        failed: 'failed',
    };
    const active = status.service && status.service.active_state;
    return map[active] || 'stopped';
};

/** Label intent of an application state. */
export const stateIntent = state => ({
    running: 'success',
    starting: 'info',
    stopping: 'info',
    failed: 'danger',
    tampered: 'danger',
    stopped: 'warning',
    suspended: 'warning',
    disabled: 'inactive',
    notConfigured: 'inactive',
})[state] || 'inactive';

/** Label intent of a background job state. */
export const jobIntent = state => ({
    queued: 'info',
    running: 'info',
    succeeded: 'success',
    failed: 'danger',
})[state] || 'inactive';

/** First non-empty string of the arguments (or null). */
export const firstString = (...values) => {
    for (let i = 0; i < values.length; i++) {
        if (typeof values[i] === 'string' && values[i] !== '') {
            return values[i];
        }
    }
    return null;
};

/**
 * Wraps a name, version, address or path in Unicode first-strong isolates (U+2068 ... U+2069),
 * so that it keeps its own direction inside right-to-left text: ".NET" or "/api" would otherwise
 * show as "NET." or "api/" in Arabic and Hebrew. Invisible in left-to-right languages.
 */
export const isolate = value => (value === null || value === undefined || value === '' ? value : `\u2068${value}\u2069`);

/**
 * A text produced by the helper in the user's language: the locale key `key` (with `params`)
 * when the locale has it, else the helper's English `fallback` (docs/DESIGN.md section 7:
 * hint_key, title_key, listener_code, health_code). Parameters (names, versions, addresses)
 * are isolated, see isolate().
 */
// Runtime hints of the helper metadata (hint_key, install_help_key):
// i18n-keys: Runtime.go.hint Runtime.rust.hint Runtime.rust.installHelp Runtime.bun.hint Runtime.java.hint
// i18n-keys: Runtime.dotnet.hint Runtime.python.hint Runtime.ruby.hint Runtime.ruby.installHelp
// i18n-keys: Runtime.php.hint Runtime.php.installHelp Runtime.binary.hint
export const helperText = (translate, key, params, fallback) => {
    if (!key) {
        return fallback || '';
    }
    const values = {};
    Object.keys(isPlainObject(params) ? params : {}).forEach(name => {
        values[name] = isolate(String(params[name]));
    });
    const text = translate(key, values, fallback || '');
    return (typeof text === 'string' && text !== key) || Array.isArray(text) ? text : (fallback || '');
};

/** Title of a job in the user's language (helper title_key + title_params, English title as fallback). */
// i18n-keys: Common.jobTitle.install Common.jobTitle.update Common.jobTitle.build_deps
// i18n-keys: Common.jobTitle.deploy_build Common.jobTitle.deploy_restart Common.jobTitle.deploy_fetch
// i18n-keys: Common.jobTitle.deploy_build_only Common.jobTitle.deploy_restart_skipped Common.jobTitle.deploy_fetch_only
export const jobTitle = (translate, job) => (
    job && job.title_key ? helperText(translate, `Common.jobTitle.${job.title_key}`, job.title_params, job.title || '') : ((job && job.title) || '')
);

/**
 * Display name of a runtime (helper metadata `meta`), isolated: the product names as they are,
 * "Prebuilt binary" in the user's language.
 */
// i18n-keys: Runtime.binary.label
export const runtimeName = (translate, meta) => {
    if (!meta) {
        return '';
    }
    const label = meta.key === 'binary' ? helperText(translate, 'Runtime.binary.label', null, meta.label) : meta.label;
    return isolate(label || meta.key);
};

/** Plain object check (not null, not an array). */
export const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
