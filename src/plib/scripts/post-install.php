<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Runs after installation and after every upgrade ("upgrade <oldVersion>" in $argv).

pm_Context::init('runway');

try {
    // Creates the directory layout and re-renders the units, environment files and socket
    // directories of existing apps, so template changes of a new version take effect (running
    // services pick them up at their next restart).
    $result = Modules_Runway_Helper::call('install');
} catch (Exception $e) {
    echo 'Runway: the privileged helper could not be set up: ' . $e->getMessage() . "\n";
    exit(1);
}
// Applications that could not be re-rendered keep their previous files: tell the administrator.
foreach (isset($result['errors']) && is_array($result['errors']) ? $result['errors'] : [] as $error) {
    echo 'Runway: warning: ' . $error . "\n";
    Modules_Runway_Log::err('Re-applying an application after the installation failed: ' . $error);
}

// Periodic reconcile as a safety net for missed domain events (suspension, deletion, ...).
// Registered first and on its own, so a failing step below can never leave it out.
try {
    $scheduled = false;
    foreach (pm_Scheduler::getInstance()->listTasks() as $task) {
        if ($task->getCmd() === 'reconcile.php') {
            $scheduled = true;
        }
    }
    if (!$scheduled) {
        $task = new pm_Scheduler_Task();
        $task->setSchedule(pm_Scheduler::$EVERY_10_MIN);
        $task->setCmd('reconcile.php');
        pm_Scheduler::getInstance()->putTask($task);
    }
} catch (Exception $e) {
    echo 'Runway: warning: the scheduled reconcile task could not be registered: ' . $e->getMessage() . "\n";
    Modules_Runway_Log::err('Registering the scheduled reconcile task failed: ' . $e->getMessage());
}

try {
    Modules_Runway_Reconcile::run();
} catch (Exception $e) {
    // Do not fail the installation for this; the scheduled task retries it.
    echo 'Runway: warning: ' . $e->getMessage() . "\n";
}

// Regenerate the web server configuration of domains that have an enabled app (the proxy
// snippet may have changed between versions). One broken vhost must not stop the others.
$domains = [];
try {
    $domains = pm_Domain::getAllDomains();
} catch (Exception $e) {
    echo 'Runway: warning: ' . $e->getMessage() . "\n";
}
foreach ($domains as $domain) {
    try {
        if (Modules_Runway_App::proxyTarget($domain)) {
            Modules_Runway_WebConfig::reconfigure($domain);
        }
    } catch (Exception $e) {
        echo 'Runway: warning: ' . $domain->getName() . ': ' . $e->getMessage() . "\n";
        Modules_Runway_Log::err('Regenerating the web server configuration of ' . $domain->getName() . ' failed: ' . $e->getMessage());
    }
}

exit(0);
