<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/** Domain-authorized bridge for optional operations; secrets and release records stay in the helper. */
class Modules_Runway_Operations
{
    public static function call(Modules_Runway_App $app, array $body = [])
    {
        if (!$app->isConfigured()) {
            throw new Modules_Runway_Exception(pm_Locale::lmsg('errorNotConfigured'));
        }
        $action = isset($body['action']) && is_string($body['action']) ? $body['action'] : 'status';
        if (!in_array($action, ['status', 'save', 'history', 'diagnostics', 'rollback', 'export', 'import', 'clear-releases', 'test-notification'], true)) {
            throw new Modules_Runway_Exception(pm_Locale::lmsg('errorInvalidOperation'));
        }
        if ($action === 'import') {
            return self::restore($app, isset($body['backup']) && is_array($body['backup']) ? $body['backup'] : [],
                isset($body['restore_secrets']) && $body['restore_secrets'] === true, false);
        }
        $payload = array_intersect_key($body, array_flip(['action', 'options', 'id']));
        $payload['action'] = $action;
        $payload['domain_id'] = (int)$app->getDomain()->getId();
        $result = Modules_Runway_Helper::call('operations', $payload);
        if ($action === 'export') {
            $result['bundle']['application'] = $app->config();
        }
        if ($action === 'status' || $action === 'save') {
            $result['policy'] = Modules_Runway_Policies::describe($app->getDomain());
        }
        if ($action === 'save') {
            $app->getDomain()->setSetting('runwayRecoveryBackup', !empty($result['options']['backup']) ? '1' : '0');
        }
        return $result;
    }

    public static function restore(Modules_Runway_App $app, array $bundle, $secrets, $native)
    {
        if (!isset($bundle['application']) || !is_array($bundle['application']) || strlen((string)json_encode($bundle)) > 512 * 1024) {
            throw new Modules_Runway_Exception(pm_Locale::lmsg('errorInvalidValue'));
        }
        $domainId = (int)$app->getDomain()->getId();
        $validation = ['domain_id' => $domainId, 'action' => 'validate-import', 'backup' => $bundle, 'restore_secrets' => (bool)$secrets];
        // Validate the whole recovery configuration before applying any application setting.
        Modules_Runway_Helper::call('operations', $validation);
        $values = $bundle['application'];
        unset($values['port'], $values['switchable'], $values['documentRoot'], $values['memoryMb'], $values['cpuPercent'], $values['tasks'], $values['env']);
        if ($native) {
            // Plesk supplies the destination identity. Old ports, units and live-slot pointers are never restored.
            $values['enabled'] = !empty($bundle['operations']['restore_start']) && !empty($values['enabled']);
        }
        $errors = $app->update($values, $native ? false : Modules_Runway_Access::isAdmin());
        if ($errors) {
            throw new Modules_Runway_ValidationException($errors);
        }
        if ($native) {
            $app->prepareRecovery();
            $app->apply(false, false);
            Modules_Runway_Helper::call('operations', ['domain_id' => $domainId, 'action' => 'save', 'options' => ['backup' => true]]);
            Modules_Runway_Helper::call('operations', $validation);
        }
        $result = Modules_Runway_Helper::call('operations', array_merge($validation, ['action' => 'import']));
        $app->getDomain()->setSetting('runwayRecoveryBackup', !empty($bundle['operations']['backup']) ? '1' : '0');
        $start = $native && !empty($bundle['operations']['restore_start']) && $app->isEnabled();
        $app->apply(false, $start, $start);
        return $result + ['requiresStart' => !$start];
    }
}
