// Copyright 2026 Taiizor. Licensed under the MIT License.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslate } from '@plesk/plesk-ext-sdk';
import { createApi } from './api';

/** Polling keeps running while the tab is hidden for this long after a user action (DESIGN section 8). */
export const POLL_GRACE_MS = 120000;
/** Normal status refresh interval and the faster one while a background job runs. */
export const POLL_IDLE_MS = 6000;
export const POLL_BUSY_MS = 2000;

/** Job states that mean "still working". */
export const BUSY_STATES = ['queued', 'running'];
export const isBusy = job => Boolean(job && BUSY_STATES.indexOf(job.state) !== -1);

/**
 * API client bound to the page's baseUrl prop; its own error messages use the page's locale.
 */
export const useApi = baseUrl => {
    const translate = useTranslate();
    const latest = useRef(translate);
    latest.current = translate;
    return useMemo(() => createApi(baseUrl, (key, params, fallback) => latest.current(key, params, fallback)), [baseUrl]);
};

/**
 * Returns a ref that is true while the component is mounted.
 */
export const useMounted = () => {
    const mounted = useRef(true);
    useEffect(() => {
        mounted.current = true;
        return () => {
            mounted.current = false;
        };
    }, []);
    return mounted;
};

/**
 * Sequence guard against late responses: `const begin = useLatest();` then, per request,
 * `const current = begin();` and apply the response only when `current()` is still true
 * (no newer request was started in the meantime and the component is still mounted).
 */
export const useLatest = () => {
    const counter = useRef(0);
    const mounted = useMounted();
    return useCallback(() => {
        counter.current += 1;
        const id = counter.current;
        return () => mounted.current && id === counter.current;
    }, [mounted]);
};

/**
 * Loads data with `load()` (a function returning a promise) on mount and whenever `deps`
 * change. Returns {data, error, loading, reload, setData}. A failed reload keeps the previous
 * data; responses of superseded loads are ignored.
 */
export const useApiData = (load, deps = []) => {
    const [state, setState] = useState({ data: null, error: null, loading: true });
    const begin = useLatest();

    const reload = useCallback(() => {
        const current = begin();
        setState(prev => ({ ...prev, loading: true }));
        return load().then(
            data => {
                if (current()) {
                    setState({ data, error: null, loading: false });
                }
                return data;
            },
            error => {
                if (current()) {
                    setState(prev => ({ data: prev.data, error, loading: false }));
                }
                return null;
            },
        );
    // `load` changes on every render; `deps` says when it really changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, deps);

    useEffect(() => {
        reload();
    }, [reload]);

    const setData = useCallback(update => setState(prev => ({
        ...prev,
        data: typeof update === 'function' ? update(prev.data) : update,
    })), []);

    return { ...state, reload, setData };
};

/**
 * Calls `tick()` (may return a promise) every `interval` ms while `active` is true. The next
 * tick is scheduled after the previous one settled, so slow requests never overlap.
 * Pauses while the browser tab is hidden (docs/DESIGN.md section 8), except for two minutes
 * after `poke()` was called (call it on every user action); ticks immediately when the tab
 * becomes visible again.
 */
export const usePolling = (tick, interval, active = true) => {
    const tickRef = useRef(tick);
    tickRef.current = tick;
    const pokedAt = useRef(0);

    useEffect(() => {
        if (!active) {
            return undefined;
        }
        let timer = null;
        let stopped = false;
        let running = false;
        const schedule = () => {
            clearTimeout(timer);
            timer = setTimeout(run, interval);
        };
        const run = () => {
            if (stopped || running) {
                return;
            }
            if (document.hidden && Date.now() - pokedAt.current > POLL_GRACE_MS) {
                schedule();
                return;
            }
            running = true;
            Promise.resolve()
                .then(() => tickRef.current())
                .catch(() => null)
                .then(() => {
                    running = false;
                    if (!stopped) {
                        schedule();
                    }
                });
        };
        const onVisibility = () => {
            if (!document.hidden && !running) {
                clearTimeout(timer);
                run();
            }
        };
        schedule();
        document.addEventListener('visibilitychange', onVisibility);
        return () => {
            stopped = true;
            clearTimeout(timer);
            document.removeEventListener('visibilitychange', onVisibility);
        };
    }, [interval, active]);

    return useCallback(() => {
        pokedAt.current = Date.now();
    }, []);
};

/**
 * Query string parameter of the current page (e.g. site_id on the domain page).
 */
export const queryParam = name => new URLSearchParams(window.location.search).get(name);
