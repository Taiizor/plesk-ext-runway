<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Logging to /var/log/plesk/panel.log. Uses the PSR-3 logger from the Plesk
 * container when available (pm_Log is deprecated) and falls back to pm_Log.
 */
class Modules_Runway_Log
{
    /** @var object|false|null */
    private static $logger = null;

    public static function err($message)
    {
        self::write('error', 'err', $message);
    }

    public static function warn($message)
    {
        self::write('warning', 'warn', $message);
    }

    public static function info($message)
    {
        self::write('info', 'info', $message);
    }

    public static function debug($message)
    {
        self::write('debug', 'debug', $message);
    }

    private static function write($psrMethod, $legacyMethod, $message)
    {
        $message = '[runway] ' . $message;
        if (self::$logger === null) {
            self::$logger = false;
            try {
                if (class_exists('pm_Bootstrap') && method_exists('pm_Bootstrap', 'getContainer')) {
                    $logger = pm_Bootstrap::getContainer()->get('Psr\Log\LoggerInterface');
                    if (is_object($logger)) {
                        self::$logger = $logger;
                    }
                }
            } catch (Throwable $e) {
                self::$logger = false;
            }
        }
        try {
            if (self::$logger) {
                self::$logger->{$psrMethod}($message);
            } else {
                pm_Log::{$legacyMethod}($message);
            }
        } catch (Throwable $e) {
            // Logging must never break the panel.
        }
    }
}
