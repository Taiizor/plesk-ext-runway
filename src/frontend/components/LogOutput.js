// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { Translate } from '@plesk/plesk-ext-sdk';

const preStyle = {
    margin: 0,
    padding: '10px 12px',
    maxHeight: '420px',
    minHeight: '120px',
    overflow: 'auto',
    background: '#1f2328',
    color: '#e6edf3',
    borderRadius: '4px',
    fontFamily: 'Menlo, Consolas, "Liberation Mono", monospace',
    fontSize: '12px',
    lineHeight: 1.45,
    whiteSpace: 'pre-wrap',
    overflowWrap: 'anywhere',
};

// Plesk's dark theme inverts the whole page (html[data-theme=dark] { filter: invert(0.9)
// hue-rotate(180deg) }), which would turn this dark log box light: invert it back.
const darkThemeFix = 'html[data-theme="dark"] pre.runway-log { filter: invert(1) hue-rotate(180deg); }';

/**
 * Log viewer (dark, monospace, also in Plesk's dark theme). Keeps the view scrolled to the
 * bottom when new output arrives, unless the user scrolled up to read older lines.
 */
const LogOutput = ({ text, empty }) => {
    const ref = useRef(null);
    const stick = useRef(true);
    useEffect(() => {
        const element = ref.current;
        if (element && stick.current) {
            element.scrollTop = element.scrollHeight;
        }
    }, [text]);
    const onScroll = () => {
        const element = ref.current;
        if (element) {
            stick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 24;
        }
    };
    return (
        <div>
            <style>{darkThemeFix}</style>
            <pre ref={ref} dir="ltr" className="runway-log" style={preStyle} onScroll={onScroll} data-testid="log-output">
                {text ? text : (empty || <Translate content="Common.logEmpty" />)}
            </pre>
        </div>
    );
};

LogOutput.propTypes = {
    text: PropTypes.string,
    empty: PropTypes.node,
};

LogOutput.defaultProps = {
    text: '',
    empty: null,
};

export default LogOutput;
