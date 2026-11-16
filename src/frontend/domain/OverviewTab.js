// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { useTranslate } from '@plesk/plesk-ext-sdk';
import MetricChart from '../components/MetricChart';
import StatusPanel from './StatusPanel';
import { formatByteRate } from '../lib/format';

const metricGridCss = `
    .runway-metrics-grid {
        display: grid;
        grid-template-columns: minmax(0, 1fr);
        gap: 16px;
        margin-bottom: 16px;
        align-items: stretch;
    }
    @media (min-width: 1200px) {
        .runway-metrics-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
`;

const OverviewTab = ({
    api,
    siteId,
    data,
    status,
    statusError,
    statusUpdatedAt,
    busyOp,
    onControl,
    onStop,
}) => {
    const translate = useTranslate();
    const [range, setRange] = useState('1h');
    const [metrics, setMetrics] = useState({ cpu: [], mem: [], read: [], write: [], download: [], upload: [] });
    const [metricWindow, setMetricWindow] = useState({});
    const [latest, setLatest] = useState(null);

    useEffect(() => {
        if (!siteId || !data || !data.configured) return;

        let active = true;
        const fetchMetrics = () => {
            api.get('app/metrics', { site_id: siteId, range }).then(res => {
                if (!active || !res || !Array.isArray(res.metrics)) return;
                const cpu = [];
                const mem = [];
                const read = [];
                const write = [];
                const download = [];
                const upload = [];

                res.metrics.forEach(m => {
                    cpu.push({ time: m.time, value: m.cpu || 0, peak: m.cpu_peak });
                    mem.push({ time: m.time, value: (m.memory_used ?? m.memory ?? 0) / (1024 * 1024),
                        peak: (m.memory_used_peak ?? m.memory_peak ?? m.memory_used ?? m.memory ?? 0) / (1024 * 1024) }); // bytes to MiB
                    read.push({ time: m.time, value: m.disk_read_rate ?? null, peak: m.disk_read_rate_peak });
                    write.push({ time: m.time, value: m.disk_write_rate ?? null, peak: m.disk_write_rate_peak });
                    download.push({ time: m.time, value: m.net_rx_rate ?? null, peak: m.net_rx_rate_peak });
                    upload.push({ time: m.time, value: m.net_tx_rate ?? null, peak: m.net_tx_rate_peak });
                });

                setMetrics({ cpu, mem, read, write, download, upload });
                setMetricWindow({ startTime: res.start_time, endTime: res.end_time, step: res.step });
                setLatest(res.latest || null);
            }).catch(() => {});
        };

        fetchMetrics();
        const interval = setInterval(fetchMetrics, range === '1h' ? 15000 : 60000);
        return () => {
            active = false;
            clearInterval(interval);
        };
    }, [api, siteId, range, data && data.configured]); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div>
            {data && data.configured && (
                <div className="runway-metrics-grid">
                    <style>{metricGridCss}</style>
                    <MetricChart
                        {...metricWindow}
                        title={translate('Domain.metricsCpu')}
                        data={metrics.cpu}
                        latestValue={latest ? latest.cpu_percent : undefined}
                        unit="%"
                        color="#0070f3"
                        range={range}
                        onRangeChange={setRange}
                        height={140}
                    />
                    <MetricChart
                        {...metricWindow}
                        title={translate('Domain.metricsMemory')}
                        data={metrics.mem}
                        latestValue={latest ? (latest.memory_used_bytes ?? latest.memory_bytes ?? 0) / (1024 * 1024) : undefined}
                        unit="MiB"
                        color="#10b981"
                        range={range}
                        onRangeChange={setRange}
                        height={140}
                    />
                    <MetricChart
                        {...metricWindow}
                        title={translate('Domain.metricsDiskIO')}
                        series={[
                            { key: 'read', label: translate('Domain.metricsRead'), color: '#8b5cf6', data: metrics.read,
                                latestValue: latest ? (latest.disk_read_rate ?? null) : null },
                            { key: 'write', label: translate('Domain.metricsWrite'), color: '#06b6d4', data: metrics.write,
                                latestValue: latest ? (latest.disk_write_rate ?? null) : null },
                        ]}
                        formatValue={formatByteRate}
                        range={range}
                        onRangeChange={setRange}
                        height={140}
                    />
                    <MetricChart
                        {...metricWindow}
                        title={translate('Domain.metricsNetwork')}
                        series={[
                            { key: 'download', label: translate('Domain.metricsDownload'), color: '#f59e0b', data: metrics.download,
                                latestValue: latest ? (latest.net_rx_rate ?? null) : null },
                            { key: 'upload', label: translate('Domain.metricsUpload'), color: '#ec4899', data: metrics.upload,
                                latestValue: latest ? (latest.net_tx_rate ?? null) : null },
                        ]}
                        formatValue={formatByteRate}
                        range={range}
                        onRangeChange={setRange}
                        height={140}
                    />
                </div>
            )}

            <StatusPanel
                data={data}
                status={status}
                error={statusError}
                updatedAt={statusUpdatedAt}
                busyOp={busyOp}
                onControl={onControl}
                onStop={onStop}
            />
        </div>
    );
};

OverviewTab.propTypes = {
    api: PropTypes.object.isRequired,
    siteId: PropTypes.string.isRequired,
    data: PropTypes.object.isRequired,
    status: PropTypes.object,
    statusError: PropTypes.string,
    statusUpdatedAt: PropTypes.string,
    busyOp: PropTypes.string,
    onControl: PropTypes.func.isRequired,
    onStop: PropTypes.func.isRequired,
};

export default OverviewTab;
