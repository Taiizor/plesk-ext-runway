// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Grid, GridCol, Panel, Paragraph, RouterLink, Translate, withStatusMessages, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { isObject } from './lib/format';
import {
    isBusy, POLL_BUSY_MS, POLL_IDLE_MS, queryParam, useApi, useApiData, useLatest, usePolling,
} from './lib/hooks';
import ConfirmDialog from './components/ConfirmDialog';
import ErrorAlert from './components/ErrorAlert';
import HelpPanel from './domain/HelpPanel';
import LogsPanel from './domain/LogsPanel';
import ProjectPanel from './domain/ProjectPanel';
import SettingsForm from './domain/SettingsForm';
import StatusPanel from './domain/StatusPanel';

const LOG_LINES = 300;

/**
 * Application page of one domain (site_id from the query string; the Dev Tools button of the
 * domain passes it): status and controls, project detection with the sample/fetch drawers,
 * the settings form, logs, help and the danger zone. Admins, or customers with the
 * permission (every API call checks access).
 */
const Domain = ({ baseUrl, statusMessages }) => {
    const api = useApi(baseUrl);
    const translate = useTranslate();
    const siteId = queryParam('site_id') || queryParam('dom_id');
    const context = useApiData(() => api.get('context'), [api]);
    const page = useApiData(() => (siteId ? api.get('app', { site_id: siteId }) : Promise.resolve(null)), [api, siteId]);
    const [status, setStatus] = useState(null);
    const [formVersion, setFormVersion] = useState(0);
    const [saving, setSaving] = useState(false);
    const [saveError, setSaveError] = useState(null);
    const [busyOp, setBusyOp] = useState(null);
    const [confirm, setConfirm] = useState(null);
    const [logKind, setLogKind] = useState('app');
    const [log, setLog] = useState({ text: '', error: null, loading: false });
    const [autoRefresh, setAutoRefresh] = useState(true);
    const [drawer, setDrawer] = useState(null);
    const [drawerBusy, setDrawerBusy] = useState(false);
    const [drawerError, setDrawerError] = useState(null);
    const beginStatus = useLatest();
    const beginLog = useLatest();
    const lastDeploy = useRef(null);

    const data = page.data;
    const configured = Boolean(data && data.configured);
    const deploy = status && isObject(status.deploy) ? status.deploy : null;
    const deploying = isBusy(deploy);
    const runtimes = context.data && Array.isArray(context.data.runtimes) ? context.data.runtimes : [];
    const isAdmin = Boolean((data && data.isAdmin) || (context.data && context.data.isAdmin));

    const toast = (intent, message) => statusMessages.add({ intent, message });

    const refreshStatus = () => {
        if (!siteId) {
            return Promise.resolve();
        }
        const current = beginStatus();
        return api.get('app/status', { site_id: siteId }).then(result => {
            if (current() && isObject(result)) {
                setStatus(result);
            }
        }, () => null);
    };

    const refreshLog = kind => {
        const which = kind || logKind;
        if (!siteId) {
            return Promise.resolve();
        }
        const current = beginLog();
        setLog(prev => ({ ...prev, loading: true }));
        return api.get('app/logs', { site_id: siteId, kind: which, lines: LOG_LINES }).then(result => {
            if (current()) {
                setLog({ text: result && typeof result.log === 'string' ? result.log : '', error: null, loading: false });
            }
        }, error => {
            if (current()) {
                setLog(prev => ({ ...prev, error: error.message, loading: false }));
            }
        });
    };

    // A (re)loaded page brings a fresh status; newer polls may replace it afterwards.
    useEffect(() => {
        if (data) {
            beginStatus();
            setStatus(isObject(data.status) ? data.status : null);
        }
    }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (configured) {
            refreshLog(logKind);
        } else {
            setLog({ text: '', error: null, loading: false });
        }
    }, [logKind, configured, siteId]); // eslint-disable-line react-hooks/exhaustive-deps

    // A deployment that finishes: reload the page (the project may have changed) and report it.
    useEffect(() => {
        const state = deploy ? deploy.state : null;
        const previous = lastDeploy.current;
        lastDeploy.current = state;
        if (previous && isBusy({ state: previous }) && state && !deploying) {
            page.reload();
            refreshLog();
            if (state === 'succeeded') {
                // A stopped application (Stop) is built but stays stopped.
                toast(status && status.stopped ? 'warning' : 'success',
                    translate(status && status.stopped ? 'Domain.messages.deployBuiltStopped' : 'Domain.messages.deploySucceeded'));
            } else if (state === 'failed') {
                toast('danger', translate('Domain.messages.deployFailed', { message: deploy.message || '' }));
            }
        }
    }, [deploy && deploy.state]); // eslint-disable-line react-hooks/exhaustive-deps

    const poke = usePolling(
        () => Promise.all([refreshStatus(), autoRefresh && configured ? refreshLog() : null]),
        deploying ? POLL_BUSY_MS : POLL_IDLE_MS,
        Boolean(data && (configured || deploying)),
    );

    const showDeployLog = () => {
        if (logKind !== 'deploy') {
            setLogKind('deploy');
        }
    };

    const control = op => {
        poke();
        setConfirm(null);
        setBusyOp(op);
        // "Restart in place" of a zero-downtime application: a restart without a switch.
        const body = op === 'restartPlain' ? { site_id: siteId, op: 'restart', plain: true } : { site_id: siteId, op };
        api.post('app/control', body).then(result => {
            setBusyOp(null);
            toast('success', (result && result.message) || translate('Domain.messages.done'));
            // A zero-downtime restart runs as a deploy job (the switch) like "Build & restart".
            if (op === 'deploy' || (result && result.job)) {
                if (result && isObject(result.job)) {
                    setStatus(prev => ({ ...(prev || {}), deploy: result.job }));
                }
                showDeployLog();
            }
            refreshStatus();
        }, error => {
            setBusyOp(null);
            toast('danger', error.message);
            refreshStatus();
        });
    };

    /** Toast of a save or a sample: a warning when the build could not start; follow a started build. */
    const reportApplied = (result, fallback) => {
        toast(result && result.buildError ? 'warning' : 'success', (result && result.message) || fallback);
        if (result && (result.build || result.job)) {
            showDeployLog();
        }
    };

    const save = body => {
        poke();
        setSaving(true);
        setSaveError(null);
        api.post('app/save', { ...body, site_id: siteId }).then(result => {
            setSaving(false);
            reportApplied(result, translate('Domain.messages.saved'));
            page.reload().then(() => setFormVersion(version => version + 1));
        }, error => {
            setSaving(false);
            setSaveError(error);
            if (!error.fieldErrors) {
                toast('danger', error.message);
            }
        });
    };

    const remove = () => {
        poke();
        setBusyOp('remove');
        api.post('app/remove', { site_id: siteId }).then(result => {
            setBusyOp(null);
            setConfirm(null);
            toast('success', (result && result.message) || translate('Domain.messages.removed'));
            setStatus(null);
            page.reload().then(() => setFormVersion(version => version + 1));
        }, error => {
            setBusyOp(null);
            setConfirm(null);
            toast('danger', error.message);
        });
    };

    const openDrawer = name => {
        setDrawerError(null);
        setDrawer(name);
    };

    const sample = values => {
        poke();
        setDrawerBusy(true);
        setDrawerError(null);
        api.post('app/sample', { site_id: siteId, runtime: values.runtime, listen: values.listen, force: Boolean(values.force) }).then(result => {
            setDrawerBusy(false);
            setDrawer(null);
            reportApplied(result, translate('Domain.messages.sampleCreated'));
            if (isObject(result) && isObject(result.config) && isObject(result.domain)) {
                page.setData(result);
                setFormVersion(version => version + 1);
            } else {
                page.reload().then(() => setFormVersion(version => version + 1));
            }
        }, error => {
            setDrawerBusy(false);
            setDrawerError(error);
        });
    };

    const fetchBinary = values => {
        poke();
        setDrawerBusy(true);
        setDrawerError(null);
        api.post('app/fetch', { site_id: siteId, ...values }).then(result => {
            setDrawerBusy(false);
            setDrawer(null);
            toast('info', (result && result.message) || translate('Domain.messages.fetchStarted'));
            if (result && isObject(result.job)) {
                setStatus(prev => ({ ...(prev || {}), deploy: result.job }));
            }
            showDeployLog();
            refreshStatus();
        }, error => {
            setDrawerBusy(false);
            setDrawerError(error);
        });
    };

    if (!siteId) {
        return (
            <Alert intent="warning">
                <Translate content="Domain.noSite" />
                {' '}
                <RouterLink to="/overview"><Translate content="Common.backToOverview" /></RouterLink>
            </Alert>
        );
    }
    if (!data) {
        return <ErrorAlert error={page.error || context.error} />;
    }

    const config = isObject(data.config) ? data.config : {};
    const meta = runtimes.filter(item => item.key === config.runtime)[0] || null;
    const domain = isObject(data.domain) ? data.domain : {};

    return (
        <div>
            <ErrorAlert error={page.error} />
            {data.pageError && <Alert intent="warning">{data.pageError}</Alert>}
            {domain.active === false && <Alert intent="warning"><Translate content="Domain.inactive" /></Alert>}

            <Grid xs={1} lg={2} gap="md">
                <GridCol>
                    <StatusPanel
                        data={data}
                        status={status}
                        busyOp={busyOp}
                        onControl={control}
                        onStop={() => setConfirm('stop')}
                    />
                </GridCol>
                <GridCol>
                    <ProjectPanel
                        data={data}
                        runtimes={runtimes}
                        drawer={drawer}
                        busy={drawerBusy}
                        error={drawerError}
                        onOpen={openDrawer}
                        onClose={() => setDrawer(null)}
                        onSample={sample}
                        onFetch={fetchBinary}
                    />
                </GridCol>
            </Grid>

            <SettingsForm
                key={`${siteId}-${formVersion}`}
                data={data}
                runtimes={runtimes}
                isAdmin={isAdmin}
                saving={saving}
                error={saveError}
                onSave={save}
            />

            {configured && (
                <LogsPanel
                    kind={logKind}
                    switchable={Boolean(status && status.switchable)}
                    text={log.text}
                    error={log.error}
                    loading={log.loading}
                    autoRefresh={autoRefresh}
                    onKind={setLogKind}
                    onAutoRefresh={value => {
                        poke();
                        setAutoRefresh(value);
                    }}
                    onRefresh={() => {
                        poke();
                        refreshLog();
                    }}
                />
            )}

            <Grid xs={1} lg={2} gap="md">
                <GridCol>
                    <HelpPanel meta={meta} collapsed={configured} />
                </GridCol>
                <GridCol>
                    <Panel title={<Translate content="Domain.danger.title" />}>
                        <Paragraph><Translate content="Domain.danger.removeHint" /></Paragraph>
                        <Button intent="danger" icon="recycle" disabled={!configured || Boolean(busyOp)} onClick={() => setConfirm('remove')}>
                            <Translate content="Domain.danger.remove" />
                        </Button>
                    </Panel>
                </GridCol>
            </Grid>

            <ConfirmDialog
                isOpen={confirm === 'stop'}
                title={<Translate content="Domain.confirm.stopTitle" />}
                intent="danger"
                confirmText={<Translate content="Domain.actions.stop" />}
                busy={busyOp === 'stop'}
                onConfirm={() => control('stop')}
                onClose={() => setConfirm(null)}
            >
                <Paragraph><Translate content="Domain.confirm.stop" /></Paragraph>
                <Paragraph><Translate content="Domain.confirm.stopPersists" /></Paragraph>
            </ConfirmDialog>
            <ConfirmDialog
                isOpen={confirm === 'remove'}
                title={<Translate content="Domain.confirm.removeTitle" />}
                intent="danger"
                confirmText={<Translate content="Domain.danger.remove" />}
                busy={busyOp === 'remove'}
                onConfirm={remove}
                onClose={() => setConfirm(null)}
            >
                <Paragraph><Translate content="Domain.confirm.remove" params={{ domain: domain.displayName || domain.name || '' }} /></Paragraph>
            </ConfirmDialog>
        </div>
    );
};

Domain.propTypes = {
    baseUrl: PropTypes.string.isRequired,
    statusMessages: PropTypes.object.isRequired,
};

export default withStatusMessages(Domain);
