<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Server-wide settings of the extension (managed by the administrator).
 * Every setting is an integer with an allowed range.
 */
class Modules_Runway_Settings
{
    private static $defaults = [
        'portMin' => 20000,
        'portMax' => 29999,
        'buildTimeout' => 3600,
        'memoryMb' => 0,
        'cpuPercent' => 0,
        'tasks' => 0,
        // Builds run customer code too: TasksMax is always applied (0 = 4096).
        'buildMemoryMb' => 0,
        'buildCpuPercent' => 0,
        'buildTasks' => 4096,
        // 0 = unlimited (enforced from Phase 3b on).
        'maxAppsPerSubscription' => 0,
    ];

    /** @var array key => [min, max] */
    private static $ranges = [
        'portMin' => [1024, 65535],
        'portMax' => [1024, 65535],
        'buildTimeout' => [60, 21600],
        'memoryMb' => [0, 1048576],
        'cpuPercent' => [0, 25600],
        'tasks' => [0, 1000000],
        'buildMemoryMb' => [0, 1048576],
        'buildCpuPercent' => [0, 25600],
        'buildTasks' => [0, 1000000],
        'maxAppsPerSubscription' => [0, 10000],
    ];

    /**
     * @param string $key
     * @return int
     */
    public static function get($key)
    {
        if (!array_key_exists($key, self::$defaults)) {
            throw new InvalidArgumentException("Unknown setting {$key}");
        }
        return (int)pm_Settings::get($key, self::$defaults[$key]);
    }

    /**
     * @param string $key
     * @param int $value
     */
    public static function set($key, $value)
    {
        if (!array_key_exists($key, self::$defaults)) {
            throw new InvalidArgumentException("Unknown setting {$key}");
        }
        pm_Settings::set($key, (string)(int)$value);
    }

    /**
     * @return array
     */
    public static function all()
    {
        $result = [];
        foreach (array_keys(self::$defaults) as $key) {
            $result[$key] = self::get($key);
        }
        return $result;
    }

    /**
     * @return array key => [min, max]
     */
    public static function ranges()
    {
        return self::$ranges;
    }

    /**
     * Validates and stores settings. Keys missing from $values keep their value.
     *
     * @param array $values Decoded JSON body
     * @return array Validation errors keyed by field (nothing is saved when not empty)
     */
    public static function update(array $values)
    {
        $errors = [];
        $new = self::all();
        foreach (self::$ranges as $key => $range) {
            if (!array_key_exists($key, $values) || $values[$key] === null) {
                continue;
            }
            $raw = is_scalar($values[$key]) && !is_bool($values[$key]) ? trim((string)$values[$key]) : 'x';
            if (!ctype_digit($raw) || (int)$raw < $range[0] || (int)$raw > $range[1]) {
                $errors[$key][] = pm_Locale::lmsg('errorSettingRange', ['min' => $range[0], 'max' => $range[1]]);
                continue;
            }
            $new[$key] = (int)$raw;
        }
        if (!isset($errors['portMin']) && !isset($errors['portMax']) && $new['portMin'] > $new['portMax']) {
            $errors['portMax'][] = pm_Locale::lmsg('errorPortRange');
        }
        if (!$errors) {
            foreach ($new as $key => $value) {
                self::set($key, $value);
            }
        }
        return $errors;
    }

    /**
     * @return int[] [min, max]
     */
    public static function portRange()
    {
        return [self::get('portMin'), self::get('portMax')];
    }
}
