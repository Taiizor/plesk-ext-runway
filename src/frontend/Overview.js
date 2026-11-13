// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Label, List, ListEmptyView, Panel, RouterLink, Text, Toolbar, ToolbarExpander, Translate, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { formatBytes, formatTime, isolate, runtimeName } from './lib/format';
import { useApi, useApiData, usePolling } from './lib/hooks';
import ErrorAlert from './components/ErrorAlert';
import Facts from './components/Facts';
import { StateLabel } from './components/StateLabel';
import UpdateNotice from './components/UpdateNotice';

const OVERVIEW_POLL_MS = 15000;

const domainLink = row => `/domain?site_id=${encodeURIComponent(row.domainId)}`;

const Steps = ({ isAdmin }) => (
    <ol style={{ margin: '0 0 0 18px', padding: 0, lineHeight: 1.7 }}>
        <li>{isAdmin ? <Translate content="Overview.emptyStep1" /> : <Translate content="Overview.emptyStep1Customer" />}</li>
        <li><Translate content="Overview.emptyStep2" /></li>
        <li><Translate content="Overview.emptyStep3" /></li>
    </ol>
);

Steps.propTypes = {
    isAdmin: PropTypes.bool,
};

Steps.defaultProps = {
    isAdmin: false,
};

const endpoint = row => {
    if (!row.configured) {
        return null;
    }
    if (row.listen === 'none' || row.mode === 'worker') {
        return <Translate content="Overview.endpointWorker" />;
    }
    const target = row.listen === 'unix' ? <Translate content="Overview.endpointSocket" /> : (row.port ? `127.0.0.1:${row.port}` : null);
    if (row.mode === 'path') {
        return <span>{target} <Text intent="muted"><Translate content="Overview.endpointPath" /></Text></span>;
    }
    return target;
};

/**
 * Memory of a running application: its own memory (memoryUsedBytes, else systemd's
 * MemoryCurrent), with the kernel's file cache charged to its service below it.
 */
const memoryCell = row => {
    if (row.state !== 'running') {
        return null;
    }
    const text = formatBytes(typeof row.memoryUsedBytes === 'number' ? row.memoryUsedBytes : row.memoryBytes);
    if (!text) {
        return null;
    }
    const cache = typeof row.memoryCacheBytes === 'number' && row.memoryCacheBytes >= 1024 * 1024 ? formatBytes(row.memoryCacheBytes) : null;
    return (
        <span>
            {text}
            {cache ? (
                <div>
                    <Text intent="muted" fontSize="sm"><Translate content="Overview.memoryCache" params={{ size: isolate(cache) }} /></Text>
                </div>
            ) : null}
        </span>
    );
};

/**
 * "Last update check" of the server panel: time (or "never"), the result or the error of the
 * check, and "Check now" (a forced check; the helper answers from its cache within a minute).
 */
const updateFact = (info, checking, checkError, checkNow) => {
    let result = null;
    if (checkError || info.error) {
        result = <Text intent="danger" fontSize="sm">{checkError || info.error}</Text>;
    } else if (info.checkedAt) {
        if (info.available && info.latest) {
            result = <Label intent="info" view="light"><Translate content="Overview.updateFound" params={{ version: isolate(info.latest.full) }} /></Label>;
        } else if (info.latest) {
            result = <Text intent="muted" fontSize="sm"><Translate content="Overview.updateCurrent" /></Text>;
        } else {
            result = <Text intent="muted" fontSize="sm"><Translate content="Overview.updateNoRelease" /></Text>;
        }
    }
    return (
        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
            <span>{info.checkedAt ? formatTime(info.checkedAt) : <Translate content="Overview.updateNever" />}</span>
            {result}
            <Button ghost icon="reload" state={checking ? 'loading' : undefined} onClick={checkNow}>
                <Translate content="Overview.checkNow" />
            </Button>
        </span>
    );
};

/**
 * Start page: every domain (with hosting) the user may manage, with the state of its
 * application; administrators also see the server facts and links to Toolchains/Settings.
 */
const Overview = ({ baseUrl }) => {
    const api = useApi(baseUrl);
    const translate = useTranslate();
    const context = useApiData(() => api.get('context'), [api]);
    const overview = useApiData(() => api.get('overview'), [api]);

    const isAdmin = Boolean(context.data && context.data.isAdmin);
    // Built-in updater (administrators): the last check, without network access on page load.
    // It is reloaded with the overview (update-status reads only local files), so an admin job
    // that ends, or a self-update started elsewhere, shows up without a page reload.
    const update = useApiData(() => (isAdmin ? api.get('update') : Promise.resolve(null)), [api, isAdmin]);
    usePolling(() => Promise.all([overview.reload(), isAdmin ? update.reload() : null]), OVERVIEW_POLL_MS, Boolean(overview.data));
    const [checking, setChecking] = useState(false);
    const [checkError, setCheckError] = useState(null);
    const checkNow = () => {
        setChecking(true);
        setCheckError(null);
        api.post('update/check', {}).then(result => {
            setChecking(false);
            update.setData(result);
            // Supersedes a poll that was sent before the check finished (it would show the old state).
            update.reload();
        }, error => {
            setChecking(false);
            setCheckError(error.message);
        });
    };
    const updateInfo = update.data || null;
    const runtimes = {};
    ((context.data && context.data.runtimes) || []).forEach(meta => {
        runtimes[meta.key] = meta;
    });
    const data = overview.data || {};
    const apps = Array.isArray(data.apps) ? data.apps : [];
    const configured = apps.filter(row => row.configured).length;
    const server = data.server || null;
    const buildDeps = server && server.build_deps && typeof server.build_deps === 'object' ? server.build_deps : {};

    const columns = [
        {
            key: 'domain',
            type: 'title',
            title: <Translate content="Overview.columnDomain" />,
            render: row => (
                <div>
                    <RouterLink to={domainLink(row)}>{row.displayName || row.domain}</RouterLink>
                    {/* The application's URL (with the mount path in path mode); workers have none. */}
                    {row.configured && row.appUrl && (
                        <div>
                            <a href={row.appUrl} target="_blank" rel="noopener noreferrer"><Text fontSize="sm">{row.appUrl}</Text></a>
                        </div>
                    )}
                </div>
            ),
        },
        {
            key: 'runtime',
            title: <Translate content="Overview.columnRuntime" />,
            render: row => {
                if (!row.configured || !row.runtime) {
                    return '—';
                }
                const meta = runtimes[row.runtime];
                return (
                    <span>
                        {meta ? runtimeName(translate, meta) : row.runtime}
                        {row.toolchain ? <Text intent="muted"> {isolate(row.toolchain)}</Text> : null}
                    </span>
                );
            },
        },
        {
            key: 'state',
            title: <Translate content="Overview.columnStatus" />,
            render: row => <StateLabel state={row.state} />,
        },
        {
            key: 'endpoint',
            title: <Translate content="Overview.columnEndpoint" />,
            render: row => endpoint(row) || '—',
        },
        {
            key: 'memory',
            title: <Translate content="Overview.columnMemory" />,
            align: 'right',
            render: row => memoryCell(row) || '—',
        },
        {
            key: 'actions',
            type: 'actions',
            render: row => (
                <Button component={RouterLink} to={domainLink(row)} ghost icon="gear">
                    {row.configured ? <Translate content="Overview.manage" /> : <Translate content="Overview.setUp" />}
                </Button>
            ),
        },
    ];

    return (
        <div>
            <ErrorAlert error={overview.data ? null : overview.error} />
            {Array.isArray(data.errors) && data.errors.length > 0 && (
                <Alert intent="warning">
                    <Translate content="Overview.helperErrors" />
                    {data.errors.map(message => <div key={message}>{message}</div>)}
                </Alert>
            )}

            {isAdmin && <UpdateNotice api={api} update={updateInfo} onReload={() => update.reload()} />}

            {isAdmin && (
                <Toolbar>
                    <Button component={RouterLink} to="/toolchains" icon="puzzle" intent="primary">
                        <Translate content="Overview.toolchains" />
                    </Button>
                    <Button component={RouterLink} to="/settings" icon="gear">
                        <Translate content="Overview.settings" />
                    </Button>
                    <ToolbarExpander />
                    <Button ghost icon="reload" onClick={() => overview.reload()} state={overview.loading ? 'loading' : undefined}>
                        <Translate content="Common.refresh" />
                    </Button>
                </Toolbar>
            )}

            {overview.data && configured === 0 && (
                <Panel title={<Translate content="Overview.emptyTitle" />}>
                    <Steps isAdmin={isAdmin} />
                </Panel>
            )}

            <div style={{ marginTop: '16px' }}>
                <List
                    columns={columns}
                    data={apps}
                    rowKey="domainId"
                    loading={!overview.data && overview.loading}
                    emptyView={overview.data ? (
                        <ListEmptyView
                            title={<Translate content="Overview.noDomainsTitle" />}
                            description={<Translate content="Overview.noDomains" />}
                        />
                    ) : undefined}
                />
            </div>

            {isAdmin && server && (
                <Panel title={<Translate content="Overview.server" />} collapsible>
                    <Facts
                        rows={[
                            { key: 'os', label: <Translate content="Overview.serverOs" />, value: [server.os, server.arch].filter(Boolean).join(' / ') },
                            { key: 'systemd', label: <Translate content="Overview.serverSystemd" />, value: server.systemd ? String(server.systemd) : null },
                            { key: 'python', label: <Translate content="Overview.serverPython" />, value: server.python || null },
                            { key: 'helper', label: <Translate content="Overview.serverHelper" />, value: server.helperVersion || null },
                            { key: 'version', label: <Translate content="Overview.serverVersion" />, value: updateInfo && updateInfo.installed ? isolate(updateInfo.installed) : null },
                            { key: 'updates', label: <Translate content="Overview.serverUpdateCheck" />, value: updateInfo ? updateFact(updateInfo, checking, checkError, checkNow) : null },
                            {
                                // Only on servers with SELinux (null: not present).
                                key: 'selinux',
                                label: <Translate content="Overview.serverSelinux" />,
                                value: server.selinux === 'enforcing' ? (
                                    <span>
                                        <Label intent="warning" view="light"><Translate content="Overview.selinuxEnforcing" /></Label>
                                        {' '}
                                        <Text fontSize="sm"><Translate content="Overview.selinuxHint" /></Text>
                                    </span>
                                ) : (server.selinux === 'permissive' ? <Translate content="Overview.selinuxPermissive" /> : null),
                            },
                            {
                                key: 'deps',
                                label: <Translate content="Overview.serverBuildDeps" />,
                                value: Object.keys(buildDeps).length ? (
                                    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '4px' }}>
                                        {Object.keys(buildDeps).map(tool => (
                                            <Label key={tool} intent={buildDeps[tool] ? 'success' : 'warning'} view="light">{tool}</Label>
                                        ))}
                                    </span>
                                ) : null,
                            },
                        ].filter(row => ['selinux', 'version', 'updates'].indexOf(row.key) === -1 || row.value)}
                    />
                    {updateInfo && !updateInfo.updateCheck && (
                        <div style={{ marginBottom: '8px' }}>
                            <Text fontSize="sm">
                                <Translate content="Overview.updateChecksOff" />
                                {' '}
                                <RouterLink to="/settings"><Translate content="Overview.openSettings" /></RouterLink>
                            </Text>
                        </div>
                    )}
                    <Text fontSize="sm"><Translate content="Overview.hint" /></Text>
                </Panel>
            )}
        </div>
    );
};

Overview.propTypes = {
    baseUrl: PropTypes.string.isRequired,
};

export default Overview;
