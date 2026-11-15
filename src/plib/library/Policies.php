<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/** Optional Plesk-native subscription policies. Disabled policies never change existing limits. */
class Modules_Runway_Policies
{
    const RUNTIMES = ['go', 'rust', 'bun', 'java', 'dotnet', 'python', 'ruby', 'php', 'binary'];
    const LIMITS = ['memoryMb' => 'app_memory_mb', 'cpuPercent' => 'app_cpu_percent', 'tasks' => 'app_tasks'];
    const MAXIMUMS = ['app_count' => 10000, 'app_memory_mb' => 1048576, 'app_cpu_percent' => 25600, 'app_tasks' => 1000000];

    public static function enabled()
    {
        return (bool)Modules_Runway_Settings::get('planPolicies');
    }

    public static function limit(pm_Domain $domain, $name)
    {
        if (!self::enabled()) {
            return null;
        }
        $value = $domain->getLimit($name);
        return is_numeric($value) && (int)$value >= 0 ? min((int)$value, self::MAXIMUMS[$name]) : null;
    }

    public static function allows(pm_Domain $domain, $runtime)
    {
        return !self::enabled() || (bool)$domain->hasPermission('runtime_' . $runtime);
    }

    public static function clamp(pm_Domain $domain, array $limits)
    {
        foreach (self::LIMITS as $field => $name) {
            $cap = self::limit($domain, $name);
            if ($cap > 0 && (empty($limits[$field]) || (int)$limits[$field] > $cap)) {
                $limits[$field] = $cap;
            }
        }
        return $limits;
    }

    public static function describe(pm_Domain $domain)
    {
        if (!self::enabled()) {
            return null;
        }
        return ['allowedRuntimes' => array_values(array_filter(self::RUNTIMES, function ($runtime) use ($domain) {
            return self::allows($domain, $runtime);
        })), 'limits' => self::clamp($domain, ['memoryMb' => 0, 'cpuPercent' => 0, 'tasks' => 0]),
            'maxApps' => self::limit($domain, 'app_count')];
    }
}
