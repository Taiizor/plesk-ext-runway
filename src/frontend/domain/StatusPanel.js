// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';
import { Alert, Button, Label, Panel, Text, Translate, useTranslate } from '@plesk/plesk-ext-sdk';
import { appState, formatBytes, formatTime, helperText, isObject, isolate, jobTitle } from '../lib/format';
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

// Phases of a zero-downtime switch (helper job status "phase", docs/DESIGN.md section 12.4).
// i18n-keys: Domain.status.switchPhase.prepare Domain.status.switchPhase.starting Domain.status.switchPhase.waiting
// i18n-keys: Domain.status.switchPhase.switching Domain.status.switchPhase.draining Domain.status.switchPhase.stopping
const PHASES = ['prepare', 'starting', 'waiting', 'switching', 'draining', 'stopping'];

/** Name of an instance: "slot a", or the classic unit (slot "") of the setting off. */
const slotName = slot => (slot
    ? <Translate content="Domain.status.slotName" params={{ slot: isolate(slot) }} />
    : <Translate content="Domain.status.slotClassic" />);

/** "Zero-downtime" fact: on (live slot and the time of the last switch), pending, or turning off. */
const zeroDowntimeValue = current => {
    if (!current.zero_downtime && !current.slot) {
        return null;
    }
    let text;
    if (!current.zero_downtime) {
        text = <Translate content="Domain.status.zeroDowntimeOffPending" params={{ slot: isolate(current.slot) }} />;
    } else if (!current.slot) {
        text = <Translate content="Domain.status.zeroDowntimePending" />;
    } else if (current.switched_at) {
        text = <Translate content="Domain.status.zeroDowntimeOn" params={{ slot: isolate(current.slot), time: formatTime(current.switched_at) }} />;
    } else {
        text = <Translate content="Domain.status.zeroDowntimeOnSlot" params={{ slot: isolate(current.slot) }} />;
    }
    const standby = current.standby_listener === 'foreign' && isObject(current.standby_params) ? current.standby_params : null;
    return (
        <span>
            {text}
            {standby ? (
                <div>
                    <Text intent="warning" fontSize="sm">
                        <Translate content="Domain.status.standbyForeign" params={{ port: isolate(String(standby.port)), uids: isolate(String(standby.uids)) }} />
                    </Text>
                </div>
            ) : null}
        </span>
    );
};

/** Progress of a running switch: "to slot a: waiting for the new version, 12 s of 60 s". */
const switchValue = (translate, deploy, deploying) => {
    if (!deploying || !deploy || PHASES.indexOf(deploy.phase) === -1) {
        return null;
    }
    const target = deploy.slot_to
        ? translate('Domain.status.slotName', { slot: isolate(deploy.slot_to) })
        : translate('Domain.status.slotClassic');
    const phase = translate(`Domain.status.switchPhase.${deploy.phase}`);
    const limit = Number(deploy.phase_limit) || 0;
    return limit
        ? translate('Domain.status.switchProgress', { target, phase, elapsed: String(Number(deploy.phase_elapsed) || 0), limit: String(limit) })
        : translate('Domain.status.switchProgressNoLimit', { target, phase });
};

// From this size on, and when it is at least the application's own memory, the file cache gets
// a hint about static paths (docs/DESIGN.md section 8; the memory fields: section 7).
const LARGE_CACHE = 256 * 1024 * 1024;
const MIB = 1024 * 1024;

/** The application's own memory (helper memory_used_bytes), else systemd's MemoryCurrent. */
const usedMemory = info => (
    isObject(info) && typeof info.memory_used_bytes === 'number' ? info.memory_used_bytes : (isObject(info) ? info.memory_bytes : null)
);

/**
 * "Memory" fact: the application's own memory (mapped files included), the kernel's unmapped
 * file cache charged to its service as secondary text, and for web applications whose cache is
 * large a hint to let the web server serve big files (static paths, from the document root).
 */
const memoryValue = (service, worker, documentRoot) => {
    const used = usedMemory(service);
    const text = formatBytes(used);
    if (!text) {
        return null;
    }
    const cache = typeof service.memory_cache_bytes === 'number' ? service.memory_cache_bytes : 0;
    const large = !worker && cache >= LARGE_CACHE && cache >= used;
    return (
        <span>
            {text}
            {cache >= MIB ? (
                <Text intent="muted" fontSize="sm">
                    {' '}
                    <Translate content="Domain.status.memoryCache" params={{ size: isolate(formatBytes(cache)) }} />
                </Text>
            ) : null}
            {large ? (
                <div>
                    <Text intent="muted" fontSize="sm">
                        <Translate content="Domain.status.memoryCacheHint" params={{ path: isolate(documentRoot || 'httpdocs') }} />
                    </Text>
                </div>
            ) : null}
        </span>
    );
};

/** The instances that run right now (both during a switch), with their state and memory. */
const versionsValue = current => {
    const slots = isObject(current.slots) ? current.slots : null;
    if (!slots) {
        return null;
    }
    const running = Object.keys(slots).filter(key => isObject(slots[key]) && ['active', 'activating', 'deactivating'].indexOf(slots[key].active_state) !== -1);
    if (!running.length) {
        return null;
    }
    return (
        <span>
            {running.map(key => (
                <div key={key || 'classic'}>
                    {slotName(key)}
                    {': '}
                    {slots[key].active_state}
                    {usedMemory(slots[key]) ? `, ${formatBytes(usedMemory(slots[key]))}` : ''}
                    {slots[key].live ? <Text intent="muted" fontSize="sm">{' '}<Translate content="Domain.status.versionLive" /></Text> : null}
                </div>
            ))}
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
    // Zero-downtime slots: Restart switches to a new instance; "Restart in place" restarts the running one.
    const switchable = Boolean(current.switchable);

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
        {
            key: 'memory',
            label: <Translate content="Domain.status.memory" />,
            value: running ? memoryValue(service, worker, isObject(data.domain) ? data.domain.documentRoot : null) : null,
        },
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
        { key: 'zeroDowntime', label: <Translate content="Domain.status.zeroDowntime" />, value: worker ? null : zeroDowntimeValue(current) },
        { key: 'switch', label: <Translate content="Domain.status.switch" />, value: switchValue(translate, deploy, deploying) },
        { key: 'versions', label: <Translate content="Domain.status.versions" />, value: switchable ? versionsValue(current) : null },
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
                    {switchable && (
                        <Button
                            icon="reload"
                            disabled={!enabled || deploying || Boolean(busyOp)}
                            state={busyOp === 'restartPlain' ? 'loading' : undefined}
                            onClick={() => onControl('restartPlain')}
                        >
                            <Translate content="Domain.actions.restartPlain" />
                        </Button>
                    )}
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
