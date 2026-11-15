// Copyright 2026 Taiizor. Licensed under the MIT License.

export const normalDocumentRoot = value => String(value || '').replace(/^[ /]+|[ /]+$/g, '');

/** A hosting change is explicit; an API without static files keeps Plesk's existing root. */
export const documentRootChange = (values, allowed, openedRoot) => (
    values.changeDocumentRoot && allowed && values.mode !== 'worker'
    && normalDocumentRoot(values.documentRoot) !== normalDocumentRoot(openedRoot)
);
