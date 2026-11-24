// Copyright 2026 Taiizor. Licensed under the MIT License.

import { expect, test } from 'bun:test';
import { stringify as reference } from 'qs';
import { stringify } from '../../src/frontend/lib/qs';

// The SDK's api.get() passes flat paging parameters; nested filters, arrays and special values
// keep the qs format anyway (extension.config.js aliases 'qs' to src/frontend/lib/qs.js).
const cases = [
    {},
    { pageSize: 25, pageNumber: 1 },
    { search: 'a b&c=d/é ü', flag: true, off: false, zero: 0 },
    { quote: "it's (ok)*!~-._" },
    { empty: '', missing: undefined, nothing: null },
    { filter: { search: 'x', state: ['running', 'stopped'] } },
    { list: [1, 2, 3], nested: [{ a: 1 }, { b: [true, null] }] },
    { when: new Date(Date.UTC(2026, 10, 24, 1, 2, 3)) },
    { 'key with spaces': 'v', 'brackets[]': 'w' },
    { deep: { a: { b: { c: 'd' } } }, emptyList: [], emptyObject: {} },
];

test('stringify matches qs.stringify with its defaults', () => {
    for (const value of cases) {
        expect(stringify(value)).toBe(reference(value));
    }
});

test('anything but an object gives an empty query', () => {
    for (const value of [null, undefined, 'text', 5]) {
        expect(stringify(value)).toBe('');
    }
});
