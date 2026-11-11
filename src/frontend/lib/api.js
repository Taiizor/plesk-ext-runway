// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Client for the Runway JSON API (plib/controllers/ApiController.php, docs/DESIGN.md section 6).
 *
 *   const api = createApi(baseUrl, translate);   // baseUrl prop of every page: /modules/runway/index.php
 *   const data = await api.get('overview');      // resolves with response.data
 *   await api.get('app', { site_id: 1 });        // query parameters
 *   await api.post('app/save', { site_id: 1, enabled: true });
 *
 * Every request sends the panel's CSRF token (X-Forgery-Protection-Token, read from the
 * <meta id="forgery_protection_token"> tag of the Plesk page) like the SDK's own client.
 * Errors of the client itself (an HTML page instead of JSON, an unknown error format) use the locale
 * keys Common.unexpectedResponse / Common.requestFailed through `translate` (useApi passes the
 * page's translate function); the server's messages are already translated.
 * A response {"status":"error"} rejects with an ApiError:
 *   error.message      first message (for an Alert or a toast)
 *   error.messages     every message as a flat list
 *   error.fieldErrors  {field: ['message', ...]} for validation errors, otherwise null
 */

export class ApiError extends Error {
    constructor(messages, fieldErrors = null, status = 0) {
        super(messages[0] || 'Request failed');
        this.name = 'ApiError';
        this.messages = messages;
        this.fieldErrors = fieldErrors;
        this.status = status;
    }
}

const forgeryToken = () => {
    const element = document.getElementById('forgery_protection_token');
    return element ? element.content : null;
};

const buildUrl = (baseUrl, path, query) => {
    let url = `${baseUrl}/api/${path.replace(/^\/+/, '')}`;
    const params = new URLSearchParams();
    Object.keys(query || {}).forEach(key => {
        const value = query[key];
        if (value !== undefined && value !== null) {
            params.append(key, String(value));
        }
    });
    const search = params.toString();
    if (search) {
        url += (url.indexOf('?') === -1 ? '?' : '&') + search;
    }
    return url;
};

// i18n-keys: Common.requestFailed Common.unexpectedResponse
/** Translated message of the client, English when no translate function is available. */
const clientMessage = (translate, key, status, fallback) => {
    if (typeof translate === 'function') {
        const text = translate(key, { status: String(status) }, fallback);
        if (typeof text === 'string' && text && text !== key) {
            return text;
        }
    }
    return fallback;
};

const toApiError = (json, status, translate) => {
    const errors = json && json.errors;
    if (errors && !Array.isArray(errors) && typeof errors === 'object') {
        const messages = Object.keys(errors).reduce((list, field) => list.concat(errors[field]), []);
        return new ApiError(messages.map(String), errors, status);
    }
    if (Array.isArray(errors) && errors.length) {
        return new ApiError(errors.map(String), null, status);
    }
    // Errors raised by Plesk itself (e.g. an invalid CSRF token) come as {"message": "..."}.
    if (json && typeof json.message === 'string' && json.message) {
        return new ApiError([json.message.split('\n')[0].replace(/#0 .*$/, '').trim()], null, status);
    }
    return new ApiError([clientMessage(translate, 'Common.requestFailed', status, `Request failed (HTTP ${status}).`)], null, status);
};

const request = (baseUrl, path, { method = 'GET', query, body } = {}, translate = null) => {
    const headers = {
        Accept: 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
    };
    const token = forgeryToken();
    if (token) {
        headers['X-Forgery-Protection-Token'] = token;
    }
    const init = { method, headers, credentials: 'same-origin' };
    if (method !== 'GET') {
        headers['Content-Type'] = 'application/json; charset=utf-8';
        init.body = JSON.stringify(body || {});
    }
    if (window.Ajax) {
        window.Ajax.activeRequestCount++;
    }
    return fetch(buildUrl(baseUrl, path, query), init)
        .then(response => response.text().then(text => {
            let json = null;
            try {
                json = JSON.parse(text);
            } catch (e) {
                // An HTML page instead of JSON: usually an expired session or a PHP fatal error.
                throw new ApiError([clientMessage(translate, 'Common.unexpectedResponse', response.status,
                    `Unexpected response from the server (HTTP ${response.status}). Reload the page and try again.`)], null, response.status);
            }
            if (json && json.status === 'success') {
                return json.data;
            }
            throw toApiError(json, response.status, translate);
        }))
        .finally(() => {
            if (window.Ajax) {
                window.Ajax.activeRequestCount--;
            }
        });
};

export const createApi = (baseUrl, translate = null) => ({
    get: (path, query) => request(baseUrl, path, { query }, translate),
    post: (path, body, query) => request(baseUrl, path, { method: 'POST', body, query }, translate),
});

/**
 * Converts ApiError.fieldErrors ({field: ['msg']}) to the ui-library Form "errors" format
 * ({field: {key: 'msg'}}).
 */
export const formErrors = error => {
    const result = {};
    if (!error || !error.fieldErrors) {
        return result;
    }
    Object.keys(error.fieldErrors).forEach(field => {
        result[field] = {};
        [].concat(error.fieldErrors[field]).forEach((message, index) => {
            result[field][`e${index}`] = String(message);
        });
    });
    return result;
};
