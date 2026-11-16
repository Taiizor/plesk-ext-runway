// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Grid, GridCol, useTranslate } from '@plesk/plesk-ext-sdk';
import MetricChart from '../components/MetricChart';
import StatusPanel from './StatusPanel';
import { formatByteRate } from '../lib/format';

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
    const [metrics, setMetrics] = useState({ cpu: [], mem: [], read: [], write: [], net: [] });
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
                const net = [];

                res.metrics.forEach(m => {
                    cpu.push({ time: m.time, value: m.cpu || 0 });
                    mem.push({ time: m.time, value: (m.memory_used ?? m.memory ?? 0) / (1024 * 1024) }); // bytes to MiB
                    read.push({ time: m.time, value: m.disk_read_rate ?? null });
                    write.push({ time: m.time, value: m.disk_write_rate ?? null });
                    net.push({ time: m.time, value: (m.net_rate || 0) / 1024 }); // bytes/s to KB/s
                });

                setMetrics({ cpu, mem, read, write, net });
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
                <Grid xs={1} lg={2} gap="md" style={{ marginBottom: '16px' }}>
                    <GridCol>
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
                    </GridCol>
                    <GridCol>
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
                    </GridCol>
                    <GridCol>
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
                    </GridCol>
                    <GridCol>
                        <MetricChart
                            {...metricWindow}
                            title={translate('Domain.metricsNetwork')}
                            data={metrics.net}
                            latestValue={latest ? latest.net_rate / 1024 : undefined}
                            unit="KB/s"
                            color="#f59e0b"
                            range={range}
                            onRangeChange={setRange}
                            height={140}
                        />
                    </GridCol>
                </Grid>
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
