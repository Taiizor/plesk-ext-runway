<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Brings the services in line with the current state of Plesk. Event object
 * ids are not reliable across Plesk object types, so instead of reacting to a
 * single id, every event triggers a full (cheap) comparison:
 *  - apps of deleted domains, or of domains without web hosting, are removed;
 *  - apps whose domain name, system user or home directory changed are re-applied;
 *  - apps of suspended/disabled domains are stopped, and started again on activation;
 *  - enabled apps that systemd gave up on (start limit hit, e.g. their database was not up yet
 *    after a reboot) are started again, unless the user stopped them.
 * Applications stopped by the user (Stop) stay stopped: re-applies keep the helper's flag.
 * Zero-downtime deployments (docs/DESIGN.md section 12.8): apps-list also converges the slots and
 * pointers of every application (converge: true), and an application is re-applied (without a
 * restart) when the helper's "switchable" or port differs from the stored configuration, so the
 * web server snippet follows the helper.
 * While the root-only test flag /var/lib/runway/pause-reconcile exists (honoured for at most one
 * hour, reported by the helper's apps-list), nothing is changed: tests/helper-smoke.sh uses
 * a domain id that Plesk does not know.
 */
class Modules_Runway_Reconcile
{
    /**
     * @return array Summary: removed, reapplied, errors, paused
     * @throws Modules_Runway_Exception When the helper cannot be reached
     */
    public static function run()
    {
        $summary = ['removed' => [], 'reapplied' => [], 'recovered' => [], 'errors' => [], 'paused' => false];
        $result = Modules_Runway_Helper::call('apps-list', ['converge' => true]);
        if (!empty($result['reconcile_paused'])) {
            $summary['paused'] = true;
            Modules_Runway_Log::info('Reconcile skipped: paused by /var/lib/runway/pause-reconcile (test flag)');
            return $summary;
        }
        if (empty($result['apps'])) {
            return $summary;
        }

        $domains = [];
        foreach (pm_Domain::getAllDomains() as $domain) {
            $domains[(int)$domain->getId()] = $domain;
        }

        foreach ($result['apps'] as $app) {
            $id = (int)$app['domain_id'];
            try {
                $domain = isset($domains[$id]) ? $domains[$id] : null;
                if (!$domain || !$domain->hasHosting()) {
                    Modules_Runway_Helper::call('app-remove', ['domain_id' => $id]);
                    if ($domain) {
                        $domain->setSetting(Modules_Runway_App::SETTING_KEY, '');
                    }
                    $summary['removed'][] = $id;
                    Modules_Runway_Log::info("Removed the application of domain #{$id} (domain deleted or hosting removed)");
                    continue;
                }

                $model = new Modules_Runway_App($domain);
                $age = time() - (int)(isset($app['updated_epoch']) ? $app['updated_epoch'] : 0);
                if (!$model->isConfigured() && $age < 300) {
                    // Probably being created right now (the panel saves after the helper): leave it.
                    continue;
                }
                if (!$model->isConfigured()) {
                    // The panel no longer knows this app: do not leave an orphaned service behind.
                    Modules_Runway_Helper::call('app-remove', ['domain_id' => $id]);
                    $summary['removed'][] = $id;
                    continue;
                }

                $suspended = !Modules_Runway_App::domainIsActive($domain);
                $identityChanged = !empty($app['home_changed'])
                    || (string)$app['sysuser'] !== (string)$domain->getSysUserLogin();
                $running = in_array((string)$app['active_state'], ['active', 'activating', 'reloading'], true);
                $stored = Modules_Runway_App::storedConfig($domain);
                $switchable = isset($app['switchable']) ? (bool)$app['switchable'] : false;
                $changed = $identityChanged
                    || (string)$app['domain'] !== (string)$domain->getName()
                    || (bool)$app['suspended'] !== $suspended
                    // e.g. an earlier suspension that did not complete: the stored flag says
                    // suspended, but the service still runs.
                    || ($suspended && $running)
                    // Zero-downtime: the snippet must follow the helper (a switch back to the 1.0
                    // unit, a failed save after app-apply, restored domain settings).
                    || $switchable !== !empty($stored['switchable'])
                    || (!$switchable && isset($app['port']) && (int)$app['port'] !== (int)(isset($stored['port']) ? $stored['port'] : 0));
                if ($changed) {
                    $model->apply($identityChanged);
                    $summary['reapplied'][] = $id;
                    Modules_Runway_Log::info('Re-applied the application of ' . $domain->getName() . ' after a domain change');
                } elseif (!$suspended && $model->isEnabled() && !empty($app['enabled']) && empty($app['stopped'])
                    && !empty($app['start_limit_hit'])) {
                    // e.g. its database was not up yet after a reboot: systemd gave up after 10 starts
                    // in 120 s. Try again (never for applications the user stopped).
                    Modules_Runway_Helper::call('app-action', ['domain_id' => $id, 'action' => 'recover']);
                    $summary['recovered'][] = $id;
                    Modules_Runway_Log::info('Restarted the application of ' . $domain->getName() . ' after it hit the start limit');
                }
            } catch (Exception $e) {
                $summary['errors'][] = "#{$id}: " . $e->getMessage();
                Modules_Runway_Log::err("Reconcile of domain #{$id} failed: " . $e->getMessage());
            }
        }
        return $summary;
    }
}
