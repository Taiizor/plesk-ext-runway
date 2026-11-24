// Copyright 2026 Taiizor. Licensed under the MIT License.

import { expect, test } from 'bun:test';
import { runtimeDomains } from '../../src/frontend/lib/toolchains';

test('the domains of a runtime come from inUse of api/toolchains', () => {
    const entry = { installed: [{ id: '1.27.4' }, { id: '1.26.9' }], inUse: { '1.27.4': ['gotest.local', 'a.example'], '1.26.9': ['a.example'] } };
    expect([...runtimeDomains(entry)].sort()).toEqual(['a.example', 'gotest.local']);
});

test('an unused runtime, a missing entry and malformed values give no domains', () => {
    expect(runtimeDomains({ installed: [{ id: '1.27.4' }], inUse: {} }).size).toBe(0);
    expect(runtimeDomains(undefined).size).toBe(0);
    expect(runtimeDomains({ installed: 'x', inUse: { a: 'b', c: [null, '', 5] } }).size).toBe(0);
});

test('domains listed on an installed entry count as well', () => {
    expect([...runtimeDomains({ installed: [{ id: 'x', domains: [{ name: 'b.example' }, 'c.example'] }] })].sort()).toEqual(['b.example', 'c.example']);
});
