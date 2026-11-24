// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Input, Label, List, ListEmptyView, Panel, Paragraph, RouterLink, Select, SelectOption, Text,
    Toolbar, ToolbarExpander, Translate, withStatusMessages, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { helperText, isObject, isolate, jobTitle, runtimeName } from './lib/format';
import { runtimeDomains } from './lib/toolchains';
import { isBusy, POLL_BUSY_MS, POLL_IDLE_MS, useApi, useApiData, useLatest, usePolling } from './lib/hooks';
import ConfirmDialog from './components/ConfirmDialog';
import ErrorAlert from './components/ErrorAlert';
import JobPanel from './components/JobPanel';
import Mono from './components/Mono';
import ResponsiveTableStyle from './components/ResponsiveTableStyle';

const installedIds = entry => (Array.isArray(entry.installed) ? entry.installed.map(item => String(item.id)) : []);

// Channels can be updated in place (rust stable/beta/nightly, bun latest); the helper may also flag them.
const isChannel = item => item.channel === true
    || /^(stable|beta|nightly(-\d{4}-\d{2}-\d{2})?|latest|canary|lts|current)$/.test(String(item.id || ''));

const DEP_TOOLS_HINT = <Translate content="Toolchains.buildDepsHint" />;

/**
 * Install control of a managed runtime: version list from api/toolchains?runtime=<key>
 * (loaded when the tab is opened) plus a free-text field for versions or channels that are
 * not listed.
 */
const InstallControl = ({ meta, available = null, installed = [], busy = false, disabled = false, onInstall, onReload }) => {
    const [selected, setSelected] = useState('');
    const [custom, setCustom] = useState('');
    const translate = useTranslate();
    const list = (available && Array.isArray(available.list)) ? available.list : [];
    const fresh = list.filter(item => installed.indexOf(item.id) === -1);
    const fallback = (fresh[0] && fresh[0].id) || (list[0] && list[0].id) || '';
    const version = custom.trim() || selected || fallback;
    const chosen = list.filter(item => item.id === version)[0];
    const versionLabel = isolate(chosen ? (chosen.label || chosen.id) : version);
    return (
        <div>
            {available && available.error && (
                <Alert intent="warning">
                    <Translate content="Toolchains.releasesError" />
                    {': '}
                    {available.error}
                </Alert>
            )}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                <Select
                    value={selected || fallback}
                    onChange={setSelected}
                    disabled={!list.length || disabled}
                    placeholder={available && available.loading ? translate('Toolchains.loadingVersions') : translate('Toolchains.noVersions')}
                    style={{ minWidth: '220px' }}
                >
                    {list.map(item => (
                        <SelectOption key={item.id} value={item.id}>
                            {installed.indexOf(item.id) === -1 ? isolate(item.label || item.id) : translate('Toolchains.installedOption', { version: isolate(item.label || item.id) })}
                        </SelectOption>
                    ))}
                </Select>
                <Input
                    value={custom}
                    onChange={event => setCustom(event.target.value)}
                    placeholder={translate('Toolchains.otherVersion')}
                    disabled={disabled}
                    size="md"
                    autoCorrect="off"
                    autoCapitalize="none"
                    spellCheck="false"
                />
                <Button
                    intent="primary"
                    icon="arrow-down-tray"
                    disabled={!version || disabled}
                    state={busy ? 'loading' : undefined}
                    onClick={() => onInstall(version)}
                >
                    <Translate content="Toolchains.install" params={{ version: versionLabel || '' }} />
                </Button>
                <Button ghost icon="reload" onClick={onReload} state={available && available.loading ? 'loading' : undefined}>
                    <Translate content="Toolchains.reloadVersions" />
                </Button>
            </div>
            <div style={{ marginTop: '6px' }}>
                <Text fontSize="sm"><Translate content="Toolchains.otherVersionHint" params={{ runtime: runtimeName(translate, meta) }} /></Text>
            </div>
        </div>
    );
};

InstallControl.propTypes = {
    meta: PropTypes.object.isRequired,
    available: PropTypes.object,
    installed: PropTypes.arrayOf(PropTypes.string),
    busy: PropTypes.bool,
    disabled: PropTypes.bool,
    onInstall: PropTypes.func.isRequired,
    onReload: PropTypes.func.isRequired,
};

/**
 * Toolchains (administrators only): one tab per runtime with the installed versions and the
 * install control, the build dependencies, and the admin job with its live log.
 */
const Toolchains = ({ baseUrl, statusMessages }) => {
    const api = useApi(baseUrl);
    const translate = useTranslate();
    const context = useApiData(() => api.get('context'), [api]);
    const toolchains = useApiData(() => api.get('toolchains', { available: 0 }), [api]);
    const [active, setActive] = useState(null);
    const [available, setAvailable] = useState({});
    const [job, setJob] = useState(null);
    const [jobLog, setJobLog] = useState('');
    const [jobOpen, setJobOpen] = useState(false);
    const [pending, setPending] = useState(null);
    const [confirm, setConfirm] = useState(null);
    const beginJob = useLatest();
    const lastJobState = useRef(null);

    const runtimes = (context.data && Array.isArray(context.data.runtimes)) ? context.data.runtimes : [];
    const data = toolchains.data || {};
    const entries = isObject(data.runtimes) ? data.runtimes : {};
    const activeKey = active || (runtimes[0] && runtimes[0].key) || null;
    const jobBusy = isBusy(job);

    const toast = (intent, message) => statusMessages.add({ intent, message });

    const loadAvailable = (key, force) => {
        setAvailable(prev => ({ ...prev, [key]: { ...(prev[key] || {}), loading: true } }));
        return api.get('toolchains', { runtime: key, force: force ? 1 : undefined }).then(result => {
            const entry = result && result.runtimes && result.runtimes[key];
            setAvailable(prev => ({
                ...prev,
                [key]: { list: entry && Array.isArray(entry.available) ? entry.available : [], error: entry ? entry.availableError : null, loading: false },
            }));
        }, error => {
            setAvailable(prev => ({ ...prev, [key]: { list: (prev[key] && prev[key].list) || [], error: error.message, loading: false } }));
        });
    };

    const refreshJob = () => {
        const current = beginJob();
        return api.get('job', { job: 'admin', lines: 400 }).then(result => {
            if (current()) {
                setJob(result);
                setJobLog(result && typeof result.log === 'string' ? result.log : '');
            }
        }, () => null);
    };

    // The job of the initial page load; afterwards the job is polled on its own.
    useEffect(() => {
        if (data.job && job === null) {
            setJob(data.job);
            if (data.job.state && data.job.state !== 'none') {
                refreshJob();
            }
        }
    }, [data.job]); // eslint-disable-line react-hooks/exhaustive-deps

    // Version lists are slow (network): load them for the open tab only.
    useEffect(() => {
        const meta = runtimes.filter(item => item.key === activeKey)[0];
        if (meta && meta.toolchain !== 'none' && !available[activeKey]) {
            loadAvailable(activeKey, false);
        }
    }, [activeKey, runtimes.length]); // eslint-disable-line react-hooks/exhaustive-deps

    // A job that finishes refreshes the installed lists and tells the user.
    useEffect(() => {
        const state = job && job.state;
        const previous = lastJobState.current;
        lastJobState.current = state;
        if (previous && isBusy({ state: previous }) && state && !isBusy(job)) {
            toolchains.reload();
            refreshJob();
            if (state === 'succeeded') {
                toast('success', translate('Toolchains.jobDone', { title: jobTitle(translate, job) }));
            } else if (state === 'failed') {
                toast('danger', translate('Toolchains.jobFailed', { title: jobTitle(translate, job), message: job.message || '' }));
            }
        }
    }, [job && job.state]); // eslint-disable-line react-hooks/exhaustive-deps

    const poke = usePolling(refreshJob, jobBusy ? POLL_BUSY_MS : POLL_IDLE_MS, jobBusy);

    const startJob = (request, key) => {
        poke();
        setPending(key);
        return request.then(result => {
            setPending(null);
            if (result && result.message) {
                toast('info', result.message);
            }
            if (result && isObject(result.job)) {
                setJob(result.job);
            } else {
                setJob({ state: 'queued', title: '' });
            }
            setJobOpen(true);
            refreshJob();
        }, error => {
            setPending(null);
            toast('danger', error.message);
        });
    };

    const install = (runtime, version) => startJob(api.post('toolchain', { runtime, op: 'install', version }), `install-${runtime}`);
    const update = (runtime, version) => startJob(api.post('toolchain', { runtime, op: 'update', version }), `update-${runtime}-${version}`);
    const installBuildDeps = () => {
        setConfirm(null);
        startJob(api.post('build-deps', {}), 'build-deps');
    };
    const installIsolationDeps = () => {
        setConfirm(null);
        startJob(api.post('isolation-deps', {}), 'isolation-deps');
    };
    const remove = (runtime, version) => {
        poke();
        setPending(`remove-${runtime}-${version}`);
        api.post('toolchain', { runtime, op: 'remove', version }).then(result => {
            setPending(null);
            setConfirm(null);
            toast('success', (result && result.message) || translate('Toolchains.removed', { version }));
            toolchains.reload();
        }, error => {
            setPending(null);
            setConfirm(null);
            toast('danger', error.message);
        });
    };

    if (!toolchains.data || !context.data) {
        return <ErrorAlert error={toolchains.error || context.error} />;
    }

    const buildDeps = isObject(data.buildDeps) ? data.buildDeps : {};
    const missingDeps = Object.keys(buildDeps).filter(tool => !buildDeps[tool]);
    const isolationDeps = isObject(data.isolationDeps) ? data.isolationDeps : {};

    const removable = (meta, item) => (item.kind ? item.kind === 'managed' : meta.toolchain === 'managed');

    const renderInstalled = (meta, entry) => {
        const inUse = isObject(entry.inUse) ? entry.inUse : {};
        const columns = [
            {
                key: 'version',
                type: 'title',
                title: <Translate content="Toolchains.columnVersion" />,
                render: item => (
                    <div>
                        <Text bold>{isolate(item.label || item.id)}</Text>
                        {item.version && item.version !== item.id && <Text intent="muted">{` ${item.version}`}</Text>}
                    </div>
                ),
            },
            {
                key: 'path',
                title: <Translate content="Toolchains.columnPath" />,
                render: item => (item.path ? <Mono>{item.path}</Mono> : '—'),
            },
            {
                key: 'usedBy',
                title: <Translate content="Toolchains.columnUsedBy" />,
                render: item => {
                    const domains = Array.isArray(inUse[item.id]) ? inUse[item.id] : [];
                    return domains.length ? domains.join(', ') : <Text intent="muted"><Translate content="Toolchains.unused" /></Text>;
                },
            },
        ];
        const installedList = Array.isArray(entry.installed) ? entry.installed : [];
        if (installedList.some(item => removable(meta, item))) {
            columns.push({
                key: 'actions',
                type: 'actions',
                render: item => (removable(meta, item) ? (
                    <div style={{ display: 'flex', gap: '4px', justifyContent: 'flex-end' }}>
                        {isChannel(item) && (
                            <Button
                                ghost
                                icon="refresh"
                                disabled={jobBusy}
                                state={pending === `update-${meta.key}-${item.id}` ? 'loading' : undefined}
                                onClick={() => update(meta.key, item.id)}
                            >
                                <Translate content="Toolchains.update" />
                            </Button>
                        )}
                        <Button
                            ghost
                            icon="recycle"
                            disabled={jobBusy}
                            onClick={() => setConfirm({ type: 'remove', runtime: meta.key, version: item.id, label: item.label || item.id, domains: inUse[item.id] || [] })}
                        >
                            <Translate content="Toolchains.remove" />
                        </Button>
                    </div>
                ) : null),
            });
        }
        return (
            <List
                columns={columns}
                data={installedList}
                rowKey="id"
                vertical={720}
                emptyView={(
                    <ListEmptyView
                        title={meta.toolchain === 'detected' ? <Translate content="Toolchains.noneDetected" /> : <Translate content="Toolchains.noneInstalled" />}
                        description={helperText(translate, meta.hint_key, null, meta.hint) || null}
                    />
                )}
            />
        );
    };

    const renderTab = meta => {
        const entry = isObject(entries[meta.key]) ? entries[meta.key] : { installed: [], inUse: {} };
        const kind = meta.toolchain || entry.toolchainKind || 'none';
        const hint = helperText(translate, meta.hint_key, null, meta.hint);
        const installHelp = helperText(translate, meta.install_help_key, null, meta.install_help);
        return (
            <div style={{ paddingTop: '12px' }}>
                {hint && <Paragraph>{hint}</Paragraph>}
                {meta.docs_url && (
                    <Paragraph>
                        <a href={meta.docs_url} target="_blank" rel="noopener noreferrer">
                            <Translate content="Toolchains.docs" params={{ runtime: runtimeName(translate, meta) }} />
                        </a>
                    </Paragraph>
                )}
                {kind === 'none' ? (
                    <Alert intent="info"><Translate content="Toolchains.kindNone" /></Alert>
                ) : (
                    <Panel title={kind === 'detected' ? <Translate content="Toolchains.detected" /> : <Translate content="Toolchains.installed" />}>
                        {renderInstalled(meta, entry)}
                    </Panel>
                )}
                {kind === 'managed' && (
                    <Panel title={<Translate content="Toolchains.installTitle" params={{ runtime: runtimeName(translate, meta) }} />}>
                        {installHelp && <Alert intent="info">{installHelp}</Alert>}
                        <InstallControl
                            meta={meta}
                            available={available[meta.key] || null}
                            installed={installedIds(entry)}
                            busy={pending === `install-${meta.key}`}
                            disabled={jobBusy}
                            onInstall={version => install(meta.key, version)}
                            onReload={() => loadAvailable(meta.key, true)}
                        />
                        {jobBusy && <div style={{ marginTop: '8px' }}><Text intent="info"><Translate content="Toolchains.jobBusy" /></Text></div>}
                    </Panel>
                )}
                {kind === 'detected' && (
                    <Panel title={<Translate content="Toolchains.howToInstall" params={{ runtime: runtimeName(translate, meta) }} />}>
                        <Paragraph>{installHelp || <Translate content="Toolchains.detectedHelp" params={{ runtime: runtimeName(translate, meta) }} />}</Paragraph>
                    </Panel>
                )}
                {/* Also with an empty list when loading it failed: the error and Reload must stay reachable. */}
                {kind === 'detected' && available[meta.key]
                    && ((available[meta.key].list && available[meta.key].list.length > 0) || available[meta.key].error) && (
                    <Panel title={<Translate content="Toolchains.installExtraTitle" />}>
                        <InstallControl
                            meta={meta}
                            available={available[meta.key]}
                            installed={installedIds(entry)}
                            busy={pending === `install-${meta.key}`}
                            disabled={jobBusy}
                            onInstall={version => install(meta.key, version)}
                            onReload={() => loadAvailable(meta.key, true)}
                        />
                    </Panel>
                )}
            </div>
        );
    };

    const activeMeta = runtimes.find(meta => meta.key === activeKey) || runtimes[0] || null;

    return (
        <div>
            <ResponsiveTableStyle />
            <Toolbar style={{ flexWrap: 'wrap', gap: '8px' }}>
                <Button component={RouterLink} to="/overview" icon="arrow-left" ghost>
                    <Translate content="Common.backToOverview" />
                </Button>
                <ToolbarExpander />
                <Button
                    ghost
                    icon="reload"
                    state={toolchains.loading ? 'loading' : undefined}
                    onClick={() => {
                        toolchains.reload();
                        refreshJob();
                    }}
                >
                    <Translate content="Common.refresh" />
                </Button>
            </Toolbar>

            <JobPanel
                job={job}
                log={jobLog}
                title={<Translate content="Toolchains.jobTitle" />}
                collapsed={!jobBusy && !jobOpen}
                onToggle={collapsed => setJobOpen(!collapsed)}
            />

            {/* Visual Runtime Hub Cards Grid */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
                gap: '12px',
                marginTop: '16px',
                marginBottom: '20px',
            }}>
                {runtimes.map(meta => {
                    const isSelected = meta.key === activeKey;
                    const entry = isObject(data.runtimes) && isObject(data.runtimes[meta.key]) ? data.runtimes[meta.key] : {};
                    const instList = Array.isArray(entry.installed) ? entry.installed : [];
                    const allDomains = runtimeDomains(entry);
                    const count = instList.length;

                    return (
                        <div
                            key={meta.key}
                            data-runtime-card={meta.key}
                            role="button"
                            tabIndex={0}
                            onClick={() => setActive(meta.key)}
                            onKeyDown={e => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault();
                                    setActive(meta.key);
                                }
                            }}
                            style={{
                                background: isSelected ? 'var(--pul-color-background-surface, #ffffff)' : 'var(--pul-color-background-subtle, #f9fafb)',
                                border: isSelected ? '2px solid var(--pul-color-primary, #0070f3)' : '1px solid var(--pul-color-border-subtle, #e5e7eb)',
                                borderRadius: '8px',
                                padding: '14px',
                                cursor: 'pointer',
                                transition: 'all 0.15s ease',
                                boxShadow: isSelected ? '0 2px 8px rgba(0, 112, 243, 0.12)' : '0 1px 3px rgba(0,0,0,0.03)',
                                display: 'flex',
                                flexDirection: 'column',
                                justifyContent: 'space-between',
                            }}
                        >
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                                <span style={{ fontWeight: 700, fontSize: '15px', color: 'var(--pul-color-text-primary, #111827)' }}>
                                    {runtimeName(translate, meta)}
                                </span>
                                <span style={{
                                    fontSize: '11px',
                                    fontWeight: 600,
                                    padding: '2px 6px',
                                    borderRadius: '12px',
                                    background: count > 0 ? 'rgba(16, 185, 129, 0.1)' : 'var(--pul-color-background-subtle, #f3f4f6)',
                                    color: count > 0 ? '#10b981' : 'var(--pul-color-text-muted, #6b7280)',
                                }}>
                                    {count > 0 ? translate('Toolchains.cardInstalled', { count }) : translate('Toolchains.cardNone')}
                                </span>
                            </div>
                            <div style={{ fontSize: '12px', color: 'var(--pul-color-text-muted, #6b7280)' }}>
                                {allDomains.size === 0
                                    ? translate('Toolchains.noAppsUsing')
                                    : (allDomains.size === 1
                                        ? translate('Toolchains.activeAppOne')
                                        : translate('Toolchains.activeAppMany', { count: allDomains.size }))}
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Active Runtime Details */}
            {activeMeta && renderTab(activeMeta)}

            <Panel title={<Translate content="Toolchains.buildDeps" />}>
                <Paragraph>{DEP_TOOLS_HINT}</Paragraph>
                <Paragraph><Text intent="muted"><Translate content="Toolchains.dependencyPolicy" /></Text></Paragraph>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '12px' }}>
                    {Object.keys(buildDeps).map(tool => (
                        <Label key={tool} intent={buildDeps[tool] ? 'success' : 'warning'} view="light">
                            {tool}
                            {': '}
                            {buildDeps[tool] ? <Translate content="Toolchains.depFound" /> : <Translate content="Toolchains.depMissing" />}
                        </Label>
                    ))}
                </div>
                <Button
                    icon="tools"
                    intent={missingDeps.length ? 'primary' : undefined}
                    disabled={jobBusy}
                    state={pending === 'build-deps' ? 'loading' : undefined}
                    onClick={() => setConfirm({ type: 'build-deps' })}
                >
                    <Translate content="Toolchains.installBuildDeps" />
                </Button>
            </Panel>

            <Panel title={<Translate content="Toolchains.isolationDeps" />}>
                <Paragraph><Translate content="Toolchains.isolationDepsHint" /></Paragraph>
                <Paragraph><Text intent="muted"><Translate content="Toolchains.dependencyPolicy" /></Text></Paragraph>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '12px' }}>
                    <Label intent={isolationDeps.bubblewrap ? 'success' : 'warning'} view="light">
                        {'bubblewrap ≥ 0.10: '}
                        {isolationDeps.bubblewrap ? isolate(isolationDeps.version) : <Translate content="Toolchains.depMissing" />}
                    </Label>
                    <Label intent={isolationDeps.libseccomp ? 'success' : 'warning'} view="light">
                        {'libseccomp: '}
                        <Translate content={isolationDeps.libseccomp ? 'Toolchains.depFound' : 'Toolchains.depMissing'} />
                    </Label>
                </div>
                {isolationDeps.reason && <Paragraph><Text intent="muted">{isolationDeps.reason}</Text></Paragraph>}
                <Button icon="tools" intent={isolationDeps.available ? undefined : 'primary'}
                    disabled={jobBusy || pending === 'isolation-deps'}
                    state={pending === 'isolation-deps' ? 'loading' : undefined}
                    onClick={() => setConfirm({ type: 'isolation-deps' })}>
                    <Translate content="Toolchains.installIsolationDeps" />
                </Button>
            </Panel>

            <ConfirmDialog
                isOpen={Boolean(confirm && confirm.type === 'remove')}
                title={<Translate content="Toolchains.confirmRemoveTitle" />}
                intent="danger"
                confirmText={<Translate content="Toolchains.remove" />}
                busy={Boolean(confirm && pending === `remove-${confirm.runtime}-${confirm.version}`)}
                onConfirm={() => remove(confirm.runtime, confirm.version)}
                onClose={() => setConfirm(null)}
            >
                {confirm && confirm.type === 'remove' && (
                    <div>
                        <Paragraph><Translate content="Toolchains.confirmRemove" params={{ version: isolate(confirm.label) }} /></Paragraph>
                        {confirm.domains.length > 0 && (
                            <Alert intent="warning">
                                <Translate content="Toolchains.confirmRemoveInUse" params={{ domains: confirm.domains.join(', ') }} />
                            </Alert>
                        )}
                    </div>
                )}
            </ConfirmDialog>

            <ConfirmDialog
                isOpen={Boolean(confirm && confirm.type === 'build-deps')}
                title={<Translate content="Toolchains.installBuildDeps" />}
                confirmText={<Translate content="Toolchains.installBuildDepsConfirm" />}
                onConfirm={installBuildDeps}
                onClose={() => setConfirm(null)}
            >
                <Paragraph><Translate content="Toolchains.confirmBuildDeps" /></Paragraph>
            </ConfirmDialog>

            <ConfirmDialog
                isOpen={Boolean(confirm && confirm.type === 'isolation-deps')}
                title={<Translate content="Toolchains.installIsolationDeps" />}
                confirmText={<Translate content="Toolchains.installBuildDepsConfirm" />}
                onConfirm={installIsolationDeps}
                onClose={() => setConfirm(null)}>
                <Paragraph><Translate content="Toolchains.confirmIsolationDeps" /></Paragraph>
            </ConfirmDialog>
        </div>
    );
};

Toolchains.propTypes = {
    baseUrl: PropTypes.string.isRequired,
    statusMessages: PropTypes.object.isRequired,
};

export default withStatusMessages(Toolchains);
