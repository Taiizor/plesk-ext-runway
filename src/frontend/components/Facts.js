// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';

const gridStyle = {
    display: 'grid',
    gridTemplateColumns: 'minmax(110px, max-content) minmax(0, 1fr)',
    gap: '6px 16px',
    alignItems: 'baseline',
    margin: '0 0 12px',
};
const labelStyle = { color: '#737373', whiteSpace: 'nowrap' };
const valueStyle = { minWidth: 0, overflowWrap: 'anywhere' };

/**
 * Two-column list of facts: [{key, label, value}]. Rows whose value is null, undefined or ''
 * show a dash unless `hideEmpty` is set.
 */
const Facts = ({ rows, hideEmpty }) => {
    const visible = rows.filter(row => row && !(hideEmpty && (row.value === null || row.value === undefined || row.value === '')));
    if (!visible.length) {
        return null;
    }
    return (
        <div style={gridStyle}>
            {visible.map(row => [
                <div key={`${row.key}-label`} style={labelStyle}>{row.label}</div>,
                <div key={`${row.key}-value`} style={valueStyle}>
                    {row.value === null || row.value === undefined || row.value === '' ? '\u2014' : row.value}
                </div>,
            ])}
        </div>
    );
};

Facts.propTypes = {
    rows: PropTypes.arrayOf(PropTypes.shape({
        key: PropTypes.string.isRequired,
        label: PropTypes.node.isRequired,
        value: PropTypes.node,
    })).isRequired,
    hideEmpty: PropTypes.bool,
};

Facts.defaultProps = {
    hideEmpty: false,
};

export default Facts;
