<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Reacts to domain lifecycle events (delete, rename, hosting change, suspend).
 * Plesk loads this file and expects it to return the listener instance.
 */
class Modules_Runway_EventListener implements EventListener
{
    public function filterActions()
    {
        return [
            'domain_delete',
            'site_delete',
            'subdomain_delete',
            'site_subdomain_delete',
            'phys_hosting_delete',
            'domain_update',
            'site_update',
            'phys_hosting_update',
            'domain_status_update',
            'site_status_update',
            'client_status_update',
            'reseller_status_update',
        ];
    }

    public function handleEvent($objectType, $objectId, $action, $oldValues, $newValues)
    {
        try {
            pm_Context::init('runway');
            Modules_Runway_Reconcile::run();
        } catch (Throwable $e) {
            Modules_Runway_Log::err("Handling event {$action} failed: " . $e->getMessage());
        }
    }
}

return new Modules_Runway_EventListener();
