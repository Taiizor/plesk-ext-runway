// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement } from 'react';
import PropTypes from 'prop-types';
import { Button, RouterLink, Text, Translate } from '@plesk/plesk-ext-sdk';
import { StateLabel } from '../components/StateLabel';
import { appState, isObject } from '../lib/format';
import { isBusy } from '../lib/hooks';

const HeroHeader = ({
    domain,
    config,
    status,
    configured,
    busyOp,
    onControl,
    onStop,
}) => {
    const deploy = status && isObject(status.deploy) ? status.deploy : null;
    const deploying = isBusy(deploy);
    const enabled = Boolean(config && config.enabled);
    const state = appState(status);
    const stopped = Boolean(status && status.stopped);
    const domainName = domain ? (domain.displayName || domain.name || '') : '';
    const siteUrl = domain ? (domain.asciiName ? `http://${domain.asciiName}` : `http://${domain.name}`) : '';

    return (
        <div style={{
            background: 'var(--pul-color-background-surface, #ffffff)',
            border: '1px solid var(--pul-color-border-subtle, #e5e7eb)',
            borderRadius: '8px',
            padding: '16px 20px',
            marginBottom: '20px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}>
            {/* Top row: Breadcrumb navigation */}
            <div style={{ marginBottom: '8px', fontSize: '13px' }}>
                <RouterLink to="/overview" style={{ color: 'var(--pul-color-text-muted, #6b7280)', textDecoration: 'none' }}>
                    &larr; <Translate content="Common.backToOverview" />
                </RouterLink>
            </div>

            {/* Main row: Domain, Badges and Actions */}
            <div style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: '16px',
            }}>
                {/* Left side: Domain name, runtime badge, status badge */}
                <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
                    <h1 style={{ margin: 0, fontSize: '22px', fontWeight: 700, color: 'var(--pul-color-text-primary, #111827)' }}>
                        {domainName}
                    </h1>

                    {siteUrl && (
                        <a
                            href={siteUrl}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '4px',
                                fontSize: '12px',
                                color: 'var(--pul-color-primary, #0070f3)',
                                textDecoration: 'none',
                                background: 'rgba(0, 112, 243, 0.08)',
                                padding: '3px 8px',
                                borderRadius: '4px',
                                fontWeight: 500,
                            }}
                        >
                            <Translate content="Domain.status.openSite" /> &#8599;
                        </a>
                    )}

                    {config && config.runtime && (
                        <span style={{
                            fontSize: '12px',
                            fontWeight: 600,
                            background: 'var(--pul-color-background-subtle, #f3f4f6)',
                            color: 'var(--pul-color-text-secondary, #4b5563)',
                            padding: '3px 8px',
                            borderRadius: '4px',
                            border: '1px solid var(--pul-color-border-subtle, #e5e7eb)',
                        }}>
                            {config.runtime.toUpperCase()} {config.toolchain || ''}
                        </span>
                    )}

                    {status && <StateLabel state={state} />}
                </div>

                {/* Right side: Quick Control Actions */}
                {configured && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        {stopped ? (
                            <Button
                                intent="primary"
                                icon="play"
                                disabled={!enabled || deploying || Boolean(busyOp)}
                                state={busyOp === 'start' ? 'loading' : undefined}
                                onClick={() => onControl('start')}
                            >
                                <Translate content="Domain.actions.start" />
                            </Button>
                        ) : (
                            <Button
                                intent="danger"
                                icon="stop"
                                disabled={!enabled || deploying || Boolean(busyOp)}
                                state={busyOp === 'stop' ? 'loading' : undefined}
                                onClick={onStop}
                            >
                                <Translate content="Domain.actions.stop" />
                            </Button>
                        )}

                        <Button
                            icon="reload"
                            disabled={!enabled || deploying || Boolean(busyOp)}
                            state={busyOp === 'restart' ? 'loading' : undefined}
                            onClick={() => onControl('restart')}
                        >
                            <Translate content="Domain.actions.restart" />
                        </Button>

                        <Button
                            intent={stopped ? undefined : 'primary'}
                            icon="deploy"
                            disabled={!enabled || deploying || Boolean(busyOp)}
                            state={busyOp === 'deploy' || deploying ? 'loading' : undefined}
                            onClick={() => onControl('deploy')}
                        >
                            <Translate content="Domain.actions.deploy" />
                        </Button>
                    </div>
                )}
            </div>
        </div>
    );
};

HeroHeader.propTypes = {
    domain: PropTypes.object,
    config: PropTypes.object,
    status: PropTypes.object,
    configured: PropTypes.bool.isRequired,
    busyOp: PropTypes.string,
    onControl: PropTypes.func.isRequired,
    onStop: PropTypes.func.isRequired,
};

export default HeroHeader;
