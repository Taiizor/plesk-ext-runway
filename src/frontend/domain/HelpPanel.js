// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useState } from 'react';
import PropTypes from 'prop-types';
import { Panel, Paragraph, Translate } from '@plesk/plesk-ext-sdk';
import Facts from '../components/Facts';
import Mono from '../components/Mono';

const ENV_ROWS = [
    { key: 'port', label: <Mono>PORT</Mono>, value: <Translate content="Domain.help.envPort" /> },
    { key: 'host', label: <Mono>HOST</Mono>, value: <Translate content="Domain.help.envHost" /> },
    { key: 'listen', label: <Mono>LISTEN_ADDR</Mono>, value: <Translate content="Domain.help.envListenAddr" /> },
    { key: 'socket', label: <Mono>RUNWAY_SOCKET</Mono>, value: <Translate content="Domain.help.envSocket" /> },
    { key: 'mode', label: <Mono>RUNWAY_LISTEN</Mono>, value: <Translate content="Domain.help.envListen" /> },
    { key: 'root', label: <Mono>RUNWAY_APP_ROOT</Mono>, value: <Translate content="Domain.help.envAppRoot" /> },
];

/**
 * Help card: how the application is started and reached, the environment it gets, the
 * trigger files and a link to the runtime's documentation. Starts collapsed when `collapsed`.
 */
const HelpPanel = ({ meta, collapsed }) => {
    const [open, setOpen] = useState(!collapsed);
    return (
        <Panel
            title={<Translate content="Domain.help.title" />}
            collapsible
            collapsed={!open}
            onToggle={value => setOpen(!value)}
        >
            <Paragraph><Translate content="Domain.help.intro" /></Paragraph>
            <Facts rows={ENV_ROWS} />
            <Paragraph><Translate content="Domain.help.triggers" /></Paragraph>
            <Paragraph><Translate content="Domain.help.git" /></Paragraph>
            {meta && meta.docs_url && (
                <Paragraph>
                    <a href={meta.docs_url} target="_blank" rel="noopener noreferrer">
                        <Translate content="Domain.help.docs" params={{ runtime: meta.label }} />
                    </a>
                </Paragraph>
            )}
        </Panel>
    );
};

HelpPanel.propTypes = {
    meta: PropTypes.object,
    collapsed: PropTypes.bool,
};

HelpPanel.defaultProps = {
    meta: null,
    collapsed: false,
};

export default HelpPanel;
