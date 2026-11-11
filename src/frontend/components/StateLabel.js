// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';
import { Label, Translate } from '@plesk/plesk-ext-sdk';
import { jobIntent, stateIntent } from '../lib/format';

// Literal keys (no template strings) so tests/check_locales.py can find every key.
const STATE_TEXT = {
    notConfigured: <Translate content="Overview.state.notConfigured" />,
    disabled: <Translate content="Overview.state.disabled" />,
    suspended: <Translate content="Overview.state.suspended" />,
    tampered: <Translate content="Overview.state.tampered" />,
    running: <Translate content="Overview.state.running" />,
    starting: <Translate content="Overview.state.starting" />,
    stopping: <Translate content="Overview.state.stopping" />,
    failed: <Translate content="Overview.state.failed" />,
    stopped: <Translate content="Overview.state.stopped" />,
};

const JOB_TEXT = {
    none: <Translate content="Common.job.none" />,
    queued: <Translate content="Common.job.queued" />,
    running: <Translate content="Common.job.running" />,
    succeeded: <Translate content="Common.job.succeeded" />,
    failed: <Translate content="Common.job.failed" />,
};

/**
 * Application state (ApiController::appState values) as a colored label.
 */
export const StateLabel = ({ state, size }) => (
    <Label intent={stateIntent(state)} size={size}>
        {STATE_TEXT[state] || state || '?'}
    </Label>
);

StateLabel.propTypes = {
    state: PropTypes.string,
    size: PropTypes.oneOf(['sm', 'md', 'lg']),
};

StateLabel.defaultProps = {
    state: null,
    size: undefined,
};

/**
 * Background job state (queued, running, succeeded, failed, none) as a colored label.
 */
export const JobLabel = ({ state }) => (
    <Label intent={jobIntent(state)} view="light">
        {JOB_TEXT[state] || state || '?'}
    </Label>
);

JobLabel.propTypes = {
    state: PropTypes.string,
};

JobLabel.defaultProps = {
    state: null,
};
