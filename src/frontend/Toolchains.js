// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Input, Label, List, ListEmptyView, Panel, Paragraph, RouterLink, Select, SelectOption, Tab, Tabs, Text,
    Toolbar, ToolbarExpander, Translate, withStatusMessages, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { helperText, isObject, jobTitle } from './lib/format';
import { isBusy, POLL_BUSY_MS, POLL_IDLE_MS, useApi, useApiData, useLatest, usePolling } from './lib/hooks';
import ConfirmDialog from './components/ConfirmDialog';
import ErrorAlert from './components/ErrorAlert';
import JobPanel from './components/JobPanel';
import Mono from './components/Mono';

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
const InstallControl = ({ meta, available, installed, busy, disabled, onInstall, onReload }) => {
    const [selected, setSelected] = useState('');
    const [custom, setCustom] = useState('');
    const translate = useTranslate();
    const list = (available && Array.isArray(available.list)) ? available.list : [];
    const fresh = list.filter(item => installed.indexOf(item.id) === -1);
    const fallback = (fresh[0] && fresh[0].id) || (list[0] && list[0].id) || '';
    const version = custom.trim() || selected || fallback;
    const chosen = list.filter(item => item.id === version)[0];
    const versionLabel = chosen ? (chosen.label || chosen.id) : version;
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
                            {installed.indexOf(item.id) === -1 ? (item.label || item.id) : translate('Toolchains.installedOption', { version: item.label || item.id })}
                        </SelectOption>
                    ))}
                </Select>
                <Input
                    value={custom}
                    onChange={event => setCustom(event.target.value)}
                    placeholder={translate('Toolchains.otherVersion')}
                    disabled={disabled}
                    size="md"
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
                <Text fontSize="sm"><Translate content="Toolchains.otherVersionHint" params={{ runtime: meta.label }} /></Text>
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

InstallControl.defaultProps = {
    available: null,
    installed: [],
    busy: false,
    disabled: false,
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
                        <Text bold>{item.label || item.id}</Text>
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
                            <Translate content="Toolchains.docs" params={{ runtime: meta.label }} />
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
                    <Panel title={<Translate content="Toolchains.installTitle" params={{ runtime: meta.label }} />}>
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
                    <Panel title={<Translate content="Toolchains.howToInstall" params={{ runtime: meta.label }} />}>
                        <Paragraph>{installHelp || <Translate content="Toolchains.detectedHelp" params={{ runtime: meta.label }} />}</Paragraph>
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

    const activeIndex = Math.max(0, runtimes.findIndex(meta => meta.key === activeKey));

    return (
        <div>
            <Toolbar>
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

            <Tabs active={activeIndex + 1}>
                {runtimes.map(meta => {
                    return (
                        <Tab key={meta.key} title={meta.label} onActivate={() => setActive(meta.key)}>
                            {renderTab(meta)}
                        </Tab>
                    );
                })}
            </Tabs>

            <Panel title={<Translate content="Toolchains.buildDeps" />}>
                <Paragraph>{DEP_TOOLS_HINT}</Paragraph>
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
                        <Paragraph><Translate content="Toolchains.confirmRemove" params={{ version: confirm.label }} /></Paragraph>
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
        </div>
    );
};

Toolchains.propTypes = {
    baseUrl: PropTypes.string.isRequired,
    statusMessages: PropTypes.object.isRequired,
};

export default withStatusMessages(Toolchains);
