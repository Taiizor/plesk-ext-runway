// Copyright 2026 Taiizor. Licensed under the MIT License.

import { afterEach, beforeEach, expect, mock, test } from 'bun:test';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { createApi } from '../../src/frontend/lib/api';

// Keep the status card's markup observable without loading the SDK's panel-wide providers.
mock.module('@plesk/plesk-ext-sdk', () => ({
    useTranslate: () => key => key,
    Alert: ({ children }) => createElement('div', { role: 'alert' }, children),
    Button: ({ children }) => createElement('button', null, children),
    Label: ({ children }) => createElement('span', null, children),
    Panel: ({ children }) => createElement('section', null, children),
    Text: ({ children }) => createElement('span', null, children),
    Translate: ({ content, params }) => createElement('span', null, content, params && params.time),
}));
const { useAppStatus, usePolling } = await import('../../src/frontend/lib/hooks');
const { default: StatusPanel } = await import('../../src/frontend/domain/StatusPanel');

const original = {
    window: globalThis.window,
    document: globalThis.document,
    fetch: globalThis.fetch,
    setTimeout: globalThis.setTimeout,
    clearTimeout: globalThis.clearTimeout,
    IS_REACT_ACT_ENVIRONMENT: globalThis.IS_REACT_ACT_ENVIRONMENT,
};
let dom;
let root;
let props;
let model;

const Probe = ({ api, siteId, page, polling }) => {
    model = useAppStatus(api, siteId, page);
    usePolling(model.refresh, 6, Boolean(polling));
    return null;
};

const render = async changes => {
    props = { ...props, ...changes };
    await act(async () => { root.render(createElement(Probe, props)); });
};

const deferred = () => {
    let resolve;
    let reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
};

beforeEach(() => {
    dom = new JSDOM('<!doctype html><div id="root"></div>', { pretendToBeVisual: true });
    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    root = createRoot(document.getElementById('root'));
    props = { api: { get: mock(() => Promise.resolve({ running: true })) }, siteId: '7', page: { status: { running: true } } };
});

afterEach(async () => {
    if (root) {
        await act(async () => { root.unmount(); });
    }
    dom.window.close();
    Object.assign(globalThis, original);
});

test('failed status refresh keeps the last snapshot and timestamp; recovery clears the warning', async () => {
    await render();
    const initial = model.status;
    const updatedAt = model.updatedAt;
    expect(updatedAt).toBeTruthy();
    props.api.get = mock(() => Promise.reject(new Error('Server unavailable')));
    await act(async () => { await model.refresh(); });
    expect(model.status).toBe(initial);
    expect(model.updatedAt).toBe(updatedAt);
    expect(model.error).toBe('Server unavailable');
    props.api.get = mock(() => Promise.resolve({ running: false }));
    await act(async () => { await model.refresh(); });
    expect(model.status).toEqual({ running: false });
    expect(model.error).toBeNull();
    expect(Date.parse(model.updatedAt)).toBeGreaterThanOrEqual(Date.parse(updatedAt));
});

test('a failed page reload preserves the snapshot, and a successful reload clears the error', async () => {
    await render();
    const initial = model.status;
    const updatedAt = model.updatedAt;
    await render({ page: { status: null, pageError: 'Helper unavailable' } });
    expect(model.error).toBe('Helper unavailable');
    expect(model.status).toBe(initial);
    expect(model.updatedAt).toBe(updatedAt);
    await render({ page: { status: { running: false } } });
    expect(model.status).toEqual({ running: false });
    expect(model.error).toBeNull();
});

test('late errors cannot replace newer successful polls or page snapshots', async () => {
    await render();
    for (const fromPage of [false, true]) {
        const old = deferred();
        props.api.get = mock(() => old.promise);
        const pending = model.refresh();
        if (fromPage) {
            await render({ page: { status: { newer: 'page' } } });
        } else {
            props.api.get = mock(() => Promise.resolve({ newer: 'poll' }));
            await act(async () => { await model.refresh(); });
        }
        await act(async () => { old.reject(new Error('Old failure')); await pending; });
        expect(model.error).toBeNull();
        expect(model.status).toEqual({ newer: fromPage ? 'page' : 'poll' });
    }
});

test('local job hints do not mark stale data fresh and clearing status resets freshness', async () => {
    await render();
    props.api.get = mock(() => Promise.reject(new Error('Offline')));
    await act(async () => { await model.refresh(); });
    const updatedAt = model.updatedAt;
    await act(async () => { model.setStatus(prev => ({ ...prev, deploy: { state: 'queued' } })); });
    expect(model.error).toBe('Offline');
    expect(model.updatedAt).toBe(updatedAt);
    expect(model.status.deploy.state).toBe('queued');
    await act(async () => { model.setStatus(null); });
    expect(model.status).toBeNull();
    expect(model.error).toBeNull();
    expect(model.updatedAt).toBeNull();
});

test('switching domains discards the old snapshot and ignores its unfinished request', async () => {
    await render();
    const old = deferred();
    props.api.get = mock(() => old.promise);
    const pending = model.refresh();
    await render({ siteId: '8' });
    await act(async () => { old.resolve({ wrongDomain: true }); await pending; });
    expect(model.status).toBeNull();
    expect(model.updatedAt).toBeNull();
    await render({ page: { status: { domainId: 8 } } });
    expect(model.status).toEqual({ domainId: 8 });
});

test('an unfinished request can settle safely after unmount', async () => {
    await render();
    const old = deferred();
    props.api.get = mock(() => old.promise);
    const pending = model.refresh();
    await act(async () => { root.unmount(); });
    root = null;
    old.reject(new Error('Late failure'));
    await pending;
    expect(model.error).toBeNull();
});

test('the status card displays the stale warning and last success time, then removes the warning on recovery', async () => {
    const card = {
        data: { configured: true, config: { enabled: true } },
        status: { configured: true, enabled: true, service: { active_state: 'active' } },
        updatedAt: '2026-11-15T10:11:12Z',
        onControl: () => {},
        onStop: () => {},
    };
    await act(async () => { root.render(createElement(StatusPanel, { ...card, error: 'Server unavailable' })); });
    expect(document.querySelector('[role="alert"]').textContent).toContain('Domain.status.refreshFailed');
    expect(document.querySelector('[role="alert"]').textContent).toContain('Server unavailable');
    expect(document.body.textContent).toContain('Domain.status.lastUpdated');
    expect(document.body.textContent).toContain(new Date(card.updatedAt).toLocaleString());
    expect(document.body.textContent).toContain('Overview.state.running');
    await act(async () => { root.render(createElement(StatusPanel, { ...card, error: null })); });
    expect(document.querySelector('[role="alert"]')).toBeNull();
    expect(document.body.textContent).toContain('Domain.status.lastUpdated');
});

test('polling resumes after a real API timeout and the next response clears stale status', async () => {
    const timers = new Map();
    let sequence = 0;
    globalThis.setTimeout = (callback, delay, ...args) => {
        if (delay !== 6 && delay !== 30000) {
            return original.setTimeout(callback, delay, ...args);
        }
        const id = ++sequence;
        timers.set(id, { callback, delay });
        return id;
    };
    globalThis.clearTimeout = id => {
        if (!timers.delete(id)) {
            original.clearTimeout(id);
        }
    };
    const fire = delay => {
        const timer = [...timers.entries()].find(([, entry]) => entry.delay === delay);
        expect(timer).toBeDefined();
        timers.delete(timer[0]);
        timer[1].callback();
    };
    let firstSignal;
    globalThis.fetch = mock((_url, init) => {
        if (!firstSignal) {
            firstSignal = init.signal;
            return new Promise(() => {});
        }
        return Promise.resolve({ status: 200, text: () => Promise.resolve('{"status":"success","data":{"recovered":true}}') });
    });
    window.Ajax = { activeRequestCount: 0 };
    await render({ api: createApi('/runway'), polling: true });
    await act(async () => { fire(6); });
    await act(async () => { fire(30000); });
    expect(firstSignal.aborted).toBe(true);
    expect(model.error).toContain('timed out');
    expect(window.Ajax.activeRequestCount).toBe(0);
    await act(async () => { fire(6); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(model.status).toEqual({ recovered: true });
    expect(model.error).toBeNull();
    expect(window.Ajax.activeRequestCount).toBe(0);
});
