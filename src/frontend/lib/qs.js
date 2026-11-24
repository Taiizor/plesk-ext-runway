// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// The one function of "qs" that the bundle needs: @plesk/plesk-ext-sdk's own api helper (src/Api/api.js)
// imports { stringify } from 'qs' for the query string of api.get(). Runway's pages use lib/api.js
// instead, and the full qs package brings object-inspect and the side-channel modules into main.js
// (over webpack's recommended size). extension.config.js aliases 'qs' to this file.
//
// Same output as qs.stringify(object) with its default options (arrayFormat "indices", RFC 3986
// encoding, null as an empty value, undefined skipped): tests/frontend/qs.test.js compares both.

const encode = value => encodeURIComponent(value).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());

const serialize = (prefix, value, parts) => {
    if (value === undefined) {
        return;
    }
    if (value === null) {
        parts.push(encode(prefix) + '=');
        return;
    }
    if (value instanceof Date) {
        parts.push(encode(prefix) + '=' + encode(value.toISOString()));
        return;
    }
    if (typeof value === 'object') {
        Object.keys(value).forEach(key => serialize(prefix + '[' + key + ']', value[key], parts));
        return;
    }
    parts.push(encode(prefix) + '=' + encode(String(value)));
};

export const stringify = object => {
    if (object === null || typeof object !== 'object') {
        return '';
    }
    const parts = [];
    Object.keys(object).forEach(key => serialize(key, object[key], parts));
    return parts.join('&');
};

export default { stringify };
