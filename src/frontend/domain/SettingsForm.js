// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import {
    Alert, Button, Form, FormField, FormFieldCheckbox, FormFieldSelect, FormFieldText, Panel, Section, SelectOption, Status, Text,
    Translate, useTranslate,
} from '@plesk/plesk-ext-sdk';
import { formErrors } from '../lib/api';
import { helperText, isObject, isolate, runtimeDefaults, runtimeName, unixSupported } from '../lib/format';

const ADVANCED = ['buildCmd', 'startCmd', 'env', 'mountPath', 'staticPaths', 'healthPath', 'healthWatch', 'healthWatchInterval',
    'healthWatchFailures', 'autoDeploy', 'memoryMb', 'cpuPercent', 'tasks',
    'zeroDowntime', 'readyTimeout', 'drainSeconds'];
const LIMITS = ['memoryMb', 'cpuPercent', 'tasks'];
// Fields the default commands depend on.
const DEFAULTS_INPUTS = ['runtime', 'toolchain', 'listen', 'mode'];
const monospace = { fontFamily: 'Menlo, Consolas, "Liberation Mono", monospace', fontSize: '12px' };
// Commands, variables and paths are code: left-to-right also in right-to-left panel languages
// (Arabic, Hebrew), where the form itself is mirrored.
const codeInput = { style: monospace, spellCheck: false, dir: 'ltr' };
const pathInput = { spellCheck: false, dir: 'ltr' };
const noticeStyle = { display: 'inline-block', marginInlineStart: '12px', verticalAlign: 'middle' };
// How long the confirmation or warning next to "Use the default commands" stays visible.
const NOTICE_MS = 5000;

const text = value => (value === null || value === undefined ? '' : String(value));

/** An application root as the helper stores it: forward slashes, no leading or trailing slash. */
const normalRoot = value => String(value || '').split('\\').join('/').replace(/^[ /]+|[ /]+$/g, '');

/**
 * The document root (an entry of api/app documentRoots: {domain, path}, relative to the
 * subscription home directory) that an application root lies in, compared as text, or null. The
 * web server serves the files there whenever it does not pass a request to the application.
 */
export const documentRootOf = (appRoot, roots) => {
    const path = normalRoot(appRoot);
    if (!path || !Array.isArray(roots)) {
        return null;
    }
    return roots.filter(root => isObject(root) && typeof root.path === 'string' && root.path !== ''
        && (path === root.path || path.indexOf(`${root.path}/`) === 0))[0] || null;
};

/** Caps of the zero-downtime timeouts from api/app (server settings), with the defaults of the server settings. */
const zeroDowntimeCaps = data => {
    const caps = isObject(data.zeroDowntimeCaps) ? data.zeroDowntimeCaps : {};
    return {
        ready: typeof caps.ready === 'number' ? caps.ready : 120,
        drain: typeof caps.drain === 'number' ? caps.drain : 30,
    };
};

/** A stored timeout (or its default) within the current cap: PHP sends the stored values clamped the same way. */
const capped = (value, fallback, cap) => {
    const raw = value === null || value === undefined || value === '' ? fallback : value;
    const number = Number(raw);
    return Number.isFinite(number) && number > cap ? cap : raw;
};

/** Form values from api/app data (tolerates missing fields). */
export const formValues = data => {
    const config = isObject(data.config) ? data.config : {};
    const limits = isObject(data.limits) ? data.limits : {};
    const caps = zeroDowntimeCaps(data);
    const listen = config.listen || 'tcp';
    return {
        enabled: Boolean(config.enabled),
        runtime: text(config.runtime),
        toolchain: text(config.toolchain),
        appRoot: text(config.appRoot),
        mode: config.mode || (listen === 'none' ? 'worker' : 'web'),
        listen,
        mountPath: text(config.mountPath),
        staticPaths: Array.isArray(config.staticPaths) ? config.staticPaths.join('\n') : text(config.staticPaths),
        healthPath: text(config.healthPath),
        // Health watch: defaults 30 s and 3 failed checks in a row.
        healthWatch: Boolean(config.healthWatch),
        healthWatchInterval: text(config.healthWatchInterval || 30),
        healthWatchFailures: text(config.healthWatchFailures || 3),
        buildCmd: text(config.buildCmd),
        startCmd: text(config.startCmd),
        autoDeploy: config.autoDeploy !== false,
        zeroDowntime: Boolean(config.zeroDowntime),
        // Defaults 60 and 10; a lowered cap of the server settings applies to them too, so that
        // ticking the checkbox does not send a value the server refuses.
        readyTimeout: text(capped(config.readyTimeout, 60, caps.ready)),
        drainSeconds: text(capped(config.drainSeconds, 10, caps.drain)),
        env: typeof data.env === 'string' ? data.env : '',
        memoryMb: text(limits.memoryMb || 0),
        cpuPercent: text(limits.cpuPercent || 0),
        tasks: text(limits.tasks || 0),
    };
};

/**
 * Request body of api/app/save. A runtime without builds (prebuilt binary) sends an empty build
 * command (a hidden one of another runtime must not run). The limits are sent only when the
 * administrator changed them: untouched, the application keeps following the server defaults.
 */
const requestBody = (values, data, isAdmin, supportsBuild) => {
    const initial = formValues(data);
    const body = {
        enabled: Boolean(values.enabled),
        runtime: values.runtime,
        toolchain: values.toolchain,
        appRoot: values.appRoot.trim(),
        mode: values.mode,
        listen: values.mode === 'worker' ? 'none' : values.listen,
        mountPath: values.mountPath.trim(),
        staticPaths: values.staticPaths.split(/[\r\n,]+/).map(item => item.trim()).filter(Boolean),
        healthPath: values.healthPath.trim(),
        buildCmd: supportsBuild ? values.buildCmd : '',
        startCmd: values.startCmd,
        autoDeploy: Boolean(values.autoDeploy),
    };
    // Zero-downtime deployments: not for workers; the timeouts only while the setting is on (a
    // lowered cap must not block saving an application that does not use them).
    if (values.mode !== 'worker') {
        body.zeroDowntime = Boolean(values.zeroDowntime);
        if (values.zeroDowntime) {
            ['readyTimeout', 'drainSeconds'].forEach(key => {
                const raw = String(values[key]).trim();
                body[key] = /^\d+$/.test(raw) ? parseInt(raw, 10) : raw;
            });
        }
        // Health watch: the interval and the failures only while it is on.
        body.healthWatch = Boolean(values.healthWatch);
        if (values.healthWatch) {
            ['healthWatchInterval', 'healthWatchFailures'].forEach(key => {
                const raw = String(values[key]).trim();
                body[key] = /^\d+$/.test(raw) ? parseInt(raw, 10) : raw;
            });
        }
    }
    // env is omitted when the stored variables could not be loaded (the helper keeps them).
    if (typeof data.env === 'string') {
        body.env = values.env;
    }
    if (isAdmin) {
        LIMITS.forEach(key => {
            const raw = String(values[key]).trim();
            if (raw === String(initial[key]).trim()) {
                return;
            }
            body[key] = /^\d+$/.test(raw) ? parseInt(raw, 10) : raw;
        });
    }
    return body;
};

/**
 * Settings form of the domain page with progressive disclosure: the basic fields are always
 * visible, commands, environment, URL paths, triggers and limits are in "Advanced".
 * Validation errors of api/app/save appear under the fields.
 */
const SettingsForm = ({ data, runtimes, isAdmin, saving, error, onSave }) => {
    const [values, setValues] = useState(() => {
        const initial = formValues(data);
        // e.g. PHP with the built-in server: its default command cannot use a Unix socket.
        if (initial.listen === 'unix' && !unixSupported(data.defaults, initial.runtime, initial.toolchain)) {
            initial.listen = 'tcp';
        }
        return initial;
    });
    const [advanced, setAdvanced] = useState(false);
    // Visible result of the last click on "Use the default commands" ({ applied }, null: none);
    // every click sets a new object, which restarts the timer that hides it.
    const [defaultsNotice, setDefaultsNotice] = useState(null);
    const translate = useTranslate();
    const toolchains = isObject(data.toolchains) ? data.toolchains : {};
    const defaults = isObject(data.defaults) ? data.defaults : {};
    const meta = runtimes.filter(item => item.key === values.runtime)[0] || null;
    const kind = (meta && meta.toolchain) || 'managed';
    const installed = Array.isArray(toolchains[values.runtime]) ? toolchains[values.runtime] : [];
    const supportsBuild = !meta || meta.supports_build !== false;
    const worker = values.mode === 'worker';
    const unixOk = unixSupported(defaults, values.runtime, values.toolchain);
    // Zero-downtime deployments: customers may turn them on only when the administrator allows it
    // (the setting stays editable once it is on, so it can be turned off).
    const zeroAllowed = data.zeroDowntimeAllowed !== false || formValues(data).zeroDowntime;
    // Upper limits of the timeouts (0 is a valid drain cap).
    const caps = zeroDowntimeCaps(data);
    // Default commands of the chosen runtime, listen mode and toolchain (null: none known).
    const commandDefaults = runtimeDefaults(defaults, values.runtime, values.listen, values.toolchain);
    const fieldErrors = error && error.fieldErrors ? error.fieldErrors : null;
    // A warning (never an error: saving stays possible) while the application root lies in a
    // document root: what is typed compared as text, the stored root also with symbolic links
    // resolved (api/app appRootDocumentRoot).
    const exposed = documentRootOf(values.appRoot, data.documentRoots)
        || (isObject(data.appRootDocumentRoot) && isObject(data.config) && normalRoot(values.appRoot) === normalRoot(data.config.appRoot)
            ? data.appRootDocumentRoot : null);
    const documentRoot = isObject(data.domain) && typeof data.domain.documentRoot === 'string' ? data.domain.documentRoot : '';

    // Validation errors in the advanced part open it.
    useEffect(() => {
        if (fieldErrors && Object.keys(fieldErrors).some(key => ADVANCED.indexOf(key) !== -1)) {
            setAdvanced(true);
        }
    }, [error]); // eslint-disable-line react-hooks/exhaustive-deps

    // The confirmation or warning of "Use the default commands" disappears after a while (a new
    // click restarts the timer).
    useEffect(() => {
        if (!defaultsNotice) {
            return undefined;
        }
        const timer = setTimeout(() => setDefaultsNotice(null), NOTICE_MS);
        return () => clearTimeout(timer);
    }, [defaultsNotice]);

    // Fields rendered right now: errors of other fields are listed in the alert above the form.
    const visible = ['enabled', 'runtime', 'appRoot', 'mode', 'startCmd', 'env', 'autoDeploy']
        .concat(supportsBuild ? ['buildCmd'] : [])
        .concat(kind !== 'none' ? ['toolchain'] : [])
        .concat(worker ? [] : ['listen', 'staticPaths', 'healthPath', 'healthWatch', 'zeroDowntime'])
        .concat(!worker && values.healthWatch ? ['healthWatchInterval', 'healthWatchFailures'] : [])
        .concat(!worker && values.zeroDowntime ? ['readyTimeout', 'drainSeconds'] : [])
        .concat(values.mode === 'path' ? ['mountPath'] : [])
        .concat(isAdmin ? LIMITS : []);
    const otherErrors = fieldErrors
        ? Object.keys(fieldErrors).filter(key => visible.indexOf(key) === -1).map(key => [].concat(fieldErrors[key]).join(' '))
        : [];

    const onFieldChange = (name, value) => {
        const defaultsChange = DEFAULTS_INPUTS.indexOf(name) !== -1;
        // The notice of "Use the default commands" was about the defaults before this change.
        if (defaultsChange) {
            setDefaultsNotice(null);
        }
        setValues(prev => {
            const next = { ...prev, [name]: value };
            if (name === 'runtime' && value !== prev.runtime) {
                const list = Array.isArray(toolchains[value]) ? toolchains[value] : [];
                if (!list.some(item => item.id === prev.toolchain)) {
                    next.toolchain = list.length ? list[0].id : '';
                }
            }
            if (name === 'mode') {
                if (value === 'worker') {
                    next.listen = 'none';
                } else if (prev.listen === 'none') {
                    next.listen = 'tcp';
                }
                if (value === 'path') {
                    setAdvanced(true);
                }
            }
            if (next.listen === 'unix' && !unixSupported(defaults, next.runtime, next.toolchain)) {
                next.listen = 'tcp';
            }
            // The default commands depend on runtime, listen mode and (PHP) toolchain: follow a
            // change unless the user edited the command.
            if (defaultsChange) {
                const before = runtimeDefaults(defaults, prev.runtime, prev.listen, prev.toolchain) || {};
                const after = runtimeDefaults(defaults, next.runtime, next.listen, next.toolchain) || {};
                if (!prev.buildCmd.trim() || prev.buildCmd === before.build_cmd) {
                    next.buildCmd = text(after.build_cmd);
                }
                if (!prev.startCmd.trim() || prev.startCmd === before.start_cmd) {
                    next.startCmd = text(after.start_cmd);
                }
            }
            return next;
        });
    };

    /**
     * Puts the default commands of the chosen runtime, listen mode and toolchain into the form.
     * They often are the current commands already (the stored ones, or a change of runtime or
     * listen mode followed the defaults by itself), so the field values do not change: a
     * confirmation next to the button shows that the click did its work. Without a default
     * start command (e.g. .NET with a solution, several projects or no project yet) the commands
     * are kept, as an empty start command cannot be saved, and a warning says why.
     */
    const useDefaults = () => {
        const current = commandDefaults || {};
        if (!text(current.start_cmd).trim()) {
            setDefaultsNotice({ applied: false });
            return;
        }
        setValues(prev => ({ ...prev, buildCmd: text(current.build_cmd), startCmd: text(current.start_cmd) }));
        setDefaultsNotice({ applied: true });
    };

    const toolchainOptions = installed.map(item => ({ id: String(item.id), label: item.label || String(item.id) }));
    if (values.toolchain && !toolchainOptions.some(item => item.id === values.toolchain)) {
        toolchainOptions.push({ id: values.toolchain, label: values.toolchain, missing: true });
    }

    let toolchainDescription = <Translate content="Domain.form.toolchainHint" />;
    if (!installed.length) {
        toolchainDescription = kind === 'detected'
            ? <Translate content="Domain.form.toolchainNoneDetected" />
            : <Translate content="Domain.form.toolchainNoneInstalled" />;
    }


    return (
        <Panel title={<Translate content="Domain.form.title" />}>
            {fieldErrors && (
                <Alert intent="danger">
                    <Translate content="Common.fixErrors" />
                    {otherErrors.map(message => <div key={message}>{message}</div>)}
                </Alert>
            )}
            <Form
                values={values}
                errors={formErrors(error)}
                state={saving ? 'submit' : undefined}
                onFieldChange={onFieldChange}
                onSubmit={() => onSave(requestBody(values, data, isAdmin, supportsBuild))}
                submitButton={{ children: <Translate content="Domain.form.save" /> }}
                applyButton={false}
                cancelButton={false}
            >
                <FormFieldCheckbox
                    name="enabled"
                    label={<Translate content="Domain.form.enabled" />}
                    description={<Translate content="Domain.form.enabledHint" />}
                />
                <FormFieldSelect
                    name="runtime"
                    label={<Translate content="Domain.form.runtime" />}
                    description={meta && meta.hint ? helperText(translate, meta.hint_key, null, meta.hint) : <Translate content="Domain.form.runtimeHint" />}
                    required
                >
                    {runtimes.map(item => <SelectOption key={item.key} value={item.key}>{runtimeName(translate, item)}</SelectOption>)}
                    {values.runtime && !meta ? <SelectOption value={values.runtime}>{values.runtime}</SelectOption> : null}
                </FormFieldSelect>
                {kind !== 'none' && (
                    <FormFieldSelect
                        name="toolchain"
                        label={kind === 'detected' ? <Translate content="Domain.form.interpreter" /> : <Translate content="Domain.form.toolchain" />}
                        description={toolchainDescription}
                    >
                        {!toolchainOptions.length ? <SelectOption value="">—</SelectOption> : null}
                        {toolchainOptions.map(item => (
                            <SelectOption key={item.id} value={item.id}>
                                {item.missing ? <Translate content="Domain.form.toolchainMissing" params={{ version: isolate(item.id) }} /> : isolate(item.label)}
                            </SelectOption>
                        ))}
                    </FormFieldSelect>
                )}
                <FormFieldText
                    name="appRoot"
                    label={<Translate content="Domain.form.appRoot" />}
                    description={(
                        <span>
                            <Translate content="Domain.form.appRootHint" />
                            {exposed ? (
                                <span style={{ display: 'block', marginTop: '4px' }}>
                                    <Text intent="warning">
                                        <Translate
                                            content="Domain.form.appRootInDocroot"
                                            params={{
                                                domain: isolate(exposed.domain),
                                                path: isolate(exposed.path),
                                                file: isolate(values.runtime === 'dotnet' ? 'appsettings.json' : '.env'),
                                                suggestion: isolate(data.defaultAppRoot || 'apps'),
                                            }}
                                        />
                                    </Text>
                                </span>
                            ) : null}
                        </span>
                    )}
                    size="xl"
                    required
                    inputProps={pathInput}
                />
                <FormFieldSelect
                    name="mode"
                    label={<Translate content="Domain.form.mode" />}
                    description={<Translate content="Domain.form.modeHint" />}
                >
                    <SelectOption value="web">{translate('Domain.form.modeWeb')}</SelectOption>
                    <SelectOption value="path">{translate('Domain.form.modePath')}</SelectOption>
                    <SelectOption value="worker">{translate('Domain.form.modeWorker')}</SelectOption>
                </FormFieldSelect>
                {!worker && (
                    <FormFieldSelect
                        name="listen"
                        label={<Translate content="Domain.form.listen" />}
                        description={unixOk ? <Translate content="Domain.form.listenHint" /> : <Translate content="Domain.form.listenUnixUnsupported" />}
                    >
                        <SelectOption value="tcp">{translate('Domain.form.listenTcp')}</SelectOption>
                        {unixOk ? <SelectOption value="unix">{translate('Domain.form.listenUnix')}</SelectOption> : null}
                    </FormFieldSelect>
                )}

                <Section
                    title={<Translate content="Domain.form.advanced" />}
                    collapsible
                    collapsed={!advanced}
                    onToggle={collapsed => setAdvanced(!collapsed)}
                >
                    {values.mode === 'path' && (
                        <FormFieldText
                            name="mountPath"
                            label={<Translate content="Domain.form.mountPath" />}
                            description={<Translate content="Domain.form.mountPathHint" />}
                            placeholder="/api"
                            required
                            inputProps={pathInput}
                        />
                    )}
                    {supportsBuild && (
                        <FormFieldText
                            name="buildCmd"
                            label={<Translate content="Domain.form.buildCmd" />}
                            description={<Translate content="Domain.form.buildCmdHint" />}
                            multiline
                            rows={2}
                            size="fill"
                            inputProps={codeInput}
                        />
                    )}
                    <FormFieldText
                        name="startCmd"
                        label={<Translate content="Domain.form.startCmd" />}
                        description={worker ? <Translate content="Domain.form.startCmdWorkerHint" /> : <Translate content="Domain.form.startCmdHint" />}
                        size="fill"
                        inputProps={codeInput}
                    />
                    <FormField>
                        <Button ghost icon="reset" onClick={useDefaults} disabled={!commandDefaults}>
                            <Translate content="Domain.form.useDefaults" />
                        </Button>
                        {defaultsNotice && (
                            <span style={noticeStyle}>
                                <Status intent={defaultsNotice.applied ? 'success' : 'warning'}>
                                    {defaultsNotice.applied
                                        ? <Translate content="Domain.form.useDefaultsDone" />
                                        : <Translate content="Domain.form.useDefaultsNone" />}
                                </Status>
                            </span>
                        )}
                    </FormField>
                    <FormFieldText
                        name="env"
                        label={<Translate content="Domain.form.env" />}
                        description={typeof data.env === 'string' ? <Translate content="Domain.form.envHint" /> : <Translate content="Domain.form.envUnavailable" />}
                        multiline
                        rows={5}
                        size="fill"
                        disabled={typeof data.env !== 'string'}
                        placeholder="KEY=value"
                        inputProps={codeInput}
                    />
                    {!worker && (
                        <FormFieldText
                            name="staticPaths"
                            label={<Translate content="Domain.form.staticPaths" />}
                            description={(
                                <span>
                                    <Translate content="Domain.form.staticPathsHint" />
                                    {' '}
                                    <Translate
                                        content="Domain.form.staticPathsExample"
                                        params={{ prefix: isolate('/assets'), url: isolate('/assets/app.css'), file: isolate('assets/app.css') }}
                                    />
                                    {documentRoot ? (
                                        <span>
                                            {' '}
                                            <Translate content="Domain.form.staticPathsDocroot" params={{ path: isolate(documentRoot) }} />
                                        </span>
                                    ) : null}
                                </span>
                            )}
                            multiline
                            rows={3}
                            size="xl"
                            placeholder={'/assets\n/images'}
                            inputProps={codeInput}
                        />
                    )}
                    {!worker && (
                        <FormFieldText
                            name="healthPath"
                            label={<Translate content="Domain.form.healthPath" />}
                            description={<Translate content="Domain.form.healthPathHint" />}
                            placeholder="/healthz"
                            inputProps={pathInput}
                        />
                    )}
                    {!worker && (
                        <FormFieldCheckbox
                            name="healthWatch"
                            label={<Translate content="Domain.form.healthWatch" />}
                            description={<Translate content="Domain.form.healthWatchHint" />}
                        />
                    )}
                    {!worker && values.healthWatch && (
                        <FormFieldText
                            name="healthWatchInterval"
                            label={<Translate content="Domain.form.healthWatchInterval" />}
                            description={<Translate content="Domain.form.healthWatchIntervalHint" />}
                            size="md"
                            inputProps={pathInput}
                        />
                    )}
                    {!worker && values.healthWatch && (
                        <FormFieldText
                            name="healthWatchFailures"
                            label={<Translate content="Domain.form.healthWatchFailures" />}
                            description={<Translate content="Domain.form.healthWatchFailuresHint" />}
                            size="md"
                            inputProps={pathInput}
                        />
                    )}
                    <FormFieldCheckbox
                        name="autoDeploy"
                        label={<Translate content="Domain.form.autoDeploy" />}
                        description={<Translate content="Domain.form.autoDeployHint" />}
                    />
                    {!worker && (
                        <FormFieldCheckbox
                            name="zeroDowntime"
                            label={<Translate content="Domain.form.zeroDowntime" />}
                            disabled={!zeroAllowed}
                            description={(
                                <span>
                                    <Translate content="Domain.form.zeroDowntimeHint" />
                                    {' '}
                                    <Translate content="Domain.form.zeroDowntimeCaveats" />
                                    {!zeroAllowed ? <span>{' '}<Translate content="Domain.form.zeroDowntimeAdminOnly" /></span> : null}
                                </span>
                            )}
                        />
                    )}
                    {!worker && values.zeroDowntime && (
                        <FormFieldText
                            name="readyTimeout"
                            label={<Translate content="Domain.form.readyTimeout" />}
                            description={<Translate content="Domain.form.readyTimeoutHint" params={{ max: String(caps.ready) }} />}
                            size="md"
                            inputProps={pathInput}
                        />
                    )}
                    {!worker && values.zeroDowntime && (
                        <FormFieldText
                            name="drainSeconds"
                            label={<Translate content="Domain.form.drainSeconds" />}
                            description={<Translate content="Domain.form.drainSecondsHint" params={{ max: String(caps.drain) }} />}
                            size="md"
                            inputProps={pathInput}
                        />
                    )}
                    {isAdmin && (
                        <FormFieldText
                            name="memoryMb"
                            label={<Translate content="Domain.form.memoryMb" />}
                            description={<Translate content="Domain.form.memoryMbHint" />}
                            size="md"
                        />
                    )}
                    {isAdmin && (
                        <FormFieldText
                            name="cpuPercent"
                            label={<Translate content="Domain.form.cpuPercent" />}
                            description={<Translate content="Domain.form.cpuPercentHint" />}
                            size="md"
                        />
                    )}
                    {isAdmin && (
                        <FormFieldText
                            name="tasks"
                            label={<Translate content="Domain.form.tasks" />}
                            description={<Translate content="Domain.form.tasksHint" />}
                            size="md"
                        />
                    )}
                </Section>
            </Form>
        </Panel>
    );
};

SettingsForm.propTypes = {
    data: PropTypes.object.isRequired,
    runtimes: PropTypes.array.isRequired,
    isAdmin: PropTypes.bool,
    saving: PropTypes.bool,
    error: PropTypes.object,
    onSave: PropTypes.func.isRequired,
};

SettingsForm.defaultProps = {
    isAdmin: false,
    saving: false,
    error: null,
};

export default SettingsForm;
