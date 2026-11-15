// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Checkbox, Form, FormFieldCheckbox, FormFieldText, Panel, Paragraph, Section, Text, Translate, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { operationsBody, operationsValues, recoveryBundle, downloadJson } from '../lib/operations';
import { useApiData, useLatest, usePolling } from '../lib/hooks';
import ConfirmDialog from '../components/ConfirmDialog';
import ErrorAlert from '../components/ErrorAlert';
import LogOutput from '../components/LogOutput';

const EVENTS = ['deploy_succeeded', 'deploy_failed', 'health_restart', 'health_paused', 'app_start', 'app_stop'];
// i18n-keys: Operations.events.deploy_succeeded Operations.events.deploy_failed Operations.events.health_restart Operations.events.health_paused Operations.events.app_start Operations.events.app_stop
// i18n-keys: Operations.checks.source Operations.checks.writable Operations.checks.toolchain Operations.checks.disk Operations.checks.release_size
// i18n-keys: Operations.title Operations.intro Operations.historyTitle Operations.history Operations.history_limit Operations.historyHint Operations.diagnosticsTitle Operations.diagnostics Operations.preflight Operations.preflightHint Operations.min_free_mb Operations.releasesTitle Operations.releases Operations.releasesHint Operations.sharedHint Operations.shared_paths Operations.pathsHint Operations.exclude_paths Operations.excludeHint Operations.release_limit Operations.retentionHint Operations.release_max_mb Operations.sizeHint Operations.notificationsTitle Operations.notifications Operations.notificationsHint Operations.notification_url Operations.notification_secret Operations.secretHint Operations.secretKept Operations.clear_notification_secret Operations.backupTitle Operations.backup Operations.backupHint Operations.backup_secrets Operations.backupSecretsHint Operations.restore_start Operations.restoreStartHint Operations.runDiagnostics Operations.exportReport Operations.exportBackup Operations.importBackup Operations.importHint Operations.recoveryJson Operations.restoreSecrets Operations.invalidBackup Operations.restored Operations.saved Operations.clearReleases Operations.clearHint Operations.rollback Operations.rollbackHint Operations.active Operations.empty Operations.viewLog Operations.confirmTitle Operations.confirm Operations.lastNotification Operations.checksPassed Operations.checksFailed Operations.checkedAtDeploy Operations.passed Operations.failed
const tr = key => <Translate content={`Operations.${key}`} />;
const codeInput = { dir: 'ltr', spellCheck: false };
const actionsStyle = { display: 'flex', gap: '8px', flexWrap: 'wrap', margin: '12px 0' };

/** Optional settings are saved separately from application configuration and never restart a service. */
const OperationsPanel = ({ api, siteId, deploying, stopped, onChanged }) => {
    const translate = useTranslate();
    const [open, setOpen] = useState(false);
    const status = useApiData(() => (open ? api.get('app/operations', { site_id: siteId }) : Promise.resolve(null)), [api, siteId, open]);
    const [edited, setEdited] = useState(null);
    const [error, setError] = useState(null);
    const [busy, setBusy] = useState(null);
    const [notice, setNotice] = useState(null);
    const [report, setReport] = useState(null);
    const [record, setRecord] = useState(null);
    const [confirm, setConfirm] = useState(null);
    const [importText, setImportText] = useState('');
    const [restoreSecrets, setRestoreSecrets] = useState(false);
    const begin = useLatest();
    const data = status.data;
    const options = data && data.options;
    const values = options ? (edited || operationsValues(options)) : null;
    usePolling(() => status.reload(), deploying ? 6000 : 15000,
        Boolean(open && options && (options.history || options.releases || options.notifications) && !busy));

    const action = async (name, body = {}, done = null) => {
        const current = begin();
        setBusy(name);
        setError(null);
        setNotice(null);
        try {
            const result = await api.post('app/operations', { site_id: siteId, action: name, ...body });
            if (!current()) {
                return;
            }
            if (done) {
                done(result);
            }
            if (['save', 'rollback', 'import', 'clear-releases'].includes(name)) {
                setConfirm(null);
                await status.reload();
                if (current()) {
                    onChanged(name);
                }
            }
        } catch (err) {
            if (current()) {
                setError(err);
            }
        } finally {
            if (current()) {
                setBusy(null);
            }
        }
    };

    const importRecovery = () => {
        try {
            const backup = recoveryBundle(importText);
            action('import', { backup, restore_secrets: restoreSecrets }, () => {
                setImportText('');
                setNotice(translate('Operations.restored'));
            });
        } catch (_err) {
            setConfirm(null);
            setError(new Error(translate('Operations.invalidBackup')));
        }
    };

    const blocked = Boolean(busy || deploying);
    const field = (name, hint = null, props = {}) => (
        <FormFieldText name={name} label={tr(name)} description={hint ? tr(hint) : null} inputProps={codeInput} {...props} />
    );
    const toggle = (name, hint = null) => (
        <FormFieldCheckbox name={name} label={tr(name)} description={hint ? tr(hint) : null} />
    );

    return (
        <Panel title={tr('title')} collapsible collapsed={!open} onToggle={collapsed => setOpen(!collapsed)}>
            <Paragraph>{tr('intro')}</Paragraph>
            <ErrorAlert error={error || status.error} />
            {notice && <Alert intent="success">{notice}</Alert>}
            {values && (
                <Form
                    values={values}
                    state={busy === 'save' ? 'submit' : undefined}
                    onFieldChange={(name, value) => setEdited({ ...values, [name]: value })}
                    onSubmit={current => action('save', { options: operationsBody(current) }, () => {
                        setEdited(null);
                        setNotice(translate('Operations.saved'));
                    })}
                    submitButton={{ children: <Translate content="Common.save" />, disabled: blocked }}
                    applyButton={false}
                    cancelButton={false}
                >
                    <Section title={tr('historyTitle')}>
                        {toggle('history')}
                        {values.history && field('history_limit', 'historyHint', { size: 'md' })}
                    </Section>
                    <Section title={tr('diagnosticsTitle')}>
                        {toggle('diagnostics')}
                        {values.diagnostics && toggle('preflight', 'preflightHint')}
                        {(values.diagnostics || values.releases) && field('min_free_mb', null, { size: 'md' })}
                    </Section>
                    <Section title={tr('releasesTitle')}>
                        {toggle('releases', 'releasesHint')}
                        {values.releases && (
                            <div>
                                <Alert intent="warning">{tr('sharedHint')}</Alert>
                                {field('shared_paths', 'pathsHint', { multiline: true, rows: 3, size: 'xl', placeholder: 'wwwroot\nuploads' })}
                                {field('exclude_paths', 'excludeHint', { multiline: true, rows: 3, size: 'xl' })}
                                {field('release_limit', 'retentionHint', { size: 'md' })}
                                {field('release_max_mb', 'sizeHint', { size: 'md' })}
                            </div>
                        )}
                    </Section>
                    <Section title={tr('notificationsTitle')}>
                        {toggle('notifications', 'notificationsHint')}
                        {values.notifications && (
                            <div>
                                {field('notification_url', null, { size: 'xl', placeholder: 'https://example.com/runway' })}
                                {field('notification_secret', options.has_notification_secret ? 'secretKept' : 'secretHint', {
                                    size: 'xl', inputProps: { ...codeInput, type: 'password', autoComplete: 'new-password' },
                                })}
                                {options.has_notification_secret && toggle('clear_notification_secret')}
                                {EVENTS.map(event => (
                                    <Checkbox
                                        key={event}
                                        checked={values.notification_events.includes(event)}
                                        onChange={checked => setEdited({ ...values, notification_events: checked
                                            ? [...values.notification_events, event] : values.notification_events.filter(item => item !== event) })}
                                    >{tr(`events.${event}`)}</Checkbox>
                                ))}
                            </div>
                        )}
                    </Section>
                    <Section title={tr('backupTitle')}>
                        {toggle('backup', 'backupHint')}
                        {values.backup && toggle('backup_secrets', 'backupSecretsHint')}
                        {values.backup && toggle('restore_start', 'restoreStartHint')}
                    </Section>
                </Form>
            )}
            {options && (
                <div>
                    <div style={actionsStyle}>
                        <Button ghost disabled={blocked} onClick={() => status.reload()}><Translate content="Common.refresh" /></Button>
                        {options.diagnostics && (
                            <Button disabled={blocked} state={busy === 'diagnostics' ? 'loading' : undefined}
                                onClick={() => action('diagnostics', {}, setReport)}>{tr('runDiagnostics')}</Button>
                        )}
                        {options.backup && (
                            <Button disabled={blocked} onClick={() => action('export', {}, result => downloadJson(`runway-${siteId}-recovery.json`, result.bundle))}>
                                {tr('exportBackup')}
                            </Button>
                        )}
                        {!options.releases && stopped && (
                            <Button intent="danger" ghost disabled={blocked} onClick={() => setConfirm({ action: 'clear-releases' })}>{tr('clearReleases')}</Button>
                        )}
                    </div>
                    {data.notification && <Paragraph>{tr('lastNotification')}: {data.notification.time} — {data.notification.state}</Paragraph>}
                    {report && (
                        <Section title={tr('diagnosticsTitle')}>
                            <Text intent={report.ready ? 'success' : 'danger'}>{tr(report.ready ? 'checksPassed' : 'checksFailed')}</Text>
                            {report.checks.map(check => (
                                <Paragraph key={check.key}>
                                    {tr(`checks.${check.key}`)}: {tr(check.ok === null ? 'checkedAtDeploy' : (check.ok ? 'passed' : 'failed'))}
                                    {check.free_mb !== undefined ? ` (${check.free_mb} MiB / ${check.required_mb} MiB)` : ''}
                                </Paragraph>
                            ))}
                            <Button ghost onClick={() => downloadJson(`runway-${siteId}-diagnostics.json`, report)}>{tr('exportReport')}</Button>
                        </Section>
                    )}
                    {options.releases && (
                        <Section title={tr('releasesTitle')}>
                            <Paragraph>{tr('rollbackHint')}</Paragraph>
                            {!data.releases.length && <Paragraph>{tr('empty')}</Paragraph>}
                            {data.releases.map(release => (
                                <Paragraph key={release.id}>
                                    <code dir="ltr">{release.id}</code> {release.active && <Text intent="success">{tr('active')}</Text>}{' '}
                                    <Button ghost disabled={blocked || release.active} onClick={() => setConfirm({ action: 'rollback', id: release.id })}>{tr('rollback')}</Button>
                                </Paragraph>
                            ))}
                        </Section>
                    )}
                    {options.history && (
                        <Section title={tr('historyTitle')}>
                            {!data.history.length && <Paragraph>{tr('empty')}</Paragraph>}
                            {data.history.map(entry => (
                                <Paragraph key={entry.id}>
                                    <code dir="ltr">{entry.started_at}</code> — {entry.actor} — {entry.mode} — {entry.state} ({entry.duration_seconds}s){' '}
                                    <Button ghost disabled={blocked} onClick={() => action('history', { id: entry.id }, setRecord)}>{tr('viewLog')}</Button>
                                </Paragraph>
                            ))}
                            {record && <LogOutput text={record.log} />}
                            {data.events.slice(0, 20).map(event => (
                                <Paragraph key={event.id}><Text intent="muted">{event.time} — {tr(`events.${event.event}`)} {event.detail.actor || ''}</Text></Paragraph>
                            ))}
                        </Section>
                    )}
                    {options.backup && (
                        <Section title={tr('importBackup')}>
                            <Paragraph>{tr('importHint')}</Paragraph>
                            <FormFieldText value={importText} onChange={setImportText} label={tr('recoveryJson')} multiline rows={4} size="xl" inputProps={codeInput} />
                            <Checkbox checked={restoreSecrets} onChange={setRestoreSecrets}>{tr('restoreSecrets')}</Checkbox>
                            <Button intent="danger" disabled={blocked || !importText.trim() || !stopped} onClick={() => setConfirm({ action: 'import' })}>{tr('importBackup')}</Button>
                        </Section>
                    )}
                </div>
            )}
            <ConfirmDialog
                isOpen={Boolean(confirm)} title={tr('confirmTitle')} confirmText={tr('confirm')} intent="danger" busy={Boolean(busy)}
                onConfirm={() => (confirm.action === 'import' ? importRecovery() : action(confirm.action, confirm.id ? { id: confirm.id } : {}))}
                onClose={() => setConfirm(null)}
            >
                <Paragraph>{tr(confirm && confirm.action === 'rollback' ? 'rollbackHint'
                    : (confirm && confirm.action === 'clear-releases' ? 'clearHint' : 'importHint'))}</Paragraph>
                {confirm && confirm.id && <code dir="ltr">{confirm.id}</code>}
            </ConfirmDialog>
        </Panel>
    );
};

OperationsPanel.propTypes = {
    api: PropTypes.object.isRequired,
    siteId: PropTypes.string.isRequired,
    deploying: PropTypes.bool.isRequired,
    stopped: PropTypes.bool.isRequired,
    onChanged: PropTypes.func.isRequired,
};

export default OperationsPanel;
