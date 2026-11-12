// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Label, List, ListEmptyView, Panel, RouterLink, Text, Toolbar, ToolbarExpander, Translate, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { formatBytes, isolate, runtimeName } from './lib/format';
import { useApi, useApiData, usePolling } from './lib/hooks';
import ErrorAlert from './components/ErrorAlert';
import Facts from './components/Facts';
import { StateLabel } from './components/StateLabel';

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
 * Start page: every domain (with hosting) the user may manage, with the state of its
 * application; administrators also see the server facts and links to Toolchains/Settings.
 */
const Overview = ({ baseUrl }) => {
    const api = useApi(baseUrl);
    const translate = useTranslate();
    const context = useApiData(() => api.get('context'), [api]);
    const overview = useApiData(() => api.get('overview'), [api]);
    usePolling(() => overview.reload(), OVERVIEW_POLL_MS, Boolean(overview.data));

    const isAdmin = Boolean(context.data && context.data.isAdmin);
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
            render: row => (row.state === 'running' && formatBytes(row.memoryBytes)) || '—',
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
                        ].filter(row => row.key !== 'selinux' || row.value)}
                    />
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
