<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Adds a permission to service plans / subscriptions so the administrator can
 * decide which customers may run applications with Runway.
 */
class Modules_Runway_Permissions extends pm_Hook_Permissions
{
    public function getPermissions()
    {
        $permissions = [
            Modules_Runway_Access::PERMISSION => [
                'default' => false,
                'place' => self::PLACE_MAIN,
                'name' => pm_Locale::lmsg('permissionName'),
                'description' => pm_Locale::lmsg('permissionDescription'),
            ],
        ];
        foreach (Modules_Runway_Policies::RUNTIMES as $runtime) {
            $permissions['runtime_' . $runtime] = ['default' => true, 'place' => self::PLACE_ADDITIONAL,
                'name' => pm_Locale::lmsg('permissionRuntime', ['runtime' => $runtime]),
                'description' => pm_Locale::lmsg('permissionRuntimeDescription')];
        }
        return $permissions;
    }
}
