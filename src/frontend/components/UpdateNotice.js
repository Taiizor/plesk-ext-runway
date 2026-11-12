// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Alert, Button, Paragraph, Translate } from '@plesk/plesk-ext-sdk';
import { isolate } from '../lib/format';
import { isBusy, POLL_BUSY_MS, useLatest, usePolling } from '../lib/hooks';
import ConfirmDialog from './ConfirmDialog';
import JobPanel from './JobPanel';

const isSelfUpdate = job => Boolean(job && job.title_key === 'self_update');

/**
 * Installed version when this bundle was loaded: set from the first api/update answer. It
 * survives in-app navigation (the bundle stays loaded) and resets on a real page reload, so a
 * different installed version means the server was upgraded under the running page (by this
 * page, another tab, the CLI or the automatic installation) and the page should be reloaded.
 */
let loadedVersion = null;

/**
 * Built-in updater on the overview (administrators only): an available release with a link to
 * its notes and "Update now" (confirmation, then the self-update job in the shared admin job
 * panel), a failed attempt, a test update source, and after an upgrade the hint to reload the
 * page. `update` is the answer of GET api/update (the overview reloads it with its poll);
 * `onReload` loads it again (after the job finished).
 */
const UpdateNotice = ({ api, update, onReload }) => {
    const [confirm, setConfirm] = useState(false);
    const [pending, setPending] = useState(false);
    const [error, setError] = useState(null);
    const [job, setJob] = useState(null);
    const [log, setLog] = useState('');
    const beginJob = useLatest();
    const lastState = useRef(null);

    const initial = update && update.job;
    // A self-update that runs when the page opens, or that starts later elsewhere (another tab,
    // the CLI, the automatic installation), is followed as well.
    useEffect(() => {
        if (isSelfUpdate(initial) && isBusy(initial) && !isBusy(job)) {
            setJob(initial);
        }
    }, [initial && initial.state, initial && initial.queued_at]); // eslint-disable-line react-hooks/exhaustive-deps

    const refreshJob = () => {
        const current = beginJob();
        // The upgrade replaces the extension's files while it runs: failed polls are ignored.
        return api.get('job', { job: 'admin', lines: 400 }).then(result => {
            if (current() && result) {
                setJob(result);
                setLog(typeof result.log === 'string' ? result.log : '');
            }
        }, () => null);
    };
    const busy = isBusy(job);
    const poke = usePolling(refreshJob, POLL_BUSY_MS, busy);

    // The finished job changes the installed version: load the update status again.
    useEffect(() => {
        const state = job && job.state;
        const previous = lastState.current;
        lastState.current = state;
        if (previous && isBusy({ state: previous }) && state && !isBusy(job)) {
            onReload();
        }
    }, [job && job.state]); // eslint-disable-line react-hooks/exhaustive-deps

    if (!update) {
        return null;
    }
    if (loadedVersion === null && update.installed) {
        loadedVersion = update.installed;
    }
    const latest = update.latest || null;
    const upgraded = Boolean(update.installed) && update.installed !== loadedVersion;
    const version = upgraded ? update.installed
        : ((job && job.title_params && job.title_params.version) || (latest && latest.full) || '');
    const done = upgraded || (isSelfUpdate(job) && job.state === 'succeeded');
    // A failed attempt that this page did not follow (automatic installation, CLI, another tab).
    const failed = update.available && latest && !busy && !isSelfUpdate(job) && update.lastFailedVersion === latest.full;

    const install = () => {
        poke();
        setPending(true);
        setError(null);
        api.post('update/install', { version: latest.full }).then(() => {
            setPending(false);
            setConfirm(false);
            setJob({ state: 'queued', title_key: 'self_update', title_params: { version: latest.full } });
            refreshJob();
        }, err => {
            setPending(false);
            setConfirm(false);
            setError(err.message);
        });
    };

    return (
        <div>
            {error && <Alert intent="danger">{error}</Alert>}
            {update.updateSource && (
                <Alert intent="warning">
                    <Translate content="Overview.updateSourceTest" params={{ source: isolate(update.updateSource) }} />
                </Alert>
            )}
            {failed && !done && (
                <Alert intent="warning">
                    <Translate content="Overview.updateFailed" params={{ version: isolate(latest.full) }} />
                </Alert>
            )}
            {done && (
                <Alert intent="success">
                    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
                        <span><Translate content="Overview.updateDone" params={{ version: isolate(version) }} /></span>
                        <Button icon="reload" intent="primary" onClick={() => window.location.reload()}>
                            <Translate content="Overview.reload" />
                        </Button>
                    </span>
                </Alert>
            )}
            {update.available && latest && !busy && !done && (
                <Alert intent="info">
                    <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center' }}>
                        <span>
                            <Translate
                                content="Overview.updateAvailable"
                                params={{ version: isolate(latest.full), installed: isolate(update.installed) }}
                            />
                        </span>
                        {latest.htmlUrl && (
                            <a href={latest.htmlUrl} target="_blank" rel="noopener noreferrer">
                                <Translate content="Overview.releaseNotes" />
                            </a>
                        )}
                        <Button
                            icon="arrow-up"
                            intent="primary"
                            disabled={isBusy(update.job)}
                            onClick={() => setConfirm(true)}
                        >
                            <Translate content="Overview.updateNow" />
                        </Button>
                    </span>
                </Alert>
            )}
            {isSelfUpdate(job) && <JobPanel job={job} log={log} />}
            <ConfirmDialog
                isOpen={confirm}
                title={<Translate content="Overview.updateConfirmTitle" params={{ version: isolate(latest ? latest.full : '') }} />}
                confirmText={<Translate content="Overview.updateNow" />}
                busy={pending}
                onConfirm={install}
                onClose={() => setConfirm(false)}
            >
                <Paragraph><Translate content="Overview.updateConfirm" /></Paragraph>
            </ConfirmDialog>
        </div>
    );
};

UpdateNotice.propTypes = {
    api: PropTypes.object.isRequired,
    update: PropTypes.object,
    onReload: PropTypes.func.isRequired,
};

UpdateNotice.defaultProps = {
    update: null,
};

export default UpdateNotice;
