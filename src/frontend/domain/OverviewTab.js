// Copyright 2026 Taiizor. Licensed under the MIT License.

import { createElement, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Grid, GridCol } from '@plesk/plesk-ext-sdk';
import MetricChart from '../components/MetricChart';
import StatusPanel from './StatusPanel';

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
    const [range, setRange] = useState('1h');
    const [metrics, setMetrics] = useState({ cpu: [], mem: [], disk: [], net: [] });

    useEffect(() => {
        if (!siteId || !data || !data.configured) return;

        let active = true;
        const fetchMetrics = () => {
            api.get('app/metrics', { site_id: siteId, range }).then(res => {
                if (!active || !res || !Array.isArray(res.metrics)) return;
                const cpu = [];
                const mem = [];
                const disk = [];
                const net = [];

                res.metrics.forEach(m => {
                    cpu.push({ time: m.time, value: m.cpu || 0 });
                    mem.push({ time: m.time, value: (m.memory || 0) / (1024 * 1024) }); // bytes to MiB
                    disk.push({ time: m.time, value: (m.disk || 0) / (1024 * 1024) }); // bytes to MiB
                    net.push({ time: m.time, value: (m.net_rate || 0) / 1024 }); // bytes/s to KB/s
                });

                setMetrics({ cpu, mem, disk, net });
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
                            title="CPU Usage"
                            data={metrics.cpu}
                            unit="%"
                            color="#0070f3"
                            range={range}
                            onRangeChange={setRange}
                            height={140}
                        />
                    </GridCol>
                    <GridCol>
                        <MetricChart
                            title="Memory Usage"
                            data={metrics.mem}
                            unit="MiB"
                            color="#10b981"
                            range={range}
                            onRangeChange={setRange}
                            height={140}
                        />
                    </GridCol>
                    <GridCol>
                        <MetricChart
                            title="Disk Usage"
                            data={metrics.disk}
                            unit="MiB"
                            color="#8b5cf6"
                            range={range}
                            onRangeChange={setRange}
                            height={140}
                        />
                    </GridCol>
                    <GridCol>
                        <MetricChart
                            title="Network Traffic"
                            data={metrics.net}
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
