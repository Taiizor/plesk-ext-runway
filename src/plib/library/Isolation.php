<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/** Administrator-owned isolation policy; application saves and recovery imports cannot disable it. */
class Modules_Runway_Isolation
{
    public static function call(Modules_Runway_App $app, array $body = [], $write = false)
    {
        if (!$app->isConfigured()) {
            throw new Modules_Runway_Exception(pm_Locale::lmsg('errorNotConfigured'));
        }
        if ($write) {
            Modules_Runway_Access::requireAdmin();
        }
        $payload = [
            'domain_id' => (int)$app->getDomain()->getId(),
            'action' => $write ? 'save' : 'status',
        ];
        if ($write) {
            $payload['options'] = isset($body['options']) ? $body['options'] : null;
        }
        $result = Modules_Runway_Helper::call('isolation', $payload);
        $result['canEdit'] = Modules_Runway_Access::isAdmin();
        return $result;
    }
}
