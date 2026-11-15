<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/** Plesk handles content backups; this hook adds opt-in recovery metadata for the root helper. */
class Modules_Runway_Backup_Domain extends pm_Hook_Backup_Domain
{
    public function backup(pm_Domain $domain)
    {
        $app = new Modules_Runway_App($domain);
        if (!$app->isConfigured() || (string)$domain->getSetting('runwayRecoveryBackup', '0') !== '1') {
            return ['', [], [], []];
        }
        $status = Modules_Runway_Operations::call($app);
        if (empty($status['options']['backup'])) {
            return ['', [], [], []];
        }
        $result = Modules_Runway_Operations::call($app, ['action' => 'export']);
        // No second archive of application/shared files: Plesk's normal content backup owns them.
        return [json_encode($result['bundle'], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), [], [], []];
    }

    public function restore(pm_Domain $domain, $pleskVersion, $extVersion, $config, $contentDir)
    {
        if ($config === '') {
            return;
        }
        if (!is_string($config) || strlen($config) > 512 * 1024) {
            throw new Modules_Runway_Exception('Invalid Runway recovery data.');
        }
        $bundle = json_decode($config, true);
        if (!is_array($bundle)) {
            throw new Modules_Runway_Exception('Invalid Runway recovery data.');
        }
        Modules_Runway_Operations::restore(new Modules_Runway_App($domain), $bundle,
            !empty($bundle['environment_included']), true);
    }
}
