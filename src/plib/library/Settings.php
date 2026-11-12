<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Server-wide settings of the extension (managed by the administrator): integers with an
 * allowed range, and the switches of the built-in updater (booleans).
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

    /** @var array Boolean settings => default: the update check of the scheduled task (twice a day) and automatic installation */
    private static $switches = [
        'updateCheck' => true,
        'updateAuto' => false,
    ];

    /**
     * @param string $key
     * @return int|bool Integer settings, or a bool for the switches (updateCheck, updateAuto)
     */
    public static function get($key)
    {
        if (array_key_exists($key, self::$switches)) {
            $value = pm_Settings::get($key, null);
            return $value === null || $value === '' ? self::$switches[$key] : (string)$value === '1';
        }
        if (!array_key_exists($key, self::$defaults)) {
            throw new InvalidArgumentException("Unknown setting {$key}");
        }
        return (int)pm_Settings::get($key, self::$defaults[$key]);
    }

    /**
     * @param string $key
     * @param int|bool $value
     */
    public static function set($key, $value)
    {
        if (array_key_exists($key, self::$switches)) {
            pm_Settings::set($key, $value ? '1' : '0');
            return;
        }
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
        foreach (array_merge(array_keys(self::$defaults), array_keys(self::$switches)) as $key) {
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
        foreach (array_keys(self::$switches) as $key) {
            if (!array_key_exists($key, $values) || $values[$key] === null) {
                continue;
            }
            $switch = self::toBool($values[$key]);
            if ($switch === null) {
                $errors[$key][] = pm_Locale::lmsg('errorSettingBoolean');
                continue;
            }
            $new[$key] = $switch;
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
     * @param mixed $value JSON boolean, 0/1 or "true"/"false"/"1"/"0" (form posts)
     * @return bool|null Null when the value is not a boolean
     */
    private static function toBool($value)
    {
        if (is_bool($value)) {
            return $value;
        }
        if ($value === 0 || $value === 1) {
            return $value === 1;
        }
        if (is_string($value)) {
            $text = strtolower(trim($value));
            if (in_array($text, ['1', 'true', 'on'], true)) {
                return true;
            }
            if (in_array($text, ['0', 'false', 'off', ''], true)) {
                return false;
            }
        }
        return null;
    }

    /**
     * @return int[] [min, max]
     */
    public static function portRange()
    {
        return [self::get('portMin'), self::get('portMax')];
    }
}
