// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';
import { Alert, Button, Label, Panel, Text, Translate, useTranslate } from '@plesk/plesk-ext-sdk';
import { appState, formatBytes, formatTime, helperText, isObject, jobTitle } from '../lib/format';
import { isBusy } from '../lib/hooks';
import Facts from '../components/Facts';
import Mono from '../components/Mono';
import { JobLabel, StateLabel } from '../components/StateLabel';

const LISTENER_TEXT = {
    ok: <Translate content="Domain.status.listenerOk" />,
    none: <Translate content="Domain.status.listenerNone" />,
    foreign: <Translate content="Domain.status.listenerForeign" />,
    tampered: <Translate content="Domain.status.listenerTampered" />,
};

const HEALTH = {
    healthy: { intent: 'success', text: <Translate content="Domain.status.healthHealthy" /> },
    unhealthy: { intent: 'danger', text: <Translate content="Domain.status.healthUnhealthy" /> },
    unknown: { intent: 'inactive', text: <Translate content="Domain.status.healthUnknown" /> },
};

// The helper reports listener_code / health_code with params next to its English detail text.
// i18n-keys: Domain.status.listenerDetail.ok Domain.status.listenerDetail.none Domain.status.listenerDetail.foreign
// i18n-keys: Domain.status.listenerDetail.tampered Domain.status.listenerDetail.socket_symlink
// i18n-keys: Domain.status.listenerDetail.socket_not_socket Domain.status.listenerDetail.socket_owner Domain.status.listenerDetail.worker
// i18n-keys: Domain.status.healthDetail.no_path Domain.status.healthDetail.not_listening Domain.status.healthDetail.failed
// i18n-keys: Domain.status.healthDetail.no_http Domain.status.healthDetail.http
const detailText = (translate, prefix, code, params, fallback) => (
    code ? helperText(translate, `${prefix}.${code}`, params, fallback) : (fallback || '')
);

/** The application's URL: api/app's appUrl (https when the domain has SSL/TLS, mount path in path mode). */
const siteUrl = (data, config) => {
    if (typeof data.appUrl === 'string' && data.appUrl) {
        return data.appUrl;
    }
    const name = data.domain && data.domain.name;
    if (!name) {
        return null;
    }
    const path = config.mode === 'path' && config.mountPath ? `${config.mountPath}/` : '/';
    return `http://${name}${path}`;
};

const Steps = () => (
    <ol style={{ margin: '0 0 12px 18px', padding: 0, lineHeight: 1.7 }}>
        <li><Translate content="Domain.intro.step1" /></li>
        <li><Translate content="Domain.intro.step2" /></li>
        <li><Translate content="Domain.intro.step3" /></li>
        <li><Translate content="Domain.intro.step4" /></li>
    </ol>
);

const listenerValue = (translate, current, running, worker) => {
    if (worker || typeof current.listener !== 'string' || (!running && current.listener !== 'tampered')) {
        return null;
    }
    const detail = current.listener !== 'ok'
        ? detailText(translate, 'Domain.status.listenerDetail', current.listener_code, current.listener_params, current.listener_detail)
        : '';
    return (
        <span>
            <Label intent={current.listener === 'ok' ? 'success' : 'danger'} view="light">
                {LISTENER_TEXT[current.listener] || current.listener}
            </Label>
            {detail ? <Text fontSize="sm">{' '}{detail}</Text> : null}
        </span>
    );
};

const deployValue = (translate, deploy, deploying) => {
    if (!deploy || !deploy.state || deploy.state === 'none') {
        return null;
    }
    return (
        <span>
            <JobLabel state={deploy.state} />
            {' '}
            {jobTitle(translate, deploy)}
            {deploy.finished_at && !deploying ? <Text fontSize="sm">{` ${formatTime(deploy.finished_at)}`}</Text> : null}
            {deploy.state === 'failed' && deploy.message ? <div><Text intent="danger" fontSize="sm">{deploy.message}</Text></div> : null}
        </span>
    );
};

/**
 * Status card of the domain page: state label, facts about the service, the listener, the
 * health check and the last deployment, and the control buttons.
 */
const StatusPanel = ({ data, status, busyOp, onControl, onStop }) => {
    const translate = useTranslate();
    const config = isObject(data.config) ? data.config : {};
    const configured = Boolean(data.configured);
    const current = isObject(status) ? status : {};
    const service = isObject(current.service) ? current.service : {};
    const deploy = isObject(current.deploy) ? current.deploy : null;
    const state = appState(current, configured);
    const deploying = isBusy(deploy);
    const enabled = configured && current.enabled !== false && config.enabled !== false;
    const running = state === 'running' || state === 'starting';
    const worker = config.mode === 'worker' || config.listen === 'none';
    const health = typeof current.health === 'string' ? HEALTH[current.health] : null;
    const healthDetail = health
        ? detailText(translate, 'Domain.status.healthDetail', current.health_code, current.health_params, current.health_detail)
        : '';
    const url = siteUrl(data, config);
    const watcher = isObject(current.watcher) ? current.watcher : {};

    let endpoint = null;
    if (worker) {
        endpoint = <Translate content="Domain.status.endpointWorker" />;
    } else if (current.socket || current.listen_mode === 'unix' || config.listen === 'unix') {
        endpoint = current.socket ? <Mono>{current.socket}</Mono> : <Translate content="Domain.status.endpointSocket" />;
    } else if (current.port || config.port) {
        endpoint = <Mono>{`127.0.0.1:${current.port || config.port}`}</Mono>;
    }

    let triggers = null;
    if (watcher.active_state) {
        triggers = watcher.active_state === 'active'
            ? <Translate content="Domain.status.triggersOn" />
            : <Translate content="Domain.status.triggersOff" />;
    }

    const rows = [
        {
            key: 'service',
            label: <Translate content="Domain.status.service" />,
            value: service.active_state ? `${service.active_state}${service.sub_state ? ` (${service.sub_state})` : ''}` : null,
        },
        { key: 'pid', label: <Translate content="Domain.status.pid" />, value: running && service.main_pid ? String(service.main_pid) : null },
        { key: 'memory', label: <Translate content="Domain.status.memory" />, value: running ? formatBytes(service.memory_bytes) : null },
        { key: 'started', label: <Translate content="Domain.status.started" />, value: running ? formatTime(service.started_iso || service.started_at) : null },
        { key: 'restarts', label: <Translate content="Domain.status.restarts" />, value: service.restarts ? String(service.restarts) : null },
        { key: 'endpoint', label: <Translate content="Domain.status.endpoint" />, value: endpoint },
        { key: 'listener', label: <Translate content="Domain.status.listener" />, value: listenerValue(translate, current, running, worker) },
        {
            key: 'health',
            label: <Translate content="Domain.status.health" />,
            value: health ? (
                <span>
                    <Label intent={health.intent} view="light">{health.text}</Label>
                    {healthDetail ? <Text fontSize="sm">{' '}{healthDetail}</Text> : null}
                </span>
            ) : null,
        },
        { key: 'deploy', label: <Translate content="Domain.status.deploy" />, value: deployValue(translate, deploy, deploying) },
        { key: 'triggers', label: <Translate content="Domain.status.triggers" />, value: triggers },
    ];

    return (
        <Panel title={<Translate content="Domain.status.title" />}>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', marginBottom: '12px' }}>
                <StateLabel state={state} size="lg" />
                {deploying && <Label intent="info" size="lg" view="light"><Translate content="Domain.status.deploying" /></Label>}
                {configured && url && !worker && (
                    // marginInlineStart: the far end of the row in left-to-right and right-to-left
                    // panel languages (Arabic, Hebrew).
                    <a href={url} target="_blank" rel="noopener noreferrer" style={{ marginInlineStart: 'auto' }}>
                        <Translate content="Domain.status.openSite" />
                    </a>
                )}
            </div>
            {state === 'tampered' && (
                <Alert intent="danger">
                    <Translate content="Domain.status.tamperedHint" />
                    {current.tampered_detail ? <div><Mono>{current.tampered_detail}</Mono></div> : null}
                </Alert>
            )}
            {configured ? <Facts rows={rows} hideEmpty /> : <Steps />}
            {configured && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    <Button
                        icon="start"
                        disabled={!enabled || running || deploying || Boolean(busyOp)}
                        state={busyOp === 'start' ? 'loading' : undefined}
                        onClick={() => onControl('start')}
                    >
                        <Translate content="Domain.actions.start" />
                    </Button>
                    <Button
                        icon="stop"
                        disabled={!enabled || !running || Boolean(busyOp)}
                        state={busyOp === 'stop' ? 'loading' : undefined}
                        onClick={onStop}
                    >
                        <Translate content="Domain.actions.stop" />
                    </Button>
                    <Button
                        icon="reload"
                        disabled={!enabled || deploying || Boolean(busyOp)}
                        state={busyOp === 'restart' ? 'loading' : undefined}
                        onClick={() => onControl('restart')}
                    >
                        <Translate content="Domain.actions.restart" />
                    </Button>
                    <Button
                        intent="primary"
                        icon="deploy"
                        disabled={!enabled || deploying || Boolean(busyOp)}
                        state={busyOp === 'deploy' || deploying ? 'loading' : undefined}
                        onClick={() => onControl('deploy')}
                    >
                        <Translate content="Domain.actions.deploy" />
                    </Button>
                </div>
            )}
            {configured && enabled && deploying && (
                <div style={{ marginTop: '8px' }}><Text intent="muted"><Translate content="Domain.status.deployingHint" /></Text></div>
            )}
            {configured && enabled && !deploying && state === 'stopped' && current.stopped && (
                <div style={{ marginTop: '8px' }}><Text intent="warning"><Translate content="Domain.status.stoppedHint" /></Text></div>
            )}
            {configured && !enabled && (
                <div style={{ marginTop: '8px' }}><Text intent="warning"><Translate content="Domain.status.disabledHint" /></Text></div>
            )}
        </Panel>
    );
};

StatusPanel.propTypes = {
    data: PropTypes.object.isRequired,
    status: PropTypes.object,
    busyOp: PropTypes.string,
    onControl: PropTypes.func.isRequired,
    onStop: PropTypes.func.isRequired,
};

StatusPanel.defaultProps = {
    status: null,
    busyOp: null,
};

export default StatusPanel;
