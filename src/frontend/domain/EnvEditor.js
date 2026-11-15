// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import { Button, Icon, Text } from '@plesk/plesk-ext-sdk';

const monospace = { fontFamily: 'Menlo, Consolas, "Liberation Mono", monospace', fontSize: '12px' };

/**
 * Parses raw .env string into an array of { id, key, val, show } rows.
 */
const parseEnvToRows = raw => {
    if (!raw || typeof raw !== 'string') return [{ id: 1, key: '', val: '', show: false }];
    const lines = raw.split(/\r?\n/);
    const rows = [];
    let nextId = 1;

    lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith('#')) return;
        const eqIdx = line.indexOf('=');
        if (eqIdx !== -1) {
            const key = line.slice(0, eqIdx).trim();
            let val = line.slice(eqIdx + 1);
            // Strip surrounding quotes if matching
            if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
                val = val.slice(1, -1);
            }
            rows.push({ id: nextId++, key, val, show: false });
        } else {
            rows.push({ id: nextId++, key: trimmed, val: '', show: false });
        }
    });

    return rows.length ? rows : [{ id: 1, key: '', val: '', show: false }];
};

/**
 * Serializes rows back to standard .env format.
 */
const serializeRowsToEnv = rows => {
    return rows
        .filter(r => r.key.trim() !== '')
        .map(r => {
            const k = r.key.trim();
            const v = r.val;
            // Wrap in quotes if it contains spaces or quotes
            if (v.includes(' ') || v.includes('\n') || v.includes('"')) {
                return `${k}="${v.replace(/"/g, '\\"')}"`;
            }
            return `${k}=${v}`;
        })
        .join('\n');
};

const EnvEditor = ({ value = '', onChange, disabled = false }) => {
    const [mode, setMode] = useState('table'); // 'table' | 'raw'
    const [rows, setRows] = useState(() => parseEnvToRows(value));

    // Sync from parent if value changes externally
    useEffect(() => {
        if (mode === 'table') {
            const currentSerialized = serializeRowsToEnv(rows);
            if (currentSerialized !== value) {
                setRows(parseEnvToRows(value));
            }
        }
    }, [value]); // eslint-disable-line react-hooks/exhaustive-deps

    const handleRowChange = (id, field, newVal) => {
        const next = rows.map(r => (r.id === id ? { ...r, [field]: newVal } : r));
        setRows(next);
        if (onChange) {
            onChange(serializeRowsToEnv(next));
        }
    };

    const handleAddRow = () => {
        const newId = rows.length ? Math.max(...rows.map(r => r.id)) + 1 : 1;
        const next = [...rows, { id: newId, key: '', val: '', show: true }];
        setRows(next);
    };

    const handleRemoveRow = id => {
        const next = rows.filter(r => r.id !== id);
        const finalRows = next.length ? next : [{ id: 1, key: '', val: '', show: false }];
        setRows(finalRows);
        if (onChange) {
            onChange(serializeRowsToEnv(finalRows));
        }
    };

    const handleSwitchMode = newMode => {
        if (newMode === 'raw') {
            if (onChange) onChange(serializeRowsToEnv(rows));
        } else {
            setRows(parseEnvToRows(value));
        }
        setMode(newMode);
    };

    return (
        <div style={{
            border: '1px solid var(--pul-color-border-subtle, #e5e7eb)',
            borderRadius: '6px',
            background: 'var(--pul-color-background-surface, #ffffff)',
            overflow: 'hidden',
            marginBottom: '12px',
        }}>
            {/* Header: Mode Switcher & Stats */}
            <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '8px 12px',
                background: 'var(--pul-color-background-subtle, #f9fafb)',
                borderBottom: '1px solid var(--pul-color-border-subtle, #e5e7eb)',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--pul-color-text-muted, #6b7280)' }}>
                    <span>{mode === 'table' ? `${rows.filter(r => r.key.trim()).length} variables` : 'Raw text'}</span>
                </div>
                <div style={{ display: 'flex', background: 'var(--pul-color-background-surface, #ffffff)', border: '1px solid var(--pul-color-border-subtle, #d1d5db)', borderRadius: '4px', overflow: 'hidden' }}>
                    <button
                        type="button"
                        onClick={() => handleSwitchMode('table')}
                        disabled={disabled}
                        style={{
                            border: 'none',
                            padding: '4px 10px',
                            fontSize: '11px',
                            fontWeight: mode === 'table' ? 600 : 400,
                            background: mode === 'table' ? 'var(--pul-color-primary, #0070f3)' : 'transparent',
                            color: mode === 'table' ? '#ffffff' : 'var(--pul-color-text-primary, #374151)',
                            cursor: disabled ? 'not-allowed' : 'pointer',
                        }}
                    >
                        Table
                    </button>
                    <button
                        type="button"
                        onClick={() => handleSwitchMode('raw')}
                        disabled={disabled}
                        style={{
                            border: 'none',
                            padding: '4px 10px',
                            fontSize: '11px',
                            fontWeight: mode === 'raw' ? 600 : 400,
                            background: mode === 'raw' ? 'var(--pul-color-primary, #0070f3)' : 'transparent',
                            color: mode === 'raw' ? '#ffffff' : 'var(--pul-color-text-primary, #374151)',
                            cursor: disabled ? 'not-allowed' : 'pointer',
                        }}
                    >
                        Raw .env
                    </button>
                </div>
            </div>

            {/* Body */}
            {mode === 'table' ? (
                <div style={{ padding: '10px 12px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                        {rows.map(row => (
                            <div key={row.id} style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                                <input
                                    type="text"
                                    value={row.key}
                                    placeholder="KEY"
                                    disabled={disabled}
                                    onChange={e => handleRowChange(row.id, 'key', e.target.value)}
                                    style={{
                                        ...monospace,
                                        flex: '1 1 35%',
                                        padding: '6px 8px',
                                        border: '1px solid var(--pul-color-border-subtle, #d1d5db)',
                                        borderRadius: '4px',
                                        color: 'var(--pul-color-text-primary, #111827)',
                                        background: 'var(--pul-color-background-surface, #ffffff)',
                                    }}
                                />
                                <span style={{ color: 'var(--pul-color-text-muted, #9ca3af)', fontWeight: 600 }}>=</span>
                                <div style={{ position: 'relative', flex: '1 1 55%', display: 'flex', alignItems: 'center' }}>
                                    <input
                                        type={row.show ? 'text' : 'password'}
                                        value={row.val}
                                        placeholder="value"
                                        disabled={disabled}
                                        onChange={e => handleRowChange(row.id, 'val', e.target.value)}
                                        style={{
                                            ...monospace,
                                            width: '100%',
                                            padding: '6px 30px 6px 8px',
                                            border: '1px solid var(--pul-color-border-subtle, #d1d5db)',
                                            borderRadius: '4px',
                                            color: 'var(--pul-color-text-primary, #111827)',
                                            background: 'var(--pul-color-background-surface, #ffffff)',
                                        }}
                                    />
                                    <button
                                        type="button"
                                        onClick={() => handleRowChange(row.id, 'show', !row.show)}
                                        title={row.show ? 'Hide value' : 'Show value'}
                                        style={{
                                            position: 'absolute',
                                            right: '6px',
                                            background: 'none',
                                            border: 'none',
                                            cursor: 'pointer',
                                            padding: '2px',
                                            color: 'var(--pul-color-text-muted, #6b7280)',
                                            display: 'flex',
                                            alignItems: 'center',
                                        }}
                                    >
                                        <Icon name={row.show ? 'eye-slash' : 'eye'} size="small" />
                                    </button>
                                </div>
                                <button
                                    type="button"
                                    onClick={() => handleRemoveRow(row.id)}
                                    disabled={disabled}
                                    title="Delete variable"
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        color: 'var(--pul-color-danger, #ef4444)',
                                        cursor: disabled ? 'not-allowed' : 'pointer',
                                        padding: '4px',
                                        display: 'flex',
                                        alignItems: 'center',
                                    }}
                                >
                                    <Icon name="trash" size="small" />
                                </button>
                            </div>
                        ))}
                    </div>
                    <div style={{ marginTop: '10px' }}>
                        <Button size="small" icon="plus" onClick={handleAddRow} disabled={disabled}>
                            Add Variable
                        </Button>
                    </div>
                </div>
            ) : (
                <div style={{ padding: '8px 12px' }}>
                    <textarea
                        value={value}
                        rows={6}
                        disabled={disabled}
                        placeholder="KEY=value&#10;PORT=3000"
                        onChange={e => onChange && onChange(e.target.value)}
                        style={{
                            ...monospace,
                            width: '100%',
                            boxSizing: 'border-box',
                            padding: '8px',
                            border: '1px solid var(--pul-color-border-subtle, #d1d5db)',
                            borderRadius: '4px',
                            color: 'var(--pul-color-text-primary, #111827)',
                            background: 'var(--pul-color-background-surface, #ffffff)',
                            resize: 'vertical',
                        }}
                    />
                </div>
            )}
        </div>
    );
};

EnvEditor.propTypes = {
    value: PropTypes.string,
    onChange: PropTypes.func,
    disabled: PropTypes.bool,
};

export default EnvEditor;
