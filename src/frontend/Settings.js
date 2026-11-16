// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Form, FormFieldCheckbox, FormFieldText, RouterLink, Section, Tab, Tabs, Text, Toolbar, Translate, withStatusMessages, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { formErrors } from './lib/api';
import { useApi, useApiData } from './lib/hooks';
import ErrorAlert from './components/ErrorAlert';

const FIELDS = ['portMin', 'portMax', 'buildTimeout', 'memoryMb', 'cpuPercent', 'tasks',
    'buildMemoryMb', 'buildCpuPercent', 'buildTasks', 'maxAppsPerSubscription', 'zeroDowntimeMaxReady', 'zeroDowntimeMaxDrain'];
/** Switches (booleans): the built-in updater, zero-downtime deployments for customers. */
const SWITCHES = ['updateCheck', 'updateAuto', 'zeroDowntimeCustomers', 'planPolicies'];

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

const NumberField = props => (
    <FormFieldText
        size="md"
        inputProps={{
            inputMode: 'numeric',
            autoCorrect: 'off',
            autoCapitalize: 'none',
            spellCheck: false,
        }}
        {...props}
    />
);

/**
 * Server-wide settings (administrators only): categorized tabs, preset profiles,
 * port range, default limits, build limits, zero-downtime and updater.
 */
const Settings = ({ baseUrl, statusMessages }) => {
    const api = useApi(baseUrl);
    const translate = useTranslate();
    const settings = useApiData(() => api.get('settings'), [api]);
    const [values, setValues] = useState(null);
    const [error, setError] = useState(null);
    const [saving, setSaving] = useState(false);
    const [activeTab, setActiveTab] = useState(0);

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

    const applyPreset = presetName => {
        if (presetName === 'vps') {
            setValues({
                ...current,
                memoryMb: 256,
                cpuPercent: 50,
                tasks: 128,
                buildTimeout: 1800,
                buildMemoryMb: 1024,
                buildCpuPercent: 50,
                buildTasks: 1024,
            });
            statusMessages.add({ intent: 'info', message: translate('Settings.presetApplied', { name: translate('Settings.presetVps') }) });
        } else if (presetName === 'standard') {
            setValues({
                ...current,
                memoryMb: 512,
                cpuPercent: 100,
                tasks: 512,
                buildTimeout: 3600,
                buildMemoryMb: 2048,
                buildCpuPercent: 100,
                buildTasks: 2048,
            });
            statusMessages.add({ intent: 'info', message: translate('Settings.presetApplied', { name: translate('Settings.presetStandard') }) });
        } else if (presetName === 'high') {
            setValues({
                ...current,
                memoryMb: 2048,
                cpuPercent: 400,
                tasks: 2048,
                buildTimeout: 7200,
                buildMemoryMb: 4096,
                buildCpuPercent: 200,
                buildTasks: 4096,
            });
            statusMessages.add({ intent: 'info', message: translate('Settings.presetApplied', { name: translate('Settings.presetHigh') }) });
        }
    };

    return (
        <div>
            <Toolbar style={{ flexWrap: 'wrap', gap: '8px', marginBottom: '16px' }}>
                <Button component={RouterLink} to="/overview" icon="arrow-left" ghost>
                    <Translate content="Common.backToOverview" />
                </Button>
            </Toolbar>

            {/* Preset Profiles Bar */}
            <div style={{
                background: 'var(--pul-color-background-surface, #ffffff)',
                border: '1px solid var(--pul-color-border-subtle, #e5e7eb)',
                borderRadius: '8px',
                padding: '12px 16px',
                marginBottom: '16px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                flexWrap: 'wrap',
                gap: '12px',
            }}>
                <div>
                    <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--pul-color-text-primary, #111827)' }}>
                        <Translate content="Settings.quickPresets" />
                    </span>
                    <span style={{ fontSize: '12px', color: 'var(--pul-color-text-muted, #6b7280)', marginLeft: '8px' }}>
                        <Translate content="Settings.quickPresetsHint" />
                    </span>
                </div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                    <Button size="small" onClick={() => applyPreset('vps')}>
                        <Translate content="Settings.presetVps" />
                    </Button>
                    <Button size="small" intent="primary" onClick={() => applyPreset('standard')}>
                        <Translate content="Settings.presetStandard" />
                    </Button>
                    <Button size="small" onClick={() => applyPreset('high')}>
                        <Translate content="Settings.presetHigh" />
                    </Button>
                </div>
            </div>

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
                <Tabs active={activeTab + 1}>
                    <Tab title={<Translate content="Settings.sectionDefaults" />} onActivate={() => setActiveTab(0)}>
                        <div style={{ paddingTop: '12px' }}>
                            <NumberField name="memoryMb" label={<Translate content="Settings.memoryMb" />} description={<Translate content="Settings.memoryMbHint" />} />
                            <NumberField name="cpuPercent" label={<Translate content="Settings.cpuPercent" />} description={<Translate content="Settings.cpuPercentHint" />} />
                            <NumberField name="tasks" label={<Translate content="Settings.tasks" />} description={<Translate content="Settings.tasksHint" />} />
                        </div>
                    </Tab>

                    <Tab title={<Translate content="Settings.sectionPorts" />} onActivate={() => setActiveTab(1)}>
                        <div style={{ paddingTop: '12px' }}>
                            <NumberField name="portMin" label={<Translate content="Settings.portMin" />} description={<Translate content="Settings.portMinHint" />} />
                            <NumberField name="portMax" label={<Translate content="Settings.portMax" />} description={<Translate content="Settings.portMaxHint" />} />
                        </div>
                    </Tab>

                    <Tab title={<Translate content="Settings.sectionBuilds" />} onActivate={() => setActiveTab(2)}>
                        <div style={{ paddingTop: '12px' }}>
                            <NumberField name="buildTimeout" label={<Translate content="Settings.buildTimeout" />} description={<Translate content="Settings.buildTimeoutHint" />} />
                            <NumberField name="buildMemoryMb" label={<Translate content="Settings.buildMemoryMb" />} description={<Translate content="Settings.buildMemoryMbHint" />} />
                            <NumberField name="buildCpuPercent" label={<Translate content="Settings.buildCpuPercent" />} description={<Translate content="Settings.buildCpuPercentHint" />} />
                            <NumberField name="buildTasks" label={<Translate content="Settings.buildTasks" />} description={<Translate content="Settings.buildTasksHint" />} />
                        </div>
                    </Tab>

                    <Tab title={<Translate content="Settings.sectionSubscriptions" />} onActivate={() => setActiveTab(3)}>
                        <div style={{ paddingTop: '12px' }}>
                            <FormFieldCheckbox
                                name="planPolicies"
                                label={<Translate content="Settings.planPolicies" />}
                                description={<Translate content="Settings.planPoliciesHint" />}
                            />
                            <NumberField
                                name="maxAppsPerSubscription"
                                label={<Translate content="Settings.maxAppsPerSubscription" />}
                                description={<Translate content="Settings.maxAppsPerSubscriptionHint" />}
                            />
                        </div>
                    </Tab>

                    <Tab title={<Translate content="Settings.sectionZeroDowntime" />} onActivate={() => setActiveTab(4)}>
                        <div style={{ paddingTop: '12px' }}>
                            <FormFieldCheckbox
                                name="zeroDowntimeCustomers"
                                label={<Translate content="Settings.zeroDowntimeCustomers" />}
                                description={<Translate content="Settings.zeroDowntimeCustomersHint" />}
                            />
                            <NumberField
                                name="zeroDowntimeMaxReady"
                                label={<Translate content="Settings.zeroDowntimeMaxReady" />}
                                description={<Translate content="Settings.zeroDowntimeMaxReadyHint" />}
                            />
                            <NumberField
                                name="zeroDowntimeMaxDrain"
                                label={<Translate content="Settings.zeroDowntimeMaxDrain" />}
                                description={<Translate content="Settings.zeroDowntimeMaxDrainHint" />}
                            />
                            <div style={{ marginTop: '20px', borderTop: '1px solid var(--pul-color-border-subtle, #e5e7eb)', paddingTop: '16px' }}>
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
                            </div>
                        </div>
                    </Tab>
                </Tabs>
            </Form>
        </div>
    );
};

Settings.propTypes = {
    baseUrl: PropTypes.string.isRequired,
    statusMessages: PropTypes.object.isRequired,
};

export default withStatusMessages(Settings);
