// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Drawer, FormFieldCheckbox, FormFieldSelect, FormFieldText, Label, Panel, Paragraph, SelectOption, Text,
    Translate, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { formErrors } from '../lib/api';
import { isObject, runtimeName, unixPossible } from '../lib/format';
import ErrorAlert from '../components/ErrorAlert';
import Facts from '../components/Facts';
import Mono from '../components/Mono';

const MAX_ENTRIES = 24;

const chipStyle = {
    display: 'inline-block',
    margin: '0 4px 4px 0',
    padding: '1px 6px',
    borderRadius: '3px',
    background: 'rgba(0, 0, 0, 0.06)',
    fontFamily: 'Menlo, Consolas, "Liberation Mono", monospace',
    fontSize: '12px',
};

/** Scalar facts of a runtime detection dict, e.g. {module: "...", go: "1.22", has_main: true}. */
const detectionFacts = detection => Object.keys(detection)
    .filter(key => {
        const value = detection[key];
        return value !== null && value !== undefined && value !== false && value !== '' && !isObject(value);
    })
    .map(key => {
        const value = detection[key];
        if (value === true) {
            return key;
        }
        return `${key}: ${Array.isArray(value) ? value.join(', ') : String(value)}`;
    });

/**
 * Runtimes the helper recognised in the application root: inspect[<runtime key>] objects
 * (go, rust, ...) and, when present, inspect.detected (a key or a list of keys).
 */
export const detectedRuntimes = (inspect, runtimes) => {
    if (!isObject(inspect)) {
        return [];
    }
    const extra = [].concat(inspect.detected || []).map(String);
    return runtimes
        .filter(meta => isObject(inspect[meta.key]) || extra.indexOf(meta.key) !== -1)
        .map(meta => ({ meta, facts: isObject(inspect[meta.key]) ? detectionFacts(inspect[meta.key]) : [] }));
};

const SampleDrawer = ({ isOpen, runtimes, initial, notEmpty, unixFor, busy, error, onSubmit, onClose }) => {
    const [values, setValues] = useState(() => ({
        ...initial,
        listen: initial.listen === 'unix' && !unixFor(initial.runtime) ? 'tcp' : initial.listen,
        force: false,
    }));
    const translate = useTranslate();
    const fieldErrors = error && error.fieldErrors ? error.fieldErrors : {};
    // The helper refuses a non-empty application root unless the user allows overwriting.
    const askForce = notEmpty || Boolean(fieldErrors.force);
    const unixOk = unixFor(values.runtime);
    return (
        <Drawer
            data-type="runway-sample-drawer"
            isOpen={isOpen}
            size="sm"
            placement="right"
            title={<Translate content="Domain.project.sampleTitle" />}
            subtitle={<Translate content="Domain.project.sampleSubtitle" />}
            onClose={onClose}
            form={{
                values,
                errors: formErrors(error),
                state: busy ? 'submit' : undefined,
                onFieldChange: (name, value) => setValues(prev => {
                    const next = { ...prev, [name]: value };
                    if (next.listen === 'unix' && !unixFor(next.runtime)) {
                        next.listen = 'tcp';
                    }
                    return next;
                }),
                onSubmit: () => onSubmit({ runtime: values.runtime, listen: values.listen, force: Boolean(askForce && values.force) }),
                submitButton: {
                    children: <Translate content="Domain.project.sampleSubmit" />,
                    disabled: askForce && !values.force,
                },
                applyButton: false,
                cancelButton: { children: <Translate content="Common.cancel" /> },
            }}
        >
            <ErrorAlert error={error && !error.fieldErrors ? error : null} />
            {askForce && <Alert intent="warning"><Translate content="Domain.project.sampleNotEmpty" /></Alert>}
            <FormFieldSelect name="runtime" label={<Translate content="Domain.form.runtime" />} required>
                {runtimes.map(meta => <SelectOption key={meta.key} value={meta.key}>{runtimeName(translate, meta)}</SelectOption>)}
            </FormFieldSelect>
            <FormFieldSelect
                name="listen"
                label={<Translate content="Domain.form.listen" />}
                description={unixOk ? <Translate content="Domain.project.sampleListenHint" /> : <Translate content="Domain.project.sampleUnixUnsupported" />}
            >
                <SelectOption value="tcp">{translate('Domain.form.listenTcp')}</SelectOption>
                {unixOk ? <SelectOption value="unix">{translate('Domain.form.listenUnix')}</SelectOption> : null}
            </FormFieldSelect>
            {askForce && (
                <FormFieldCheckbox
                    name="force"
                    label={<Translate content="Domain.project.sampleForce" />}
                    description={<Translate content="Domain.project.sampleForceHint" />}
                />
            )}
        </Drawer>
    );
};

SampleDrawer.propTypes = {
    isOpen: PropTypes.bool.isRequired,
    runtimes: PropTypes.array.isRequired,
    initial: PropTypes.object.isRequired,
    notEmpty: PropTypes.bool,
    unixFor: PropTypes.func.isRequired,
    busy: PropTypes.bool,
    error: PropTypes.object,
    onSubmit: PropTypes.func.isRequired,
    onClose: PropTypes.func.isRequired,
};

SampleDrawer.defaultProps = {
    notEmpty: false,
    busy: false,
    error: null,
};

const FetchDrawer = ({ isOpen, busy, error, onSubmit, onClose }) => {
    const [values, setValues] = useState({ url: '', sha256: '', extract: false });
    return (
        <Drawer
            data-type="runway-fetch-drawer"
            isOpen={isOpen}
            size="sm"
            placement="right"
            title={<Translate content="Domain.project.fetchTitle" />}
            subtitle={<Translate content="Domain.project.fetchSubtitle" />}
            onClose={onClose}
            form={{
                values,
                errors: formErrors(error),
                state: busy ? 'submit' : undefined,
                onFieldChange: (name, value) => setValues(prev => ({ ...prev, [name]: value })),
                onSubmit: () => onSubmit({
                    url: String(values.url || '').trim(),
                    sha256: String(values.sha256 || '').trim().toLowerCase(),
                    extract: Boolean(values.extract),
                }),
                submitButton: { children: <Translate content="Domain.project.fetchSubmit" />, disabled: !String(values.url || '').trim() },
                applyButton: false,
                cancelButton: { children: <Translate content="Common.cancel" /> },
            }}
        >
            <ErrorAlert error={error && !error.fieldErrors ? error : null} />
            <FormFieldText
                name="url"
                label={<Translate content="Domain.project.fetchUrl" />}
                description={<Translate content="Domain.project.fetchUrlHint" />}
                placeholder="https://"
                size="fill"
                required
                inputProps={{ spellCheck: false, dir: 'ltr' }}
            />
            <FormFieldText
                name="sha256"
                label={<Translate content="Domain.project.fetchSha256" />}
                description={<Translate content="Domain.project.fetchSha256Hint" />}
                size="fill"
                inputProps={{ spellCheck: false, dir: 'ltr' }}
            />
            <FormFieldCheckbox
                name="extract"
                label={<Translate content="Domain.project.fetchExtract" />}
                description={<Translate content="Domain.project.fetchExtractHint" />}
            />
        </Drawer>
    );
};

FetchDrawer.propTypes = {
    isOpen: PropTypes.bool.isRequired,
    busy: PropTypes.bool,
    error: PropTypes.object,
    onSubmit: PropTypes.func.isRequired,
    onClose: PropTypes.func.isRequired,
};

FetchDrawer.defaultProps = {
    busy: false,
    error: null,
};

/**
 * Project card: the application root, what the helper detected in it, and the drawers that
 * create a sample application or download a prebuilt binary.
 */
const ProjectPanel = ({ data, runtimes, drawer, busy, error, onOpen, onClose, onSample, onFetch }) => {
    const translate = useTranslate();
    // The helper answers {error} when it could not inspect the application root (unreadable for
    // the system user, timeout): that is not an empty directory.
    const inspectError = isObject(data.inspect) && typeof data.inspect.error === 'string' ? data.inspect.error : null;
    const inspect = isObject(data.inspect) && !inspectError && Array.isArray(data.inspect.entries) ? data.inspect : null;
    const configured = Boolean(data.configured);
    const config = isObject(data.config) ? data.config : {};
    const home = data.domain && data.domain.home;
    const path = (inspect && inspect.path) || (home && config.appRoot ? `${home}/${config.appRoot}` : config.appRoot || null);
    const entries = inspect && Array.isArray(inspect.entries) ? inspect.entries : [];
    const entryCount = inspect && typeof inspect.entry_count === 'number' ? inspect.entry_count : entries.length;
    const detected = detectedRuntimes(inspect, runtimes);
    const triggers = inspect && isObject(inspect.triggers) ? inspect.triggers : null;
    const sampleRuntime = config.runtime && runtimes.some(meta => meta.key === config.runtime) ? config.runtime : (runtimes[0] && runtimes[0].key) || '';

    const rows = [
        { key: 'path', label: <Translate content="Domain.project.path" />, value: path ? <Mono>{path}</Mono> : null },
        {
            key: 'files',
            label: <Translate content="Domain.project.files" />,
            value: inspect && inspect.exists === false ? (
                <Text intent="warning"><Translate content="Domain.project.missing" /></Text>
            ) : (
                entries.length ? (
                    <div>
                        {entries.slice(0, MAX_ENTRIES).map(name => <span key={name} dir="ltr" style={chipStyle}>{name}</span>)}
                        {entryCount > Math.min(entries.length, MAX_ENTRIES) && (
                            <Text fontSize="sm">
                                {inspect.more
                                    ? <Translate content="Domain.project.moreFilesCapped" params={{ count: entryCount - Math.min(entries.length, MAX_ENTRIES) }} />
                                    : <Translate content="Domain.project.moreFiles" params={{ count: entryCount - Math.min(entries.length, MAX_ENTRIES) }} />}
                            </Text>
                        )}
                    </div>
                ) : (inspect ? <Text intent="muted"><Translate content="Domain.project.empty" /></Text> : null)
            ),
        },
        {
            key: 'detected',
            label: <Translate content="Domain.project.detected" />,
            value: inspect ? (detected.length ? (
                <div>
                    {detected.map(item => (
                        <div key={item.meta.key} style={{ marginBottom: '4px' }}>
                            <Label intent={item.meta.key === config.runtime ? 'success' : 'info'} view="light">{runtimeName(translate, item.meta)}</Label>
                            {item.facts.length > 0 && <Text fontSize="sm">{` ${item.facts.join(' · ')}`}</Text>}
                        </div>
                    ))}
                </div>
            ) : <Text intent="muted"><Translate content="Domain.project.nothingDetected" /></Text>) : null,
        },
        {
            key: 'triggers',
            label: <Translate content="Domain.project.triggerFiles" />,
            value: triggers ? (
                <span>
                    <Mono>tmp/deploy.txt</Mono>
                    {' '}
                    {triggers.deploy ? <Translate content="Domain.project.present" /> : <Translate content="Domain.project.absent" />}
                    {', '}
                    <Mono>tmp/restart.txt</Mono>
                    {' '}
                    {triggers.restart ? <Translate content="Domain.project.present" /> : <Translate content="Domain.project.absent" />}
                </span>
            ) : null,
        },
    ];

    return (
        <Panel title={<Translate content="Domain.project.title" />}>
            {!inspect && (
                <Paragraph>
                    <Text intent="warning"><Translate content="Domain.project.unavailable" /></Text>
                    {inspectError ? <div><Text fontSize="sm">{inspectError}</Text></div> : null}
                </Paragraph>
            )}
            <Facts rows={rows} hideEmpty />
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                <Button icon="code" onClick={() => onOpen('sample')}>
                    <Translate content="Domain.project.sample" />
                </Button>
                <Button
                    icon="arrow-down-tray"
                    disabled={!configured}
                    tooltip={configured ? undefined : <Translate content="Domain.project.fetchNeedsSave" />}
                    onClick={() => onOpen('fetch')}
                >
                    <Translate content="Domain.project.fetch" />
                </Button>
                {!configured && <Text intent="muted" fontSize="sm"><Translate content="Domain.project.fetchNeedsSave" /></Text>}
            </div>
            {drawer === 'sample' && (
                <SampleDrawer
                    isOpen
                    runtimes={runtimes}
                    initial={{ runtime: sampleRuntime, listen: config.listen === 'unix' ? 'unix' : 'tcp' }}
                    notEmpty={entries.some(name => name !== 'tmp')}
                    unixFor={runtime => unixPossible(data.defaults, runtime, isObject(data.toolchains) ? data.toolchains[runtime] : [])}
                    busy={busy}
                    error={error}
                    onSubmit={onSample}
                    onClose={onClose}
                />
            )}
            {drawer === 'fetch' && (
                <FetchDrawer isOpen busy={busy} error={error} onSubmit={onFetch} onClose={onClose} />
            )}
        </Panel>
    );
};

ProjectPanel.propTypes = {
    data: PropTypes.object.isRequired,
    runtimes: PropTypes.array.isRequired,
    drawer: PropTypes.string,
    busy: PropTypes.bool,
    error: PropTypes.object,
    onOpen: PropTypes.func.isRequired,
    onClose: PropTypes.func.isRequired,
    onSample: PropTypes.func.isRequired,
    onFetch: PropTypes.func.isRequired,
};

ProjectPanel.defaultProps = {
    drawer: null,
    busy: false,
    error: null,
};

export default ProjectPanel;
