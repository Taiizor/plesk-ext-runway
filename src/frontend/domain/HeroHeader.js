// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, Fragment } from 'react';
import PropTypes from 'prop-types';
import { Button, Icon, RouterLink, Text, Translate, useTranslate } from '@plesk/plesk-ext-sdk';
import { StateLabel } from '../components/StateLabel';
import { appState, isObject, runtimeName } from '../lib/format';
import { isBusy } from '../lib/hooks';

const HeroHeader = ({
    domain,
    config,
    status,
    configured,
    appUrl,
    runtimes = [],
    busyOp,
    onControl,
    onStop,
}) => {
    const translate = useTranslate();
    const deploy = status && isObject(status.deploy) ? status.deploy : null;
    const deploying = isBusy(deploy);
    const enabled = Boolean(config && config.enabled);
    const state = appState(status, configured);
    const stopped = Boolean(status && status.stopped);
    const domainName = domain ? (domain.displayName || domain.name || '') : '';
    const siteUrl = domain ? (domain.asciiName ? `http://${domain.asciiName}` : `http://${domain.name}`) : '';
    const effectiveUrl = appUrl || siteUrl;

    const runtimeMeta = (runtimes || []).find(r => r.key === (config && config.runtime));
    const runtimeDisplay = runtimeMeta ? runtimeName(translate, runtimeMeta) : (config && config.runtime ? config.runtime.toUpperCase() : null);
    const toolchainDisplay = config && config.toolchain ? config.toolchain : null;

    let listenerText = null;
    if (configured && status) {
        if (config && (config.mode === 'worker' || config.listen === 'none')) {
            listenerText = translate('Overview.endpointWorker');
        } else if (status.socket || status.listen_mode === 'unix' || (config && config.listen === 'unix')) {
            listenerText = translate('Overview.endpointSocket');
        } else if (status.port || (config && config.port)) {
            listenerText = `127.0.0.1:${status.port || config.port}`;
        }
    }

    return (
        <div style={{
            background: 'var(--pul-color-background-surface, #ffffff)',
            border: '1px solid var(--pul-color-border-subtle, #e5e7eb)',
            borderRadius: '8px',
            padding: '18px 22px',
            marginBottom: '20px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}>
            {/* Top row: Breadcrumb navigation */}
            <div style={{ marginBottom: '10px' }}>
                <RouterLink
                    to="/overview"
                    style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '6px',
                        color: 'var(--pul-color-text-muted, #6b7280)',
                        fontSize: '12px',
                        fontWeight: 500,
                        textDecoration: 'none',
                    }}
                >
                    <span style={{ fontSize: '13px', lineHeight: 1 }}>&larr;</span>
                    <Translate content="Common.backToOverview" />
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
                {/* Left side: Domain name, Status and Meta Details */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {/* Primary Title + Live Status Badge */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                        <h1 style={{
                            margin: 0,
                            fontSize: '24px',
                            fontWeight: 700,
                            color: 'var(--pul-color-text-primary, #111827)',
                            letterSpacing: '-0.02em',
                            lineHeight: 1.2,
                        }}>
                            {domainName}
                        </h1>
                        <StateLabel state={state} />
                    </div>

                    {/* Subtitle / Meta Bar */}
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        flexWrap: 'wrap',
                        gap: '8px',
                        fontSize: '13px',
                        color: 'var(--pul-color-text-muted, #6b7280)',
                    }}>
                        {effectiveUrl && (
                            <a
                                href={effectiveUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    color: 'var(--pul-color-primary, #0070f3)',
                                    textDecoration: 'none',
                                    fontWeight: 500,
                                }}
                                title={effectiveUrl}
                            >
                                <span>{domainName}</span>
                                <span style={{ fontSize: '11px', opacity: 0.85 }}>&#8599;</span>
                            </a>
                        )}

                        {runtimeDisplay && (
                            <Fragment>
                                <span style={{ color: '#d1d5db', userSelect: 'none' }}>&bull;</span>
                                <span style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '5px',
                                    fontSize: '12px',
                                    fontWeight: 500,
                                    color: 'var(--pul-color-text-secondary, #374151)',
                                    background: 'var(--pul-color-background-subtle, #f3f4f6)',
                                    padding: '2px 8px',
                                    borderRadius: '4px',
                                    border: '1px solid var(--pul-color-border-subtle, #e5e7eb)',
                                }}>
                                    <Icon name="puzzle" size="12" />
                                    <span>{runtimeDisplay}{toolchainDisplay ? ` ${toolchainDisplay}` : ''}</span>
                                </span>
                            </Fragment>
                        )}

                        {listenerText && (
                            <Fragment>
                                <span style={{ color: '#d1d5db', userSelect: 'none' }}>&bull;</span>
                                <span style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '4px',
                                    fontSize: '12px',
                                    color: 'var(--pul-color-text-muted, #6b7280)',
                                    fontFamily: 'monospace',
                                }}>
                                    <span>{listenerText}</span>
                                </span>
                            </Fragment>
                        )}
                    </div>
                </div>

                {/* Right side: Quick Control Actions */}
                {configured && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        {stopped ? (
                            <Button
                                intent="primary"
                                icon="start"
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
    appUrl: PropTypes.string,
    runtimes: PropTypes.array,
    busyOp: PropTypes.string,
    onControl: PropTypes.func.isRequired,
    onStop: PropTypes.func.isRequired,
};

export default HeroHeader;
