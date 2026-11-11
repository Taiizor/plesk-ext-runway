<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Runtime metadata. The root helper is the single source of truth (`runtimes` command,
 * docs/DESIGN.md section 5.1); this class caches its answer for the current request and
 * offers a few lookups for validation.
 *
 * Every entry: key, label, toolchain (managed|detected|none), version_re (Python regex
 * syntax that is also valid PCRE), hint, docs_url, default_listen, supports_build,
 * install_help.
 */
class Modules_Runway_Runtime
{
    const TOOLCHAIN_MANAGED = 'managed';
    const TOOLCHAIN_DETECTED = 'detected';
    const TOOLCHAIN_NONE = 'none';

    /** @var array|null Metadata list of the current request */
    private static $cache = null;

    /**
     * @return array[] Metadata of every runtime the helper supports, in display order
     */
    public static function all()
    {
        if (self::$cache === null) {
            try {
                $result = Modules_Runway_Helper::call('runtimes');
                $list = isset($result['runtimes']) && is_array($result['runtimes']) ? $result['runtimes'] : [];
            } catch (Exception $e) {
                Modules_Runway_Log::warn('Runtime metadata could not be loaded: ' . $e->getMessage());
                $list = [];
            }
            $valid = [];
            foreach ($list as $meta) {
                if (is_array($meta) && isset($meta['key']) && preg_match('/^[a-z][a-z0-9_-]{0,31}$/', (string)$meta['key'])) {
                    $valid[] = $meta;
                }
            }
            // The cache lives for one request only, so a helper failure is retried by the next one.
            self::$cache = $valid ? $valid : self::fallback();
        }
        return self::$cache;
    }

    /**
     * @return string[]
     */
    public static function keys()
    {
        return array_map(function ($meta) {
            return (string)$meta['key'];
        }, self::all());
    }

    /**
     * @param string $key
     * @return array|null
     */
    public static function get($key)
    {
        foreach (self::all() as $meta) {
            if ((string)$meta['key'] === (string)$key) {
                return $meta;
            }
        }
        return null;
    }

    /**
     * @param string $key
     * @return string managed|detected|none
     */
    public static function toolchainKind($key)
    {
        $meta = self::get($key);
        return $meta && isset($meta['toolchain']) ? (string)$meta['toolchain'] : self::TOOLCHAIN_NONE;
    }

    /**
     * Whether a toolchain id is syntactically valid for the runtime (the helper validates again
     * and also checks that it is installed).
     *
     * @param string $key
     * @param string $version
     * @return bool
     */
    public static function isValidVersion($key, $version)
    {
        $meta = self::get($key);
        if (!$meta || empty($meta['version_re'])) {
            return false;
        }
        $pattern = '~' . str_replace('~', '\~', (string)$meta['version_re']) . '~';
        return @preg_match($pattern, (string)$version) === 1;
    }

    /**
     * Whether the default start command of a runtime can listen on a Unix socket with the
     * given toolchain (helper metadata "unix_toolchain_re"; empty = every toolchain can).
     *
     * @param string $key
     * @param string $toolchain
     * @return bool
     */
    public static function unixSupported($key, $toolchain)
    {
        $meta = self::get($key);
        if (!$meta || empty($meta['unix_toolchain_re'])) {
            return true;
        }
        $pattern = '~' . str_replace('~', '\~', (string)$meta['unix_toolchain_re']) . '~';
        return @preg_match($pattern, (string)$toolchain) === 1;
    }

    /**
     * Minimal metadata used when the helper cannot be reached (keeps the UI usable).
     *
     * @return array[]
     */
    private static function fallback()
    {
        return [
            ['key' => 'go', 'label' => 'Go', 'toolchain' => self::TOOLCHAIN_MANAGED,
                'version_re' => '^1\.\d{1,3}(\.\d{1,3})?((rc|beta)\d{1,2})?$', 'hint' => '', 'docs_url' => '',
                'default_listen' => 'tcp', 'supports_build' => true, 'install_help' => ''],
            ['key' => 'rust', 'label' => 'Rust', 'toolchain' => self::TOOLCHAIN_MANAGED,
                'version_re' => '^(stable|beta|nightly(-\d{4}-\d{2}-\d{2})?|1\.\d{1,3}(\.\d{1,3})?)$', 'hint' => '',
                'docs_url' => '', 'default_listen' => 'tcp', 'supports_build' => true, 'install_help' => ''],
            ['key' => 'binary', 'label' => 'Prebuilt binary', 'toolchain' => self::TOOLCHAIN_NONE,
                'version_re' => '', 'hint' => '', 'docs_url' => '', 'default_listen' => 'tcp',
                'supports_build' => false, 'install_help' => ''],
        ];
    }
}
