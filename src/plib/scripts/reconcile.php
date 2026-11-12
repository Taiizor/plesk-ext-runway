<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Scheduled task (every 10 minutes): converges the services with the state of Plesk, then runs
// the update check of the built-in updater (twice a day, when enabled in the settings).

pm_Context::init('runway');

$code = 0;
try {
    $summary = Modules_Runway_Reconcile::run();
    if ($summary['removed'] || $summary['reapplied'] || $summary['recovered'] || $summary['errors']) {
        Modules_Runway_Log::info('Scheduled reconcile: ' . json_encode($summary));
    }
} catch (Exception $e) {
    Modules_Runway_Log::err('Scheduled reconcile failed: ' . $e->getMessage());
    $code = 1;
}
// Never fails the task: errors of the update check are logged by the updater itself.
Modules_Runway_Updater::scheduled();
exit($code);
