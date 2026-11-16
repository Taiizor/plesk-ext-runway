// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { Button, Checkbox, Panel, Tab, Tabs, Text, Translate, useTranslate } from '@plesk/plesk-ext-sdk';
import LogOutput from '../components/LogOutput';

const KINDS = ['app', 'deploy'];

/**
 * Logs card: application log (journal) and build/deploy log in tabs, refreshed with the
 * status polling while "Auto-refresh" is on, plus filter and download.
 */
const LogsPanel = ({
    kind, text = '', error = null, loading = false, autoRefresh = true, switchable = false, onKind, onAutoRefresh, onRefresh,
}) => {
    const translate = useTranslate();
    const [filter, setFilter] = useState('');

    const filteredText = useMemo(() => {
        if (!filter.trim()) return text;
        const lower = filter.toLowerCase();
        return text.split('\n').filter(line => line.toLowerCase().includes(lower)).join('\n');
    }, [text, filter]);

    const downloadLog = () => {
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${kind}-log.txt`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    const body = (
        <div style={{ paddingTop: '12px' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
                    <Checkbox checked={autoRefresh} onChange={onAutoRefresh}>
                        <Translate content="Domain.logs.autoRefresh" />
                    </Checkbox>
                    <Button ghost icon="reload" state={loading ? 'loading' : undefined} onClick={onRefresh}>
                        <Translate content="Common.refresh" />
                    </Button>
                    <Button ghost icon="download" disabled={!text} onClick={downloadLog}>
                        {translate('Domain.project.fetchSubmit')} (.log)
                    </Button>
                    {error && <Text intent="danger">{error}</Text>}
                </div>

                <div style={{ minWidth: '220px' }}>
                    <input
                        type="text"
                        value={filter}
                        onChange={e => setFilter(e.target.value)}
                        placeholder={translate('Domain.logs.filterPlaceholder')}
                        style={{
                            width: '100%',
                            boxSizing: 'border-box',
                            padding: '4px 8px',
                            fontSize: '12px',
                            border: '1px solid var(--pul-color-border-subtle, #d1d5db)',
                            borderRadius: '4px',
                            background: 'var(--pul-color-background-surface, #ffffff)',
                            color: 'var(--pul-color-text-primary, #111827)',
                        }}
                    />
                </div>
            </div>
            {kind === 'app' && switchable && (
                // Zero-downtime slots: both versions write into the application log.
                <div style={{ marginBottom: '8px' }}><Text intent="muted" fontSize="sm"><Translate content="Domain.logs.slotsHint" /></Text></div>
            )}
            <LogOutput text={filteredText} />
        </div>
    );
    return (
        <Panel title={<Translate content="Domain.logs.title" />}>
            <Tabs active={KINDS.indexOf(kind) + 1}>
                <Tab title={<Translate content="Domain.log_app" />} onActivate={() => onKind('app')}>
                    {kind === 'app' ? body : null}
                </Tab>
                <Tab title={<Translate content="Domain.log_deploy" />} onActivate={() => onKind('deploy')}>
                    {kind === 'deploy' ? body : null}
                </Tab>
            </Tabs>
        </Panel>
    );
};

LogsPanel.propTypes = {
    kind: PropTypes.oneOf(KINDS).isRequired,
    text: PropTypes.string,
    error: PropTypes.string,
    loading: PropTypes.bool,
    autoRefresh: PropTypes.bool,
    switchable: PropTypes.bool,
    onKind: PropTypes.func.isRequired,
    onAutoRefresh: PropTypes.func.isRequired,
    onRefresh: PropTypes.func.isRequired,
};

export default LogsPanel;
