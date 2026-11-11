// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';
import { Button, Dialog, Translate } from '@plesk/plesk-ext-sdk';

/**
 * Confirmation dialog (DESIGN section 8: never window.confirm). The confirm button shows a
 * spinner while `busy`.
 */
const ConfirmDialog = ({ isOpen, title, children, confirmText, intent, busy, onConfirm, onClose }) => (
    <Dialog
        isOpen={isOpen}
        size="sm"
        title={title}
        onClose={busy ? undefined : onClose}
        cancelTitle={<Translate content="Common.cancel" />}
        buttons={(
            <Button intent={intent} state={busy ? 'loading' : undefined} onClick={onConfirm}>
                {confirmText}
            </Button>
        )}
    >
        {children}
    </Dialog>
);

ConfirmDialog.propTypes = {
    isOpen: PropTypes.bool.isRequired,
    title: PropTypes.node.isRequired,
    children: PropTypes.node,
    confirmText: PropTypes.node.isRequired,
    intent: PropTypes.string,
    busy: PropTypes.bool,
    onConfirm: PropTypes.func.isRequired,
    onClose: PropTypes.func.isRequired,
};

ConfirmDialog.defaultProps = {
    children: null,
    intent: 'primary',
    busy: false,
};

export default ConfirmDialog;
