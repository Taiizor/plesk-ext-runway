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
        return [
            Modules_Runway_Access::PERMISSION => [
                'default' => false,
                'place' => self::PLACE_MAIN,
                'name' => pm_Locale::lmsg('permissionName'),
                'description' => pm_Locale::lmsg('permissionDescription'),
            ],
        ];
    }
}
