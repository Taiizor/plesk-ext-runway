// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';
import { Panel, ProgressBar, Translate, useTranslate } from '@plesk/plesk-ext-sdk';
import { formatTime, jobTitle } from '../lib/format';
import { isBusy } from '../lib/hooks';
import { JobLabel } from './StateLabel';
import Facts from './Facts';
import LogOutput from './LogOutput';

/**
 * Background job (toolchain installation, build dependencies): state, times, message and the
 * live log tail.
 */
const JobPanel = ({ job, log, title, collapsed, onToggle }) => {
    const translate = useTranslate();
    if (!job || !job.state || job.state === 'none') {
        return null;
    }
    const busy = isBusy(job);
    const name = jobTitle(translate, job);
    return (
        <Panel
            title={(
                <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center' }}>
                    {title}
                    {title && name ? <span>{'—'}</span> : null}
                    {name ? <span>{name}</span> : null}
                    <JobLabel state={job.state} />
                </span>
            )}
            collapsible={Boolean(onToggle)}
            collapsed={onToggle ? collapsed : undefined}
            onToggle={onToggle}
        >
            {busy && <div style={{ marginBottom: '12px' }}><ProgressBar intent="info" /></div>}
            <Facts
                hideEmpty
                rows={[
                    { key: 'started', label: <Translate content="Common.jobStarted" />, value: formatTime(job.started_at || job.queued_at) },
                    { key: 'finished', label: <Translate content="Common.jobFinished" />, value: busy ? null : formatTime(job.finished_at) },
                    { key: 'message', label: <Translate content="Common.jobMessage" />, value: job.message || null },
                ]}
            />
            <LogOutput text={log} />
        </Panel>
    );
};

JobPanel.propTypes = {
    job: PropTypes.object,
    log: PropTypes.string,
    title: PropTypes.node,
    collapsed: PropTypes.bool,
    onToggle: PropTypes.func,
};

JobPanel.defaultProps = {
    job: null,
    log: '',
    title: null,
    collapsed: false,
    onToggle: undefined,
};

export default JobPanel;
