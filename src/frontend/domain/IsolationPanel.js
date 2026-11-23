// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Form, FormFieldCheckbox, FormFieldText, Panel, Paragraph, Translate,
} from '@plesk/plesk-ext-sdk';
import { useApiData, useLatest } from '../lib/hooks';
import ErrorAlert from '../components/ErrorAlert';

const IsolationPanel = ({ api, siteId, deploying, onChanged }) => {
    const status = useApiData(() => api.get('app/isolation', { site_id: siteId }), [api, siteId]);
    const [edited, setEdited] = useState(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [saved, setSaved] = useState(false);
    const begin = useLatest();
    const data = status.data;
    // Field names also become DOM ids; the application form shares this tab.
    const values = data && (edited || {
        isolationEnabled: data.options.enabled,
        isolationOffline: data.options.network === 'offline',
        isolationWritable: data.options.writable_paths.join('\n'),
        isolationSockets: data.options.socket_paths.join('\n'),
    });
    const save = async currentValues => {
        const current = begin();
        setBusy(true);
        setError(null);
        setSaved(false);
        try {
            await api.post('app/isolation', { site_id: siteId, options: {
                enabled: currentValues.isolationEnabled,
                network: currentValues.isolationOffline ? 'offline' : 'shared',
                writable_paths: currentValues.isolationWritable.split(/[\r\n,]+/).map(path => path.trim()).filter(Boolean),
                socket_paths: currentValues.isolationSockets.split(/[\r\n,]+/).map(path => path.trim()).filter(Boolean),
            } });
            if (current()) {
                setEdited(null);
                setSaved(true);
                await status.reload();
                onChanged();
            }
        } catch (err) {
            if (current()) {
                setError(err);
                status.reload();
                onChanged();
            }
        } finally {
            if (current()) {
                setBusy(false);
            }
        }
    };
    const blocked = busy || deploying || !data || !data.canEdit;
    return (
        <Panel title={<Translate content="Isolation.title" />}>
            <Paragraph><Translate content="Isolation.intro" /></Paragraph>
            <ErrorAlert error={status.error || error} />
            {data && !data.available && <Alert intent="warning"><Translate content="Isolation.requirements" />{' '}{data.reason}</Alert>}
            {data && !data.canEdit && <Paragraph><Translate content="Isolation.adminOnly" /></Paragraph>}
            {saved && <Alert intent="success"><Translate content="Isolation.saved" /></Alert>}
            {values && (
                <Form values={values} state={busy ? 'submit' : undefined}
                    onFieldChange={(name, value) => { setEdited({ ...values, [name]: value }); setSaved(false); }}
                    onSubmit={save} submitButton={{ children: <Translate content="Common.save" />, disabled: blocked }}
                    applyButton={false} cancelButton={false}>
                    <FormFieldCheckbox name="isolationEnabled" label={<Translate content="Isolation.enabled" />} disabled={blocked} />
                    <FormFieldText name="isolationWritable" label={<Translate content="Isolation.writable" />}
                        description={<Translate content="Isolation.writableHint" />} multiline rows={4} size="xl"
                        inputProps={{ dir: 'ltr' }} disabled={blocked} />
                    <FormFieldCheckbox name="isolationOffline" label={<Translate content="Isolation.offline" />}
                        description={<Translate content="Isolation.networkHint" />} disabled={blocked} />
                    <FormFieldText name="isolationSockets" label={<Translate content="Isolation.sockets" />}
                        description={<Translate content="Isolation.socketsHint" />} multiline rows={2} size="xl"
                        inputProps={{ dir: 'ltr' }} disabled={blocked} />
                    <Paragraph><Translate content="Isolation.resourceHint" /></Paragraph>
                    <Paragraph><Translate content="Isolation.restartHint" /></Paragraph>
                </Form>
            )}
            <Button ghost disabled={busy || status.loading} onClick={() => { status.reload(); onChanged(); }}><Translate content="Common.refresh" /></Button>
        </Panel>
    );
};

IsolationPanel.propTypes = {
    api: PropTypes.object.isRequired,
    siteId: PropTypes.string.isRequired,
    deploying: PropTypes.bool.isRequired,
    onChanged: PropTypes.func.isRequired,
};

export default IsolationPanel;
