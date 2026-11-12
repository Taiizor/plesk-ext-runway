// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Form, FormFieldCheckbox, FormFieldText, RouterLink, Section, Text, Toolbar, Translate, withStatusMessages, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { formErrors } from './lib/api';
import { useApi, useApiData } from './lib/hooks';
import ErrorAlert from './components/ErrorAlert';

const FIELDS = ['portMin', 'portMax', 'buildTimeout', 'memoryMb', 'cpuPercent', 'tasks',
    'buildMemoryMb', 'buildCpuPercent', 'buildTasks', 'maxAppsPerSubscription'];
/** Switches of the built-in updater (booleans). */
const SWITCHES = ['updateCheck', 'updateAuto'];

/** Numeric strings become numbers, switches booleans; anything else is sent as typed (the server validates). */
const toBody = values => {
    const body = {};
    FIELDS.forEach(key => {
        if (values[key] === undefined) {
            return;
        }
        const text = String(values[key]).trim();
        body[key] = /^-?\d+$/.test(text) ? parseInt(text, 10) : text;
    });
    SWITCHES.forEach(key => {
        if (values[key] !== undefined) {
            body[key] = Boolean(values[key]);
        }
    });
    return body;
};

const NumberField = props => <FormFieldText size="md" {...props} />;

/**
 * Server-wide settings (administrators only): port range, default limits of new applications,
 * build limits, the number of applications per subscription and the built-in updater.
 */
const Settings = ({ baseUrl, statusMessages }) => {
    const api = useApi(baseUrl);
    const translate = useTranslate();
    const settings = useApiData(() => api.get('settings'), [api]);
    const [values, setValues] = useState(null);
    const [error, setError] = useState(null);
    const [saving, setSaving] = useState(false);

    const save = formValues => {
        setSaving(true);
        setError(null);
        api.post('settings', toBody(formValues)).then(result => {
            setSaving(false);
            setValues(null);
            settings.setData(result);
            statusMessages.add({ intent: 'success', message: translate('Settings.saved') });
        }, err => {
            setSaving(false);
            setError(err);
            if (!err.fieldErrors) {
                statusMessages.add({ intent: 'danger', message: err.message });
            }
        });
    };

    if (!settings.data) {
        return <ErrorAlert error={settings.error} />;
    }
    const current = values || settings.data;
    const unknownErrors = error && error.fieldErrors
        ? Object.keys(error.fieldErrors).filter(key => FIELDS.indexOf(key) === -1 && SWITCHES.indexOf(key) === -1)
            .map(key => [].concat(error.fieldErrors[key]).join(' '))
        : [];

    return (
        <div>
            <Toolbar>
                <Button component={RouterLink} to="/overview" icon="arrow-left" ghost>
                    <Translate content="Common.backToOverview" />
                </Button>
            </Toolbar>
            {error && error.fieldErrors && (
                <Alert intent="danger">
                    <Translate content="Common.fixErrors" />
                    {unknownErrors.map(message => <div key={message}>{message}</div>)}
                </Alert>
            )}
            <Form
                values={current}
                errors={formErrors(error)}
                state={saving ? 'submit' : undefined}
                onFieldChange={(name, value) => setValues({ ...current, [name]: value })}
                onSubmit={save}
                submitButton={{ children: <Translate content="Common.save" /> }}
                applyButton={false}
                cancelButton={false}
            >
                <Section title={<Translate content="Settings.sectionPorts" />}>
                    <NumberField name="portMin" label={<Translate content="Settings.portMin" />} description={<Translate content="Settings.portMinHint" />} />
                    <NumberField name="portMax" label={<Translate content="Settings.portMax" />} description={<Translate content="Settings.portMaxHint" />} />
                </Section>
                <Section title={<Translate content="Settings.sectionDefaults" />}>
                    <NumberField name="memoryMb" label={<Translate content="Settings.memoryMb" />} description={<Translate content="Settings.memoryMbHint" />} />
                    <NumberField name="cpuPercent" label={<Translate content="Settings.cpuPercent" />} description={<Translate content="Settings.cpuPercentHint" />} />
                    <NumberField name="tasks" label={<Translate content="Settings.tasks" />} description={<Translate content="Settings.tasksHint" />} />
                </Section>
                <Section title={<Translate content="Settings.sectionBuilds" />}>
                    <NumberField name="buildTimeout" label={<Translate content="Settings.buildTimeout" />} description={<Translate content="Settings.buildTimeoutHint" />} />
                    <NumberField name="buildMemoryMb" label={<Translate content="Settings.buildMemoryMb" />} description={<Translate content="Settings.buildMemoryMbHint" />} />
                    <NumberField name="buildCpuPercent" label={<Translate content="Settings.buildCpuPercent" />} description={<Translate content="Settings.buildCpuPercentHint" />} />
                    <NumberField name="buildTasks" label={<Translate content="Settings.buildTasks" />} description={<Translate content="Settings.buildTasksHint" />} />
                </Section>
                <Section title={<Translate content="Settings.sectionSubscriptions" />}>
                    <NumberField
                        name="maxAppsPerSubscription"
                        label={<Translate content="Settings.maxAppsPerSubscription" />}
                        description={<Translate content="Settings.maxAppsPerSubscriptionHint" />}
                    />
                </Section>
                <Section title={<Translate content="Settings.sectionUpdates" />}>
                    <FormFieldCheckbox
                        name="updateCheck"
                        label={<Translate content="Settings.updateCheck" />}
                        description={<Translate content="Settings.updateCheckHint" />}
                    />
                    <FormFieldCheckbox
                        name="updateAuto"
                        label={<Translate content="Settings.updateAuto" />}
                        description={<Translate content="Settings.updateAutoHint" />}
                        disabled={!current.updateCheck}
                    />
                    <Text intent="muted" fontSize="sm"><Translate content="Settings.updatePrivacy" /></Text>
                </Section>
            </Form>
        </div>
    );
};

Settings.propTypes = {
    baseUrl: PropTypes.string.isRequired,
    statusMessages: PropTypes.object.isRequired,
};

export default withStatusMessages(Settings);
