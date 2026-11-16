// Copyright 2026 Taiizor. Licensed under the MIT License.

import { afterEach, beforeEach, expect, mock, test } from 'bun:test';
import { JSDOM } from 'jsdom';
import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { formatByteRate } from '../../src/frontend/lib/format';

mock.module('@plesk/plesk-ext-sdk', () => ({
    useTranslate: () => key => key,
    Grid: ({ children }) => createElement('div', null, children),
    GridCol: ({ children }) => createElement('div', null, children),
    Alert: ({ children }) => createElement('div', { role: 'alert' }, children),
    Button: ({ children }) => createElement('button', null, children),
    Label: ({ children }) => createElement('span', null, children),
    Panel: ({ children }) => createElement('section', null, children),
    Text: ({ children }) => createElement('span', null, children),
    Translate: ({ content, params }) => createElement('span', null, content, params && params.time),
}));
const { default: MetricChart } = await import('../../src/frontend/components/MetricChart');
const { default: OverviewTab } = await import('../../src/frontend/domain/OverviewTab');

const original = {
    window: globalThis.window,
    document: globalThis.document,
    IS_REACT_ACT_ENVIRONMENT: globalThis.IS_REACT_ACT_ENVIRONMENT,
};
let dom;
let root;

beforeEach(() => {
    dom = new JSDOM('<!doctype html><div id="root"></div>', { pretendToBeVisual: true });
    globalThis.window = dom.window;
    globalThis.document = dom.window.document;
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    root = createRoot(document.getElementById('root'));
});

afterEach(async () => {
    await act(async () => root.unmount());
    dom.window.close();
    Object.assign(globalThis, original);
});

const render = async props => {
    await act(async () => root.render(createElement(MetricChart, { title: 'CPU', unit: '%', ...props })));
    return document.getElementById('root');
};

const sparseSamples = [
    { time: 3600, value: 1 },
    { time: 7200, value: 2 },
    { time: 46800, value: 3 },
];

test('timestamps determine positions and an eleven-hour gap is not connected', async () => {
    const chart = await render({ data: sparseSamples, startTime: 0, endTime: 50400, step: 3600, range: '7d' });
    const path = chart.querySelector('path[stroke]').getAttribute('d');
    const positions = Array.from(path.matchAll(/[ML] ([\d.]+) [\d.]+/g), match => Number(match[1]));
    expect(positions).toHaveLength(3);
    expect((positions[2] - positions[1]) / (positions[1] - positions[0])).toBeCloseTo(11, 1);
    expect(path.match(/M /g)).toHaveLength(2);
    expect(path.match(/L /g)).toHaveLength(1);
    expect(chart.querySelectorAll('svg > circle')).toHaveLength(1);
});

test('a single real sample is shown as a point without inventing a history', async () => {
    const chart = await render({ data: [{ time: 3600, value: 5 }], startTime: 0, endTime: 3600 });
    expect(chart.querySelectorAll('svg > circle')).toHaveLength(1);
    expect(chart.querySelector('svg > circle').getAttribute('cx')).toBe('490');
    expect(chart.querySelector('path[stroke]').getAttribute('d')).not.toContain('L ');
    expect(chart.textContent).not.toContain('Domain.metricsEmpty');
});

test('hover selects the nearest timestamp instead of the nearest array index', async () => {
    const chart = await render({ data: sparseSamples, startTime: 0, endTime: 50400, step: 3600 });
    const overlay = chart.querySelector('[style*="crosshair"]');
    overlay.getBoundingClientRect = () => ({ left: 0, width: 500 });
    await act(async () => overlay.dispatchEvent(new dom.window.MouseEvent('mousemove', { clientX: 80, bubbles: true })));
    expect(chart.querySelector('[style*="z-index"] strong').textContent).toBe('2 %');
});

test('current measurement is distinct from the bucket average and empty data is not zero usage', async () => {
    let chart = await render({ data: [{ time: 3600, value: 2 }], latestValue: 9 });
    expect(chart.textContent).toContain('9 %');
    expect(chart.querySelectorAll('strong')[0].textContent).toBe('2 %');
    chart = await render({ data: [] });
    expect(chart.textContent).toContain('Domain.metricsEmpty');
    expect(chart.textContent).not.toContain('0 %');
});

test('time range leaves unmeasured history blank and discards invalid numeric samples', async () => {
    const chart = await render({ data: [{ time: 3600, value: 3 }, { time: 0, value: NaN }], range: '1h', endTime: 3600 });
    expect(chart.querySelector('svg > circle').getAttribute('cx')).toBe('490');
    expect(chart.querySelector('svg').innerHTML).not.toContain('NaN');
    expect(chart.querySelectorAll('strong')[0].textContent).toBe('3 %');
});

test('read and write share a time and value scale, and hover shows both rates', async () => {
    const chart = await render({ title: 'Disk I/O', startTime: 0, endTime: 60, formatValue: formatByteRate, series: [
        { key: 'read', label: 'Read', color: '#8b5cf6', data: [{ time: 0, value: 1024 }, { time: 60, value: 2048 }], latestValue: 2048 },
        { key: 'write', label: 'Write', color: '#06b6d4', data: [{ time: 0, value: 1048576 }, { time: 60, value: 2097152 }], latestValue: 2097152 },
    ] });
    const paths = chart.querySelectorAll('path[stroke]');
    expect(paths).toHaveLength(2);
    expect(paths[0].getAttribute('stroke')).toBe('#8b5cf6');
    expect(paths[1].getAttribute('stroke')).toBe('#06b6d4');
    const readY = Number(paths[0].getAttribute('d').match(/M [\d.]+ ([\d.]+)/)[1]);
    const writeY = Number(paths[1].getAttribute('d').match(/M [\d.]+ ([\d.]+)/)[1]);
    expect(readY).toBeGreaterThan(writeY);
    expect(chart.textContent).toContain('Read2.0 KiB/s');
    expect(chart.textContent).toContain('Write2.0 MiB/s');
    const overlay = chart.querySelector('[style*="crosshair"]');
    overlay.getBoundingClientRect = () => ({ left: 0, width: 500 });
    await act(async () => overlay.dispatchEvent(new dom.window.MouseEvent('mousemove', { clientX: 490, bubbles: true })));
    const tooltip = chart.querySelector('[style*="z-index"]');
    expect(tooltip.textContent).toContain('Read2.0 KiB/s');
    expect(tooltip.textContent).toContain('Write2.0 MiB/s');
    expect(tooltip.querySelectorAll('strong')).toHaveLength(2);
});

test('missing I/O samples stay blank while measured zero throughput is retained', async () => {
    const chart = await render({ title: 'Disk I/O', startTime: 0, endTime: 180, formatValue: formatByteRate, series: [
        { key: 'read', label: 'Read', color: '#8b5cf6', data: [
            { time: 0, value: 100 }, { time: 60, value: null }, { time: 120, value: 0 }, { time: 180, value: null },
        ], latestValue: null },
        { key: 'write', label: 'Write', color: '#06b6d4', data: [{ time: 120, value: 1024 }], latestValue: 1024 },
    ] });
    expect(chart.textContent).toContain('Read—');
    expect(chart.textContent).toContain('Write1.0 KiB/s');
    const readPath = chart.querySelector('path[stroke="#8b5cf6"]').getAttribute('d');
    expect(readPath.match(/M /g)).toHaveLength(2);
    expect(readPath).not.toContain('L ');
    expect(chart.querySelectorAll('svg > circle')).toHaveLength(3);
});

test('throughput formatting distinguishes unknown counters, zero and binary units', () => {
    expect(formatByteRate(null)).toBe('—');
    expect(formatByteRate(undefined)).toBe('—');
    expect(formatByteRate(-1)).toBe('—');
    expect(formatByteRate(0)).toBe('0 B/s');
    expect(formatByteRate(1536)).toBe('1.5 KiB/s');
    expect(formatByteRate(1048576)).toBe('1.0 MiB/s');
});

test('application overview keeps four charts and plots I/O rates instead of capacity', async () => {
    const api = { get: mock(() => Promise.resolve({
        start_time: 0, end_time: 60, step: 60,
        metrics: [{ time: 60, cpu: 1, memory_used: 1048576, disk: 1099511627776, net_rate: 1024,
            disk_read_rate: 2048, disk_write_rate: 4096 }],
        latest: { cpu_percent: 1, memory_used_bytes: 1048576, disk_bytes: 1099511627776, net_rate: 1024,
            disk_read_rate: 2048, disk_write_rate: 4096 },
    })) };
    await act(async () => root.render(createElement(OverviewTab, {
        api, siteId: '17', data: { configured: true }, status: { running: true }, onControl: mock(), onStop: mock(),
    })));
    expect(api.get).toHaveBeenCalledWith('app/metrics', { site_id: '17', range: '1h' });
    expect(document.querySelectorAll('svg')).toHaveLength(4);
    const diskChart = document.querySelectorAll('svg')[2];
    expect(diskChart.querySelectorAll('path[stroke]')).toHaveLength(2);
    expect(document.body.textContent).toContain('Domain.metricsDiskIO');
    expect(document.body.textContent).toContain('Domain.metricsRead2.0 KiB/s');
    expect(document.body.textContent).toContain('Domain.metricsWrite4.0 KiB/s');
    expect(document.body.textContent).not.toContain('TiB');
});
