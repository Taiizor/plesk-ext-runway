// Copyright 2026 Taiizor. Licensed under the MIT License.

import { afterEach, beforeEach, expect, mock, test } from 'bun:test';
import { ApiError, createApi } from '../../src/frontend/lib/api';

const original = {
    fetch: globalThis.fetch,
    document: globalThis.document,
    window: globalThis.window,
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
};
let timers;
let nextTimer;

beforeEach(() => {
    timers = new Map();
    nextTimer = 0;
    globalThis.document = { getElementById: () => ({ content: 'csrf-token' }) };
    globalThis.window = { Ajax: { activeRequestCount: 0 } };
    globalThis.setTimeout = (callback, delay) => {
        const id = ++nextTimer;
        timers.set(id, { callback, delay });
        return id;
    };
    globalThis.clearTimeout = id => timers.delete(id);
});

afterEach(() => {
    Object.assign(globalThis, original);
});

const respond = json => ({ status: 200, text: () => Promise.resolve(JSON.stringify(json)) });
const expire = () => [...timers.values()][0].callback();

test('successful requests preserve CSRF, query parameters and JSON bodies, and clear their timers', async () => {
    const signals = [];
    globalThis.fetch = mock((url, init) => {
        expect(url).toBe('/runway/api/app/save?site_id=7');
        expect(init.credentials).toBe('same-origin');
        expect(init.headers['X-Forgery-Protection-Token']).toBe('csrf-token');
        expect(JSON.parse(init.body)).toEqual({ enabled: true });
        signals.push(init.signal);
        return Promise.resolve(respond({ status: 'success', data: { saved: true } }));
    });
    const result = await createApi('/runway').post('app/save', { enabled: true }, { site_id: 7 });
    expect(result).toEqual({ saved: true });
    expect(signals[0].aborted).toBe(false);
    expect(timers.size).toBe(0);
    expect(window.Ajax.activeRequestCount).toBe(0);
});

test('polls, other reads and writes have separate finite deadlines', async () => {
    globalThis.fetch = mock(() => Promise.resolve(respond({ status: 'success', data: {} })));
    const api = createApi('/runway');
    for (const path of ['app/status', '/app/logs', 'job', 'update']) {
        const pending = api.get(path);
        expect([...timers.values()][0].delay).toBe(30000);
        await pending;
    }
    const read = api.get('toolchains', { available: true });
    expect([...timers.values()][0].delay).toBe(120000);
    await read;
    const write = api.post('app/save', {});
    expect([...timers.values()][0].delay).toBe(300000);
    await write;
    expect(timers.size).toBe(0);
});

test('a stalled fetch is aborted and rejects with the translated timeout instead of AbortError', async () => {
    let signal;
    globalThis.fetch = mock((_url, init) => {
        signal = init.signal;
        return new Promise((resolve, reject) => {
            signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        });
    });
    const translate = mock(key => key === 'Common.requestTimeout' ? 'Translated timeout' : key);
    const pending = createApi('/runway', translate).get('app/status').catch(error => error);
    await Promise.resolve();
    expire();
    const error = await pending;
    expect(signal.aborted).toBe(true);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.message).toBe('Translated timeout');
    expect(error.status).toBe(0);
    expect(timers.size).toBe(0);
    expect(window.Ajax.activeRequestCount).toBe(0);
});

test('the deadline includes a response body that stalls after headers arrive', async () => {
    let signal;
    globalThis.fetch = mock((_url, init) => {
        signal = init.signal;
        return Promise.resolve({ status: 200, text: () => new Promise(() => {}) });
    });
    const pending = createApi('/runway').get('app/status').catch(error => error);
    await Promise.resolve();
    await Promise.resolve();
    expire();
    expect((await pending).message).toContain('timed out');
    expect(signal.aborted).toBe(true);
    expect(timers.size).toBe(0);
    expect(window.Ajax.activeRequestCount).toBe(0);
});

test('a timed-out write never retries automatically and a late response cannot change its result', async () => {
    let finish;
    globalThis.fetch = mock(() => new Promise(resolve => { finish = resolve; }));
    const pending = createApi('/runway').post('app/control', { op: 'restart' }).catch(error => error);
    await Promise.resolve();
    expire();
    const error = await pending;
    expect(error.message).toContain('server may still be processing');
    finish(respond({ status: 'success', data: { restarted: true } }));
    await Promise.resolve();
    expect(await pending).toBe(error);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(window.Ajax.activeRequestCount).toBe(0);
});

test('validation errors keep their field mapping and release request bookkeeping', async () => {
    globalThis.fetch = mock(() => Promise.resolve(respond({ status: 'error', errors: { appRoot: ['Invalid directory'] } })));
    const error = await createApi('/runway').post('app/save', {}).catch(value => value);
    expect(error.fieldErrors).toEqual({ appRoot: ['Invalid directory'] });
    expect(timers.size).toBe(0);
    expect(window.Ajax.activeRequestCount).toBe(0);
});

test('synchronous fetch failures and malformed responses also clear their deadlines', async () => {
    globalThis.fetch = mock(() => { throw new TypeError('Network failure'); });
    await expect(createApi('/runway').get('context')).rejects.toThrow('Network failure');
    expect(timers.size).toBe(0);
    expect(window.Ajax.activeRequestCount).toBe(0);
    globalThis.fetch = mock(() => Promise.resolve({ status: 502, text: () => Promise.resolve('<html>Bad gateway</html>') }));
    await expect(createApi('/runway').get('context')).rejects.toThrow('Unexpected response');
    expect(timers.size).toBe(0);
    expect(window.Ajax.activeRequestCount).toBe(0);
});
