// Copyright 2026 Taiizor. Licensed under the MIT License.

const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);

/**
 * The domains that use any installed version of a runtime, for the cards of the Toolchains page.
 * api/toolchains reports the usage per version id in `inUse` ({"1.27.4": ["example.com"]}); an
 * installed entry may also carry its own `domains` list.
 */
export const runtimeDomains = entry => {
    const domains = new Set();
    const add = list => (Array.isArray(list) ? list : []).forEach(d => {
        const name = isObject(d) ? d.name : d;
        if (typeof name === 'string' && name !== '') {
            domains.add(name);
        }
    });
    if (isObject(entry)) {
        if (isObject(entry.inUse)) {
            Object.keys(entry.inUse).forEach(version => add(entry.inUse[version]));
        }
        (Array.isArray(entry.installed) ? entry.installed : []).forEach(item => add(isObject(item) ? item.domains : null));
    }
    return domains;
};
