// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';
import { Alert } from '@plesk/plesk-ext-sdk';

/**
 * Shows the messages of an ApiError (or any Error) as a danger alert; renders nothing
 * without an error.
 */
const ErrorAlert = ({ error }) => {
    if (!error) {
        return null;
    }
    const messages = error.messages && error.messages.length ? error.messages : [error.message || String(error)];
    return (
        <Alert intent="danger">
            {messages.map((message, index) => (
                // eslint-disable-next-line react/no-array-index-key
                <div key={index}>{message}</div>
            ))}
        </Alert>
    );
};

ErrorAlert.propTypes = {
    error: PropTypes.object,
};

ErrorAlert.defaultProps = {
    error: null,
};

export default ErrorAlert;
