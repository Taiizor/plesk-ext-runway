// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useState, useMemo } from 'react';
import PropTypes from 'prop-types';

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
}) => {
    const [hoverIndex, setHoverIndex] = useState(null);

    const values = useMemo(() => {
        if (!Array.isArray(data) || data.length === 0) return [];
        return data.map(d => (typeof d.value === 'number' ? d.value : 0));
    }, [data]);

    const stats = useMemo(() => {
        if (values.length === 0) return { min: 0, avg: 0, max: 0, last: 0 };
        const min = Math.min(...values);
        const max = Math.max(...values);
        const sum = values.reduce((acc, v) => acc + v, 0);
        const avg = sum / values.length;
        const last = values[values.length - 1];
        return { min, avg, max, last };
    }, [values]);

    const chartPoints = useMemo(() => {
        if (!Array.isArray(data) || data.length < 2) return null;
        const minVal = Math.min(0, stats.min);
        const maxVal = Math.max(stats.max * 1.15, 1);
        const valRange = maxVal - minVal || 1;

        const w = 500;
        const h = height;
        const padX = 10;
        const padY = 15;
        const innerW = w - padX * 2;
        const innerH = h - padY * 2;

        const pts = data.map((d, i) => {
            const x = padX + (i / (data.length - 1)) * innerW;
            const y = padY + innerH - ((d.value - minVal) / valRange) * innerH;
            return { x, y, time: d.time, value: d.value };
        });

        const linePath = pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
        const areaPath = `${linePath} L ${pts[pts.length - 1].x.toFixed(1)} ${(padY + innerH).toFixed(1)} L ${pts[0].x.toFixed(1)} ${(padY + innerH).toFixed(1)} Z`;

        return { linePath, areaPath, pts, w, h, innerW, innerH, padX, padY, minVal, maxVal };
    }, [data, height, stats.max, stats.min]);

    const format = val => {
        if (formatValue) return formatValue(val);
        if (val >= 100) return Math.round(val) + (unit ? ' ' + unit : '');
        return (Math.round(val * 10) / 10) + (unit ? ' ' + unit : '');
    };

    const formatTime = epochSec => {
        if (!epochSec) return '';
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
            background: 'var(--pul-color-background-surface, #ffffff)',
            border: '1px solid var(--pul-color-border-subtle, #e5e7eb)',
            borderRadius: '8px',
            padding: '14px 16px',
            marginBottom: '16px',
            boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
        }}>
            {/* Header: Title, Stats & Range Selector */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--pul-color-text-primary, #111827)' }}>
                        {title}
                    </span>
                    <span style={{
                        fontSize: '15px',
                        fontWeight: 700,
                        color: color,
                        background: `${color}18`,
                        padding: '2px 8px',
                        borderRadius: '4px',
                    }}>
                        {format(stats.last)}
                    </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    {/* Min / Avg / Peak badges */}
                    <div style={{ fontSize: '11px', color: 'var(--pul-color-text-muted, #6b7280)', display: 'flex', gap: '8px' }}>
                        <span>Avg: <strong style={{ color: 'var(--pul-color-text-primary, #374151)' }}>{format(stats.avg)}</strong></span>
                        <span>Peak: <strong style={{ color: 'var(--pul-color-text-primary, #374151)' }}>{format(stats.max)}</strong></span>
                    </div>

                    {/* Range Selector */}
                    {onRangeChange && (
                        <div style={{ display: 'flex', background: 'var(--pul-color-background-subtle, #f3f4f6)', borderRadius: '6px', padding: '2px' }}>
                            {['1h', '24h', '7d'].map(r => (
                                <button
                                    key={r}
                                    type="button"
                                    onClick={() => onRangeChange(r)}
                                    style={{
                                        border: 'none',
                                        background: range === r ? 'var(--pul-color-background-surface, #ffffff)' : 'transparent',
                                        color: range === r ? 'var(--pul-color-text-primary, #111827)' : 'var(--pul-color-text-muted, #6b7280)',
                                        fontWeight: range === r ? 600 : 400,
                                        fontSize: '11px',
                                        padding: '3px 8px',
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
                <div style={{ position: 'relative', width: '100%', height: `${height}px` }}>
                    <svg
                        viewBox={`0 0 ${chartPoints.w} ${chartPoints.h}`}
                        preserveAspectRatio="none"
                        style={{ width: '100%', height: '100%', overflow: 'visible' }}
                    >
                        <defs>
                            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor={color} stopOpacity="0.28" />
                                <stop offset="100%" stopColor={color} stopOpacity="0.02" />
                            </linearGradient>
                        </defs>

                        {/* Grid lines */}
                        <line x1="10" y1={chartPoints.padY} x2="490" y2={chartPoints.padY} stroke="currentColor" strokeOpacity="0.06" strokeDasharray="3 3" />
                        <line x1="10" y1={chartPoints.padY + chartPoints.innerH / 2} x2="490" y2={chartPoints.padY + chartPoints.innerH / 2} stroke="currentColor" strokeOpacity="0.06" strokeDasharray="3 3" />
                        <line x1="10" y1={chartPoints.padY + chartPoints.innerH} x2="490" y2={chartPoints.padY + chartPoints.innerH} stroke="currentColor" strokeOpacity="0.1" />

                        {/* Area */}
                        <path d={chartPoints.areaPath} fill={`url(#${gradientId})`} />

                        {/* Line */}
                        <path d={chartPoints.linePath} fill="none" stroke={color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />

                        {/* Hover active point indicator */}
                        {hoverIndex !== null && chartPoints.pts[hoverIndex] && (
                            <g>
                                <line
                                    x1={chartPoints.pts[hoverIndex].x}
                                    y1={chartPoints.padY}
                                    x2={chartPoints.pts[hoverIndex].x}
                                    y2={chartPoints.padY + chartPoints.innerH}
                                    stroke={color}
                                    strokeWidth="1.2"
                                    strokeDasharray="2 2"
                                />
                                <circle
                                    cx={chartPoints.pts[hoverIndex].x}
                                    cy={chartPoints.pts[hoverIndex].y}
                                    r="4.5"
                                    fill={color}
                                    stroke="#ffffff"
                                    strokeWidth="2"
                                />
                            </g>
                        )}
                    </svg>

                    {/* Interactive overlay for mouse move */}
                    <div
                        style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', cursor: 'crosshair' }}
                        onMouseMove={e => {
                            const rect = e.currentTarget.getBoundingClientRect();
                            const xRatio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                            const idx = Math.round(xRatio * (chartPoints.pts.length - 1));
                            setHoverIndex(idx);
                        }}
                        onMouseLeave={() => setHoverIndex(null)}
                    />

                    {/* Hover tooltip */}
                    {hoverIndex !== null && chartPoints.pts[hoverIndex] && (
                        <div style={{
                            position: 'absolute',
                            left: `${Math.min(85, Math.max(15, (chartPoints.pts[hoverIndex].x / chartPoints.w) * 100))}%`,
                            top: '4px',
                            transform: 'translateX(-50%)',
                            background: 'rgba(17, 24, 39, 0.92)',
                            color: '#ffffff',
                            padding: '4px 8px',
                            borderRadius: '4px',
                            fontSize: '11px',
                            pointerEvents: 'none',
                            whiteSpace: 'nowrap',
                            boxShadow: '0 2px 6px rgba(0,0,0,0.2)',
                            zIndex: 10,
                        }}>
                            <span style={{ opacity: 0.75, marginRight: '6px' }}>{formatTime(chartPoints.pts[hoverIndex].time)}</span>
                            <strong>{format(chartPoints.pts[hoverIndex].value)}</strong>
                        </div>
                    )}
                </div>
            ) : (
                <div style={{ height: `${height}px`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--pul-color-text-muted, #9ca3af)', fontSize: '12px' }}>
                    No metric data available yet
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
    })),
    unit: PropTypes.string,
    color: PropTypes.string,
    range: PropTypes.string,
    onRangeChange: PropTypes.func,
    formatValue: PropTypes.func,
    height: PropTypes.number,
};

export default MetricChart;
