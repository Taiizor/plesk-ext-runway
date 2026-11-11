// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';

const style = {
    fontFamily: 'Menlo, Consolas, "Liberation Mono", monospace',
    fontSize: '12px',
    overflowWrap: 'anywhere',
};

/**
 * Inline monospace text (paths, commands, variables) in the normal text color; the panel's
 * own <code> style is red.
 */
const Mono = ({ children }) => <span style={style}>{children}</span>;

Mono.propTypes = {
    children: PropTypes.node,
};

Mono.defaultProps = {
    children: null,
};

export default Mono;
