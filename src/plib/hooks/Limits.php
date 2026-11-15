<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

class Modules_Runway_Limits extends pm_Hook_Limits
{
    public function getLimits()
    {
        $result = [];
        foreach (['app_count' => 'planLimitApps', 'app_memory_mb' => 'planLimitMemory',
                     'app_cpu_percent' => 'planLimitCpu', 'app_tasks' => 'planLimitTasks'] as $id => $key) {
            $result[$id] = ['default' => false, 'place' => self::PLACE_ADDITIONAL, 'name' => pm_Locale::lmsg($key)];
        }
        return $result;
    }
}
