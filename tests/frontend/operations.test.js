// Copyright 2026 Taiizor. Licensed under the MIT License.

import { expect, test } from 'bun:test';
import { documentRootChange } from '../../src/frontend/lib/documentRoot';
import { operationsBody, operationsValues, recoveryBundle } from '../../src/frontend/lib/operations';

test('document root changes require explicit opt-in and hosting permission', () => {
    const values = { mode: 'web', documentRoot: 'apps/api/wwwroot', changeDocumentRoot: false };
    expect(documentRootChange(values, true, 'httpdocs')).toBe(false);
    expect(documentRootChange({ ...values, changeDocumentRoot: true }, true, 'httpdocs')).toBe(true);
    expect(documentRootChange({ ...values, changeDocumentRoot: true }, false, 'httpdocs')).toBe(false);
    expect(documentRootChange({ ...values, changeDocumentRoot: true, mode: 'worker' }, true, 'httpdocs')).toBe(false);
    expect(documentRootChange({ ...values, changeDocumentRoot: true, documentRoot: ' /httpdocs/ ' }, true, 'httpdocs')).toBe(false);
});

test('operation form preserves disabled flags, converts paths and never resends the secret indicator', () => {
    const values = operationsValues({ history: false, releases: false, shared_paths: ['wwwroot'], exclude_paths: ['.git'],
        history_limit: 20, min_free_mb: 256, release_limit: 3, release_max_mb: 2048, has_notification_secret: true });
    const body = operationsBody({ ...values, shared_paths: 'wwwroot\r\nuploads\n', release_limit: '4' });
    expect(body.history).toBe(false);
    expect(body.releases).toBe(false);
    expect(body.shared_paths).toEqual(['wwwroot', 'uploads']);
    expect(body.exclude_paths).toEqual(['.git']);
    expect(body.release_limit).toBe(4);
    expect(body.notification_secret).toBe('');
    expect(body.has_notification_secret).toBeUndefined();
});

test('invalid numeric input reaches server validation without silent coercion', () => {
    const body = operationsBody({ history_limit: 'x', min_free_mb: '-1', release_limit: '2.5', release_max_mb: '100' });
    expect(body.history_limit).toBe('x');
    expect(body.min_free_mb).toBe('-1');
    expect(body.release_limit).toBe('2.5');
    expect(body.release_max_mb).toBe(100);
});

test('recovery parser rejects malformed, oversized and unsupported bundles', () => {
    const bundle = { schema: 1, application: { runtime: 'dotnet' }, operations: { backup: true } };
    expect(recoveryBundle(JSON.stringify(bundle))).toEqual(bundle);
    for (const input of ['{}', '{', 'null', JSON.stringify({ ...bundle, schema: 2 }), ' '.repeat(512 * 1024 + 1)]) {
        expect(() => recoveryBundle(input)).toThrow();
    }
});
