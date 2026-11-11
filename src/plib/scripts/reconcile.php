<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Scheduled task (every 10 minutes): converges the services with the state of Plesk.

pm_Context::init('runway');

try {
    $summary = Modules_Runway_Reconcile::run();
    if ($summary['removed'] || $summary['reapplied'] || $summary['recovered'] || $summary['errors']) {
        Modules_Runway_Log::info('Scheduled reconcile: ' . json_encode($summary));
    }
} catch (Exception $e) {
    Modules_Runway_Log::err('Scheduled reconcile failed: ' . $e->getMessage());
    exit(1);
}
exit(0);
