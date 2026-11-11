// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';
import { Button, Checkbox, Panel, Tab, Tabs, Text, Translate } from '@plesk/plesk-ext-sdk';
import LogOutput from '../components/LogOutput';

const KINDS = ['app', 'deploy'];

/**
 * Logs card: application log (journal) and build/deploy log in tabs, refreshed with the
 * status polling while "Auto-refresh" is on.
 */
const LogsPanel = ({ kind, text, error, loading, autoRefresh, onKind, onAutoRefresh, onRefresh }) => {
    const body = (
        <div style={{ paddingTop: '12px' }}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', marginBottom: '8px' }}>
                <Checkbox checked={autoRefresh} onChange={onAutoRefresh}>
                    <Translate content="Domain.logs.autoRefresh" />
                </Checkbox>
                <Button ghost icon="reload" state={loading ? 'loading' : undefined} onClick={onRefresh}>
                    <Translate content="Common.refresh" />
                </Button>
                {error && <Text intent="danger">{error}</Text>}
            </div>
            <LogOutput text={text} />
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
    onKind: PropTypes.func.isRequired,
    onAutoRefresh: PropTypes.func.isRequired,
    onRefresh: PropTypes.func.isRequired,
};

LogsPanel.defaultProps = {
    text: '',
    error: null,
    loading: false,
    autoRefresh: true,
};

export default LogsPanel;
