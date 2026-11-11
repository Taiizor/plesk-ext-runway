<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Stops and removes every application service, the toolchains and all state.
// Application files in the subscriptions are NOT touched.

pm_Context::init('runway');

try {
    pm_Scheduler::getInstance()->removeAllTasks();
} catch (Exception $e) {
    echo 'Runway: warning: ' . $e->getMessage() . "\n";
}

$domains = [];
try {
    foreach (pm_Domain::getAllDomains() as $domain) {
        // Every configured domain (also disabled or suspended ones) loses its settings below.
        if ($domain->getSetting(Modules_Runway_App::SETTING_KEY, '') !== '') {
            $domains[] = $domain;
        }
    }
} catch (Exception $e) {
    echo 'Runway: warning: ' . $e->getMessage() . "\n";
}

try {
    Modules_Runway_Helper::call('uninstall', ['keep_toolchains' => false]);
} catch (Exception $e) {
    // Never block the uninstallation; report what could not be cleaned up.
    echo 'Runway: warning: cleanup failed: ' . $e->getMessage() . "\n";
}

// Remove the proxy snippets: clear the setting first so the hook returns nothing.
foreach ($domains as $domain) {
    try {
        $domain->setSetting(Modules_Runway_App::SETTING_KEY, '');
        Modules_Runway_WebConfig::reconfigure($domain);
    } catch (Exception $e) {
        echo 'Runway: warning: ' . $domain->getName() . ': ' . $e->getMessage() . "\n";
    }
}

exit(0);
