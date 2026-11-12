<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Built-in updater (docs/DESIGN.md sections 6 and 7). Runway is distributed through GitHub
 * releases, not the Plesk extension catalog, so Plesk never offers updates for it. The root
 * helper checks releases/latest of the repository (update-check, cached for 12 hours) and
 * upgrades the extension in the administrator's background job (update-install, job title key
 * "self_update"). The scheduled task checks twice a day while the server setting updateCheck
 * is on and installs automatically when updateAuto is on.
 */
class Modules_Runway_Updater
{
    /** Version of an update as the administrator saw it: X.Y.Z-R */
    const VERSION_PATTERN = '/^\d{1,6}\.\d{1,6}\.\d{1,6}-\d{1,6}$/';

    /**
     * Installed version, the result of the last check and the admin job, plus the two
     * settings. No network access.
     *
     * @return array
     * @throws Modules_Runway_Exception
     */
    public static function status()
    {
        return self::describe(Modules_Runway_Helper::call('update-status'));
    }

    /**
     * Asks GitHub for the latest release (a forced check within 60 seconds of the previous one
     * answers from the cache). A failed check is reported in "error", not as an exception.
     *
     * @param bool $force
     * @return array status() plus "checked" (whether the network was used)
     * @throws Modules_Runway_Exception
     */
    public static function check($force)
    {
        $result = Modules_Runway_Helper::call('update-check', ['force' => (bool)$force, 'auto_install' => false]);
        return self::describe($result) + ['checked' => !empty($result['checked'])];
    }

    /**
     * Starts the self-update job for the version the administrator saw.
     *
     * @param string $version X.Y.Z-R
     * @return array {job, version}
     * @throws Modules_Runway_Exception
     */
    public static function install($version)
    {
        return Modules_Runway_Helper::call('update-install', ['version' => (string)$version]);
    }

    /**
     * Scheduled task (every 10 minutes): checks while updateCheck is on (the helper uses the
     * network at most every 12 hours) and installs an available update when updateAuto is on.
     * Never throws: failures are logged.
     */
    public static function scheduled()
    {
        try {
            if (!Modules_Runway_Settings::get('updateCheck')) {
                return;
            }
            $auto = (bool)Modules_Runway_Settings::get('updateAuto');
            $result = Modules_Runway_Helper::call('update-check', ['force' => false, 'auto_install' => $auto]);
            $latest = isset($result['latest']['full']) ? (string)$result['latest']['full'] : '';
            if (!empty($result['checked'])) {
                if (!empty($result['error'])) {
                    Modules_Runway_Log::err('Update check failed: ' . $result['error']);
                } elseif (!empty($result['available'])) {
                    Modules_Runway_Log::info('Update check: Runway ' . $latest . ' is available (installed: '
                        . (isset($result['installed']) ? $result['installed'] : '?') . ')');
                }
            }
            if (!empty($result['started'])) {
                Modules_Runway_Log::info('Automatic update to Runway ' . $latest . ' started');
            } elseif (!empty($result['auto_error'])) {
                Modules_Runway_Log::err('Automatic update to Runway ' . $latest . ' could not be started: ' . $result['auto_error']);
            }
        } catch (Throwable $e) {
            Modules_Runway_Log::err('Update check failed: ' . $e->getMessage());
        }
    }

    /**
     * API shape of the helper's update-status / update-check answer.
     *
     * @param array $result
     * @return array
     */
    private static function describe(array $result)
    {
        $latest = isset($result['latest']) && is_array($result['latest']) ? $result['latest'] : null;
        return [
            'installed' => isset($result['installed']) ? (string)$result['installed'] : '',
            'latest' => $latest ? [
                'version' => isset($latest['version']) ? (string)$latest['version'] : '',
                'release' => isset($latest['release']) ? (int)$latest['release'] : 0,
                'full' => isset($latest['full']) ? (string)$latest['full'] : '',
                'tag' => isset($latest['tag']) ? (string)$latest['tag'] : '',
                'htmlUrl' => isset($latest['html_url']) ? (string)$latest['html_url'] : null,
                'publishedAt' => isset($latest['published_at']) ? (string)$latest['published_at'] : null,
            ] : null,
            'available' => !empty($result['available']),
            'checkedAt' => isset($result['checked_at']) ? (string)$result['checked_at'] : null,
            'error' => isset($result['error']) && $result['error'] !== '' ? (string)$result['error'] : null,
            'updateSource' => isset($result['update_source']) ? (string)$result['update_source'] : null,
            'lastFailedVersion' => isset($result['last_failed_version']) ? (string)$result['last_failed_version'] : null,
            'job' => isset($result['job']) && is_array($result['job']) ? $result['job'] : null,
            'updateCheck' => (bool)Modules_Runway_Settings::get('updateCheck'),
            'updateAuto' => (bool)Modules_Runway_Settings::get('updateAuto'),
        ];
    }
}
