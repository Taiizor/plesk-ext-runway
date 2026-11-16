// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, Fragment, useState, useMemo, useRef, useLayoutEffect } from 'react';
import PropTypes from 'prop-types';
import { useTranslate } from '@plesk/plesk-ext-sdk';

/**
 * Modern SVG-based responsive metric chart (area + line) with time range selector,
 * Min/Avg/Max stats, and hover tooltips. Zero external dependencies.
 */
const MetricChart = ({
    title,
    data,
    unit = '',
    color = '#0070f3',
    range = '1h',
    onRangeChange,
    formatValue,
    height = 140,
    startTime,
    endTime,
    step,
    latestValue,
    series,
}) => {
    const translate = useTranslate();
    const [hoverIndex, setHoverIndex] = useState(null);
    const [tooltipLeft, setTooltipLeft] = useState(8);
    const [tooltipWidth, setTooltipWidth] = useState(0);
    const plotRef = useRef(null);
    const tooltipRef = useRef(null);

    const datasets = useMemo(() => (series || [{ key: 'value', data, color, latestValue }]).map(item => {
        const samples = (Array.isArray(item.data) ? item.data : [])
            .filter(d => Number.isFinite(d.time) && Number.isFinite(d.value))
            .slice().sort((a, b) => a.time - b.time);
        const values = samples.map(d => d.value);
        return { ...item, samples, stats: {
            min: values.length ? Math.min(...values) : 0,
            max: Math.max(0, ...values, ...samples.map(d => d.peak).filter(Number.isFinite),
                Number.isFinite(item.latestValue) ? item.latestValue : 0),
            avg: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0,
            last: values[values.length - 1],
        } };
    }), [series, data, color, latestValue]);

    const chartPoints = useMemo(() => {
        const samples = datasets.flatMap(item => item.samples);
        if (samples.length === 0) return null;
        const minVal = Math.min(0, ...datasets.map(item => item.stats.min));
        const maxVal = Math.max(...datasets.map(item => item.stats.max * 1.15), 1);
        const valRange = maxVal - minVal || 1;

        const w = 500;
        const h = height;
        const padX = 10;
        const padY = 15;
        const innerW = w - padX * 2;
        const innerH = h - padY * 2;

        const lastTime = Number.isFinite(endTime) ? endTime : Math.max(...samples.map(d => d.time));
        const duration = { '1h': 3600, '24h': 86400, '7d': 604800 }[range] || 3600;
        const firstTime = Number.isFinite(startTime) ? startTime : lastTime - duration;
        const timeSpan = Math.max(1, lastTime - firstTime);
        const gap = (step || { '1h': 60, '24h': 300, '7d': 3600 }[range] || 60) * 1.5;
        const point = d => {
            const x = padX + ((d.time - firstTime) / timeSpan) * innerW;
            const y = padY + innerH - ((d.value - minVal) / valRange) * innerH;
            return { x, y, time: d.time, value: d.value };
        };
        const pointsByTime = new Map();
        const lines = datasets.map(item => {
            const pts = item.samples.filter(d => d.time >= firstTime && d.time <= lastTime).map(point);
            const segments = [];
            pts.forEach((p, i) => {
                if (i === 0 || p.time - pts[i - 1].time > gap) segments.push([]);
                segments[segments.length - 1].push(p);
                if (!pointsByTime.has(p.time)) pointsByTime.set(p.time, { ...p, entries: [] });
                pointsByTime.get(p.time).entries.push({ ...p, label: item.label, color: item.color, key: item.key });
            });
            const paths = segments.map(segment => {
                const line = segment.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
                const area = `${line} L ${segment[segment.length - 1].x.toFixed(1)} ${(padY + innerH).toFixed(1)} L ${segment[0].x.toFixed(1)} ${(padY + innerH).toFixed(1)} Z`;
                return { line, area };
            });
            return { ...item, linePath: paths.map(p => p.line).join(' '), areaPath: paths.map(p => p.area).join(' '),
                singletons: segments.filter(s => s.length === 1).map(s => s[0]) };
        });
        return { lines, pts: Array.from(pointsByTime.values()).sort((a, b) => a.time - b.time),
            w, h, innerW, innerH, padX, padY, firstTime, lastTime };
    }, [datasets, height, startTime, endTime, step, range]);

    const hoveredPoint = hoverIndex !== null ? chartPoints?.pts[hoverIndex] : null;
    useLayoutEffect(() => {
        if (!hoveredPoint || !plotRef.current || !tooltipRef.current) return undefined;
        const position = () => {
            if (!plotRef.current || !tooltipRef.current) return;
            const width = plotRef.current.getBoundingClientRect().width;
            const tipWidth = tooltipRef.current.getBoundingClientRect().width;
            const anchor = hoveredPoint.x / chartPoints.w * width;
            setTooltipWidth(tipWidth);
            setTooltipLeft(Math.max(8, Math.min(width - tipWidth - 8, anchor - tipWidth / 2)));
        };
        position();
        const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(position) : null;
        observer?.observe(plotRef.current);
        observer?.observe(tooltipRef.current);
        window.addEventListener('resize', position);
        return () => {
            observer?.disconnect();
            window.removeEventListener('resize', position);
        };
    }, [hoveredPoint, chartPoints]);

    const format = val => {
        if (formatValue) return formatValue(val);
        if (val >= 100) return Math.round(val) + (unit ? ' ' + unit : '');
        return (Math.round(val * 10) / 10) + (unit ? ' ' + unit : '');
    };

    const formatTime = epochSec => {
        if (!Number.isFinite(epochSec)) return '';
        const d = new Date(epochSec * 1000);
        const hh = String(d.getHours()).padStart(2, '0');
        const mm = String(d.getMinutes()).padStart(2, '0');
        if (range === '7d') {
            const day = String(d.getDate()).padStart(2, '0');
            const mo = String(d.getMonth() + 1).padStart(2, '0');
            return `${day}.${mo} ${hh}:${mm}`;
        }
        return `${hh}:${mm}`;
    };

    const gradientId = useMemo(() => `metric-grad-${Math.random().toString(36).substr(2, 9)}`, []);

    return (
        <div style={{
            background: 'var(--pul-color-bg-surface, #ffffff)',
            border: '1px solid var(--pul-color-border-subtle, #e5e7eb)',
            borderRadius: '8px',
            padding: '14px 16px',
            marginBottom: '16px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            minWidth: 0,
            maxWidth: '100%',
            boxSizing: 'border-box',
            display: 'flex',
            flexDirection: 'column',
            flex: 1,
        }}>
            {/* Header: Title, Stats & Range Selector */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--pul-color-text, #202020)' }}>
                        {title}
                    </span>
                    {datasets.map(item => <span key={item.key} style={{
                        fontSize: '15px',
                        fontWeight: 700,
                        color: item.color,
                        background: `${item.color}18`,
                        padding: '2px 8px',
                        borderRadius: '4px',
                        whiteSpace: 'nowrap',
                    }}>
                        {item.label && <span style={{ fontSize: '11px', marginRight: '5px' }}>{item.label}</span>}
                        {item.latestValue !== undefined
                            ? (Number.isFinite(item.latestValue) ? format(item.latestValue) : '—')
                            : (item.samples.length ? format(item.stats.last) : '—')}
                    </span>)}
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '8px 12px', flexWrap: 'wrap', minWidth: 0, maxWidth: '100%' }}>
                    {/* Min / Avg / Peak badges */}
                    <div style={{ fontSize: '11px', color: 'var(--pul-color-text-subtle, #737373)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                        {datasets.map(item => <div key={item.key} style={{ display: 'flex', gap: '2px 8px', flexWrap: 'wrap' }}>
                            {item.label && <span style={{ color: item.color, whiteSpace: 'nowrap' }}>{item.label}</span>}
                            <span style={{ whiteSpace: 'nowrap' }}>{translate('Domain.metricsAvg')} <strong style={{ color: 'var(--pul-color-text, #202020)' }}>{item.samples.length ? format(item.stats.avg) : '—'}</strong></span>
                            <span style={{ whiteSpace: 'nowrap' }}>{translate('Domain.metricsPeak')} <strong style={{ color: 'var(--pul-color-text, #202020)' }}>{item.samples.length ? format(item.stats.max) : '—'}</strong></span>
                        </div>)}
                    </div>

                    {/* Range Selector */}
                    {onRangeChange && (
                        <div style={{ display: 'flex', flexShrink: 0, background: 'var(--pul-color-background-subtle, #f3f4f6)', borderRadius: '6px', padding: '2px' }}>
                            {['1h', '24h', '7d'].map(r => (
                                <button
                                    key={r}
                                    type="button"
                                    onClick={() => onRangeChange(r)}
                                    style={{
                                        border: 'none',
                                        background: range === r ? 'var(--pul-color-bg-surface, #ffffff)' : 'transparent',
                                        color: range === r ? 'var(--pul-color-text, #202020)' : 'var(--pul-color-text-subtle, #737373)',
                                        fontWeight: range === r ? 600 : 400,
                                        fontSize: '12px',
                                        padding: '6px 10px',
                                        minWidth: '44px',
                                        minHeight: '44px',
                                        borderRadius: '4px',
                                        cursor: 'pointer',
                                        boxShadow: range === r ? '0 1px 2px rgba(0,0,0,0.06)' : 'none',
                                    }}
                                >
                                    {r}
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </div>

            {/* SVG Chart */}
            {chartPoints ? (
                <div ref={plotRef} style={{ position: 'relative', width: '100%', height: `${height}px`, flexShrink: 0, marginTop: 'auto', marginBottom: '18px' }}>
                    <svg
                        viewBox={`0 0 ${chartPoints.w} ${chartPoints.h}`}
                        preserveAspectRatio="none"
                        style={{ width: '100%', height: '100%', overflow: 'visible' }}
                    >
                        <defs>
                            {chartPoints.lines.map((line, i) => <linearGradient key={line.key} id={`${gradientId}-${i}`} x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor={line.color} stopOpacity="0.28" />
                                <stop offset="100%" stopColor={line.color} stopOpacity="0.02" />
                            </linearGradient>)}
                        </defs>

                        {/* Grid lines */}
                        <line x1="10" y1={chartPoints.padY} x2="490" y2={chartPoints.padY} stroke="currentColor" strokeOpacity="0.06" strokeDasharray="3 3" />
                        <line x1="10" y1={chartPoints.padY + chartPoints.innerH / 2} x2="490" y2={chartPoints.padY + chartPoints.innerH / 2} stroke="currentColor" strokeOpacity="0.06" strokeDasharray="3 3" />
                        <line x1="10" y1={chartPoints.padY + chartPoints.innerH} x2="490" y2={chartPoints.padY + chartPoints.innerH} stroke="currentColor" strokeOpacity="0.1" />

                        {chartPoints.lines.map((line, i) => <Fragment key={line.key}>
                            <path d={line.areaPath} fill={`url(#${gradientId}-${i})`} />
                            <path d={line.linePath} fill="none" stroke={line.color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
                            {line.singletons.map(p => <circle key={p.time} cx={p.x} cy={p.y} r="3" fill={line.color} />)}
                        </Fragment>)}

                        {/* Hover active point indicator */}
                        {hoverIndex !== null && chartPoints.pts[hoverIndex] && (
                            <g>
                                <line
                                    x1={chartPoints.pts[hoverIndex].x}
                                    y1={chartPoints.padY}
                                    x2={chartPoints.pts[hoverIndex].x}
                                    y2={chartPoints.padY + chartPoints.innerH}
                                    stroke="currentColor"
                                    strokeOpacity="0.4"
                                    strokeWidth="1.2"
                                    strokeDasharray="2 2"
                                />
                                {chartPoints.pts[hoverIndex].entries.map(entry => <circle
                                    key={entry.key}
                                    cx={chartPoints.pts[hoverIndex].x}
                                    cy={entry.y}
                                    r="4.5"
                                    fill={entry.color}
                                    stroke="var(--pul-color-bg-surface, #ffffff)"
                                    strokeWidth="2"
                                />)}
                            </g>
                        )}
                    </svg>

                    {/* Interactive overlay for mouse move */}
                    <div
                        style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', cursor: 'crosshair' }}
                        onMouseMove={e => {
                            const rect = e.currentTarget.getBoundingClientRect();
                            const x = ((e.clientX - rect.left) / rect.width) * chartPoints.w;
                            let idx = null;
                            chartPoints.pts.forEach((point, i) => {
                                if (idx === null || Math.abs(point.x - x) < Math.abs(chartPoints.pts[idx].x - x)) idx = i;
                            });
                            setHoverIndex(idx);
                        }}
                        onMouseLeave={() => setHoverIndex(null)}
                    />
                    <div style={{ position: 'absolute', top: '100%', left: '2%', right: '2%', display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--pul-color-text-subtle, #737373)' }}>
                        {[chartPoints.firstTime, (chartPoints.firstTime + chartPoints.lastTime) / 2, chartPoints.lastTime].map((t, i) => (
                            <span key={i}>{formatTime(t)}</span>
                        ))}
                    </div>

                    {/* Hover tooltip */}
                    {hoverIndex !== null && chartPoints.pts[hoverIndex] && (
                        <div ref={tooltipRef} role="tooltip" style={{
                            position: 'absolute',
                            left: `clamp(8px, ${tooltipLeft}px, max(8px, calc(100% - ${tooltipWidth}px - 8px)))`,
                            ...(hoveredPoint.entries.some(entry => entry.y < height / 2) ? { bottom: '8px' } : { top: '4px' }),
                            maxWidth: 'calc(100% - 16px)',
                            boxSizing: 'border-box',
                            background: 'var(--pul-color-bg-surface-overlay, #ffffff)',
                            color: 'var(--pul-color-text, #202020)',
                            border: '1px solid var(--pul-color-border-subtle, #b5b5b5)',
                            padding: '6px 8px',
                            borderRadius: '4px',
                            fontSize: '11px',
                            pointerEvents: 'none',
                            overflowWrap: 'anywhere',
                            boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
                            zIndex: 10,
                        }}>
                            <div style={{ color: 'var(--pul-color-text-subtle, #737373)', marginBottom: '3px' }}>{formatTime(hoveredPoint.time)}</div>
                            {hoveredPoint.entries.map(entry => <div key={entry.key} style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                                {entry.label && <span style={{ color: entry.color, marginRight: '6px' }}>{entry.label}</span>}
                                <strong style={{ whiteSpace: 'nowrap' }}>{format(entry.value)}</strong>
                            </div>)}
                        </div>
                    )}
                </div>
            ) : (
                <div style={{ height: `${height}px`, flexShrink: 0, marginTop: 'auto', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--pul-color-text-subtle, #737373)', fontSize: '12px' }}>
                    {translate('Domain.metricsEmpty')}
                </div>
            )}
        </div>
    );
};

MetricChart.propTypes = {
    title: PropTypes.node.isRequired,
    data: PropTypes.arrayOf(PropTypes.shape({
        time: PropTypes.number.isRequired,
        value: PropTypes.number.isRequired,
        peak: PropTypes.number,
    })),
    unit: PropTypes.string,
    color: PropTypes.string,
    range: PropTypes.string,
    onRangeChange: PropTypes.func,
    formatValue: PropTypes.func,
    height: PropTypes.number,
    startTime: PropTypes.number,
    endTime: PropTypes.number,
    step: PropTypes.number,
    latestValue: PropTypes.number,
    series: PropTypes.arrayOf(PropTypes.shape({
        key: PropTypes.string.isRequired,
        label: PropTypes.string,
        color: PropTypes.string.isRequired,
        data: PropTypes.arrayOf(PropTypes.shape({ time: PropTypes.number.isRequired, value: PropTypes.number, peak: PropTypes.number })),
        latestValue: PropTypes.number,
    })),
};

export default MetricChart;
