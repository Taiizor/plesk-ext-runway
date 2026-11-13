<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Per-domain application configuration.
 *
 * The configuration is stored as JSON in the domain's extension settings (the
 * source of truth for the UI and the web server hook). Applying it sends a
 * validated copy to the root helper, which mirrors it into its own state and
 * renders the systemd units. Environment variables are never stored here: they
 * may contain secrets and live only in the helper's root-only state.
 *
 * Field names are camelCase (API, settings); payload() converts them to the
 * helper's snake_case contract (docs/DESIGN.md sections 6 and 7).
 */
class Modules_Runway_App
{
    const SETTING_KEY = 'runwayApp';
    const LIMITS_KEY = 'runwayLimits';

    const RUNTIME_GO = 'go';
    const RUNTIME_RUST = 'rust';
    const RUNTIME_BINARY = 'binary';

    const LISTEN_TCP = 'tcp';
    const LISTEN_UNIX = 'unix';
    const LISTEN_NONE = 'none';

    const MODE_WEB = 'web';
    const MODE_PATH = 'path';
    const MODE_WORKER = 'worker';

    const MAX_STATIC_PATHS = 20;

    /** Zero-downtime deployments (docs/DESIGN.md section 12): defaults and lower limits of the timeouts. */
    const READY_TIMEOUT_DEFAULT = 60;
    const DRAIN_SECONDS_DEFAULT = 10;
    const READY_TIMEOUT_MIN = 5;
    const DRAIN_SECONDS_MIN = 0;

    /**
     * Plesk stores domain settings in dom_param.val, a varchar(5000); MariaDB in Plesk's default
     * (non-strict) sql_mode silently truncates longer values, which would turn the app into "not
     * configured". The encoded configuration is therefore limited to this many characters, and
     * the per-field limits below keep normal configurations far away from it.
     */
    const MAX_CONFIG_CHARS = 4500;
    const MAX_APP_ROOT = 255;
    const MAX_BUILD_CMD = 1500;
    const MAX_START_CMD = 1000;
    const MAX_HEALTH_PATH = 255;
    /** Total length of all static paths together. */
    const MAX_STATIC_CHARS = 1000;

    const RE_ENV_KEY = '/^[A-Za-z_][A-Za-z0-9_]{0,127}$/';
    const RE_APP_ROOT = '#^[A-Za-z0-9._@+-]+(/[A-Za-z0-9._@+-]+)*$#';
    /** URL prefix (mount path, static paths): docs/DESIGN.md section 5.3 */
    const RE_URL_PREFIX = '#^/[A-Za-z0-9._~-]+(/[A-Za-z0-9._~-]+)*$#';
    /** Health check path (may carry a query string); same rule as RE_HEALTH_PATH in the helper. */
    const RE_HEALTH_PATH = '#^/[A-Za-z0-9._~%/?=&+,:@-]{0,511}$#';

    /** Variables managed by Runway itself (must match RESERVED_ENV in the helper). */
    public static $reservedEnv = ['PORT', 'HOST', 'LISTEN_ADDR', 'RUNWAY_APP_ROOT', 'RUNWAY_START_CMD',
        'RUNWAY_SOCKET', 'RUNWAY_LISTEN', 'HOME', 'USER', 'LOGNAME'];

    /**
     * Variables of the dynamic loader and the C library that change what a process loads (must match
     * LOADER_ENV in the helper). They are refused in the environment file; an application that needs
     * one sets it in its start command.
     */
    public static $loaderEnv = ['LD_PRELOAD', 'LD_AUDIT', 'GCONV_PATH', 'GLIBC_TUNABLES'];

    /**
     * URL paths that always stay with Plesk (web statistics, ACME challenges). They are
     * excluded from the proxy (see WebConfig) and cannot be used as a mount path.
     */
    public static $reservedPaths = ['/.well-known/acme-challenge', '/plesk-stat', '/webstat', '/webstat-ssl',
        '/ftpstat', '/anon_ftpstat', '/awstats-icon'];

    /**
     * Fallback build and start commands per runtime (docs/DESIGN.md section 5.2). The helper's
     * app-page returns project-aware defaults; these are used when it cannot be reached and
     * for the initial configuration of a new application.
     *
     * @var array runtime => [build, start]
     */
    private static $fallbackCommands = [
        'go' => ['go build -o bin/app .', './bin/app'],
        'rust' => ['cargo build --release', './target/release/app'],
        'bun' => ['bun install', 'bun run start'],
        'java' => ['', 'java -jar target/app.jar'],
        'dotnet' => ['dotnet publish -c Release -o publish', 'dotnet publish/app.dll'],
        'python' => ['uv venv .venv && uv pip install -r requirements.txt',
            '.venv/bin/uvicorn app:app --host $HOST --port $PORT'],
        'ruby' => ['bundle install', 'bundle exec puma -b tcp://$HOST:$PORT'],
        'php' => ['composer install --no-dev --optimize-autoloader', 'php -S $LISTEN_ADDR -t public'],
        'binary' => ['', './app'],
    ];

    /** @var pm_Domain */
    private $domain;

    /** @var array */
    private $data;

    /** @var bool */
    private $configured;

    /** @var bool Whether an administrator changed the limits in this request */
    private $limitsChanged = false;

    /**
     * Environment variables (KEY => value). null = not loaded and not edited: the helper then
     * keeps the stored ones. Never persisted in the Plesk database.
     *
     * @var array|null
     */
    private $env = null;

    public function __construct(pm_Domain $domain)
    {
        $this->domain = $domain;
        $stored = self::readStored($domain);
        $this->configured = is_array($stored);
        $runtime = $this->configured && isset($stored['runtime']) ? (string)$stored['runtime'] : self::RUNTIME_GO;
        $this->data = array_merge(self::defaults($domain, $runtime), $this->configured ? $stored : []);
        unset($this->data['env']);
        // Limits always come from the admin-only storage (see adminLimits()).
        $this->data = array_merge($this->data, self::adminLimits($domain));
    }

    /**
     * @param pm_Domain $domain
     * @param string $runtime
     * @return array
     */
    public static function defaults(pm_Domain $domain, $runtime)
    {
        $commands = self::defaultCommands($runtime);
        return [
            'enabled' => false,
            'runtime' => $runtime,
            'toolchain' => '',
            'appRoot' => self::defaultAppRoot($domain),
            'listen' => self::defaultListen($runtime),
            'mode' => self::MODE_WEB,
            'mountPath' => '',
            'staticPaths' => [],
            'healthPath' => '',
            'buildCmd' => $commands['build'],
            'startCmd' => $commands['start'],
            'autoDeploy' => true,
            'port' => 0,
            'zeroDowntime' => false,
            'readyTimeout' => self::READY_TIMEOUT_DEFAULT,
            'drainSeconds' => self::DRAIN_SECONDS_DEFAULT,
            // Helper-owned: the web server snippet uses the zero-downtime pointer (app-apply's result).
            'switchable' => false,
        ] + self::adminLimits($domain);
    }

    /**
     * Resource limits of the domain. They are set by administrators only and are stored apart
     * from the app configuration, so a customer cannot drop them by removing and re-creating
     * the app. Falls back to the server-wide defaults.
     *
     * @param pm_Domain $domain
     * @return array memoryMb, cpuPercent, tasks
     */
    public static function adminLimits(pm_Domain $domain)
    {
        $limits = [
            'memoryMb' => Modules_Runway_Settings::get('memoryMb'),
            'cpuPercent' => Modules_Runway_Settings::get('cpuPercent'),
            'tasks' => Modules_Runway_Settings::get('tasks'),
        ];
        $raw = $domain->getSetting(self::LIMITS_KEY, '');
        $stored = is_string($raw) && $raw !== '' ? json_decode($raw, true) : null;
        if (is_array($stored)) {
            foreach (array_keys($limits) as $key) {
                if (isset($stored[$key])) {
                    $limits[$key] = (int)$stored[$key];
                }
            }
        }
        return $limits;
    }

    /**
     * Static fallback for the default commands (the helper's app-page returns the
     * project-aware defaults, see loadPage()).
     *
     * @param string $runtime
     * @return array ['build' => string, 'start' => string]
     */
    public static function defaultCommands($runtime)
    {
        $commands = isset(self::$fallbackCommands[$runtime]) ? self::$fallbackCommands[$runtime] : ['', './app'];
        return ['build' => $commands[0], 'start' => $commands[1]];
    }

    /**
     * Listen mode of a new web application of the runtime (helper metadata "default_listen").
     *
     * @param string $runtime
     * @return string tcp|unix
     */
    public static function defaultListen($runtime)
    {
        $meta = Modules_Runway_Runtime::get($runtime);
        $listen = $meta && isset($meta['default_listen']) ? (string)$meta['default_listen'] : '';
        return in_array($listen, [self::LISTEN_TCP, self::LISTEN_UNIX], true) ? $listen : self::LISTEN_TCP;
    }

    /**
     * Whether a string is a valid URL prefix for a mount path or a static path
     * (docs/DESIGN.md section 5.3, without "." and ".." segments).
     *
     * @param string $path
     * @return bool
     */
    public static function isValidUrlPrefix($path)
    {
        $path = (string)$path;
        return strlen($path) <= 200 && preg_match(self::RE_URL_PREFIX, $path) === 1
            && !preg_match('#/\.{1,2}(/|$)#', $path);
    }

    /**
     * Whether a URL path is, contains or lies inside a path that must stay with Plesk.
     *
     * @param string $path
     * @return bool
     */
    public static function isReservedPath($path)
    {
        foreach (self::$reservedPaths as $reserved) {
            if ($path === $reserved || strpos($path, $reserved . '/') === 0 || strpos($reserved, $path . '/') === 0) {
                return true;
            }
        }
        return false;
    }

    /**
     * Normalises a URL path typed by a user: surrounding blanks and trailing slashes are
     * removed and a missing leading slash is added ("api/" => "/api", "/" => "").
     *
     * @param mixed $value
     * @return string
     */
    private static function normalizeUrlPath($value)
    {
        $path = is_scalar($value) && !is_bool($value) ? trim((string)$value) : '';
        $path = rtrim($path, '/');
        if ($path !== '' && $path[0] !== '/') {
            $path = '/' . $path;
        }
        return $path;
    }

    /**
     * Document roots of the domains in the webspace of a domain (its subscription: the same home
     * directory and system user), relative to the home directory, the domain's own first. The
     * web server serves every file below a document root whenever it does not pass a request to
     * an application (application disabled or removed, worker mode, paths outside the mount path,
     * static paths), so an application root there exposes its files (docs/DESIGN.md section 6).
     *
     * @param pm_Domain $domain
     * @return array[] [['domain' => display name, 'path' => relative path, 'own' => bool], ...]
     */
    public static function documentRoots(pm_Domain $domain)
    {
        try {
            $home = rtrim((string)$domain->getHomePath(), '/');
            $sysuser = (string)$domain->getSysUserLogin();
        } catch (Exception $e) {
            return [];
        }
        $domains = [$domain];
        try {
            foreach (pm_Domain::getDomainsByClient($domain->getClient()) as $other) {
                if ((int)$other->getId() !== (int)$domain->getId()) {
                    $domains[] = $other;
                }
            }
        } catch (Exception $e) {
            Modules_Runway_Log::debug('Domains of the subscription of ' . $domain->getName() . ' unknown: ' . $e->getMessage());
        }
        $roots = [];
        foreach ($domains as $item) {
            try {
                if (!$item->hasHosting() || (string)$item->getSysUserLogin() !== $sysuser
                    || rtrim((string)$item->getHomePath(), '/') !== $home) {
                    continue;
                }
                $root = rtrim((string)$item->getDocumentRoot(), '/');
            } catch (Exception $e) {
                continue;
            }
            if ($home === '' || strpos($root, $home . '/') !== 0) {
                continue;
            }
            $roots[] = [
                'domain' => (string)$item->getDisplayName(),
                'path' => substr($root, strlen($home) + 1),
                'own' => (int)$item->getId() === (int)$domain->getId(),
            ];
        }
        return $roots;
    }

    /**
     * The document root an application root lies in (the same directory or below it), compared
     * as text.
     *
     * @param array[] $roots documentRoots()
     * @param string $appRoot Relative to the subscription home directory
     * @return array|null The entry of $roots, or null
     */
    public static function documentRootOf(array $roots, $appRoot)
    {
        $appRoot = trim(str_replace('\\', '/', (string)$appRoot), " /");
        if ($appRoot === '') {
            return null;
        }
        foreach ($roots as $root) {
            if ($appRoot === $root['path'] || strpos($appRoot, $root['path'] . '/') === 0) {
                return $root;
            }
        }
        return null;
    }

    /**
     * The entry of documentRoots() that the helper named ("document_root" of app-inspect and
     * app-page: the document root the application root lies in once symbolic links are resolved).
     *
     * @param array[] $roots documentRoots()
     * @param mixed $path Relative path from the helper, null when none
     * @return array|null
     */
    public static function documentRootByPath(array $roots, $path)
    {
        if (!is_string($path) || $path === '') {
            return null;
        }
        foreach ($roots as $root) {
            if ($root['path'] === $path) {
                return $root;
            }
        }
        return null;
    }

    /**
     * The document root the configured application root lies in: compared as text, else with
     * symbolic links resolved by the helper as the system user (app-inspect), so that a link such
     * as apps/api -> ../httpdocs/api or httpdocs -> releases/current counts as well.
     *
     * @return array|null An entry of documentRoots(), or null
     */
    public function appRootDocumentRoot()
    {
        $roots = self::documentRoots($this->domain);
        $found = self::documentRootOf($roots, $this->data['appRoot']);
        if ($found !== null || !$roots) {
            return $found;
        }
        try {
            $inspect = $this->inspect(null, $roots);
        } catch (Exception $e) {
            Modules_Runway_Log::debug('app-inspect for the document roots failed: ' . $e->getMessage());
            return null;
        }
        return self::documentRootByPath($roots, isset($inspect['document_root']) ? $inspect['document_root'] : null);
    }

    /**
     * @param pm_Domain $domain
     * @return string Path relative to the subscription home directory
     */
    public static function defaultAppRoot(pm_Domain $domain)
    {
        $name = strtolower((string)$domain->getName());
        if (!preg_match('/^[a-z0-9][a-z0-9.-]{0,200}$/', $name)) {
            $name = 'app-' . (int)$domain->getId();
        }
        return 'apps/' . $name;
    }

    /**
     * Where the web server should proxy to, or null when the domain has no enabled app that
     * serves HTTP (workers included). Used by the web server hook: cheap and never throws.
     *
     * The result has 'port' or 'socket', plus 'mode' (web|path), 'mountPath' (path mode) and
     * 'staticPaths' (URL prefixes that stay with the web server). WebConfig validates the
     * paths again before writing them into the web server configuration.
     *
     * @param pm_Domain $domain
     * @return array|null
     */
    public static function proxyTarget(pm_Domain $domain)
    {
        try {
            $data = self::readStored($domain);
            if (!is_array($data) || empty($data['enabled']) || !self::domainIsActive($domain)) {
                return null;
            }
            $listen = isset($data['listen']) ? (string)$data['listen'] : self::LISTEN_TCP;
            $mode = isset($data['mode']) ? (string)$data['mode'] : self::MODE_WEB;
            if ($listen === self::LISTEN_NONE || $mode === self::MODE_WORKER) {
                return null;
            }
            $extra = [
                'mode' => $mode === self::MODE_PATH ? self::MODE_PATH : self::MODE_WEB,
                'mountPath' => $mode === self::MODE_PATH && isset($data['mountPath']) ? (string)$data['mountPath'] : '',
                'staticPaths' => isset($data['staticPaths']) && is_array($data['staticPaths']) ? array_values($data['staticPaths']) : [],
                // Zero-downtime deployments: the snippet uses the helper's pointer (root link or include).
                'switchable' => !empty($data['switchable']),
                'domainId' => (int)$domain->getId(),
            ];
            if ($extra['mode'] === self::MODE_PATH && !self::isValidUrlPrefix($extra['mountPath'])) {
                return null;
            }
            if ($listen === self::LISTEN_UNIX) {
                return ['socket' => $extra['switchable'] ? self::linkPath($domain) : self::socketPath($domain)] + $extra;
            }
            $port = isset($data['port']) ? (int)$data['port'] : 0;
            return ($port >= 1024 && $port <= 65535) ? ['port' => $port] + $extra : null;
        } catch (Exception $e) {
            return null;
        }
    }

    /**
     * One display state from a stored configuration and the helper's view of the service
     * (an apps-list entry, or at least active_state + suspended).
     *
     * @param array|null $config Stored configuration
     * @param array|null $state Helper state
     * @return string notConfigured|disabled|suspended|tampered|running|starting|stopping|failed|stopped
     */
    public static function uiState($config, $state)
    {
        if ($config === null) {
            return 'notConfigured';
        }
        if (empty($config['enabled'])) {
            return 'disabled';
        }
        if ($state && !empty($state['suspended'])) {
            return 'suspended';
        }
        if ($state && !empty($state['tampered'])) {
            // Runway stopped it: its unix socket path was replaced (docs/DESIGN.md section 7).
            return 'tampered';
        }
        $map = [
            'active' => 'running',
            'activating' => 'starting',
            'reloading' => 'starting',
            'deactivating' => 'stopping',
            'failed' => 'failed',
        ];
        $active = $state && isset($state['active_state']) ? (string)$state['active_state'] : '';
        return isset($map[$active]) ? $map[$active] : 'stopped';
    }

    /**
     * URL of the application on its domain: the site for "web", the mount path for "path",
     * null for workers.
     *
     * @param pm_Domain $domain
     * @param array|null $config Stored configuration
     * @return string|null
     */
    public static function appUrl(pm_Domain $domain, $config)
    {
        if (!is_array($config)) {
            return null;
        }
        $mode = isset($config['mode']) ? (string)$config['mode'] : self::MODE_WEB;
        if ($mode === self::MODE_WORKER || (isset($config['listen']) && $config['listen'] === self::LISTEN_NONE)) {
            return null;
        }
        $base = rtrim(self::siteUrl($domain), '/');
        if ($mode === self::MODE_PATH && !empty($config['mountPath'])) {
            return $base . $config['mountPath'] . '/';
        }
        return $base . '/';
    }

    /**
     * Root URL of the domain's website: https:// when its hosting has SSL/TLS support enabled
     * (pm_Domain::hasSsl(), available in the Plesk versions Runway supports; guarded anyway),
     * else http://.
     *
     * @param pm_Domain $domain
     * @return string
     */
    public static function siteUrl(pm_Domain $domain)
    {
        $scheme = 'http';
        try {
            if (method_exists($domain, 'hasSsl') && $domain->hasSsl()) {
                $scheme = 'https';
            }
        } catch (Exception $e) {
            Modules_Runway_Log::debug('SSL status of ' . $domain->getName() . ' unknown: ' . $e->getMessage());
        }
        return $scheme . '://' . $domain->getName() . '/';
    }

    /**
     * Number of enabled applications of other domains that belong to the same system user
     * (= the same subscription). Used for the maxAppsPerSubscription limit.
     *
     * @param pm_Domain $domain
     * @return int
     */
    public static function countOtherEnabledApps(pm_Domain $domain)
    {
        $sysuser = (string)$domain->getSysUserLogin();
        $count = 0;
        foreach (pm_Domain::getAllDomains() as $other) {
            try {
                if ((int)$other->getId() === (int)$domain->getId() || !$other->hasHosting()
                    || (string)$other->getSysUserLogin() !== $sysuser) {
                    continue;
                }
                $config = self::storedConfig($other);
                if ($config !== null && !empty($config['enabled'])) {
                    $count++;
                }
            } catch (Exception $e) {
                continue;
            }
        }
        return $count;
    }

    /**
     * @param pm_Domain $domain
     * @return string Unix socket path used in socket mode (must match the helper)
     */
    public static function socketPath(pm_Domain $domain)
    {
        return '/run/runway/' . (int)$domain->getId() . '/app.sock';
    }

    /**
     * @param pm_Domain $domain
     * @return string The web server's path of a switchable unix application: the root-owned symlink
     *                to the live slot's socket (docs/DESIGN.md section 12.6, must match the helper)
     */
    public static function linkPath(pm_Domain $domain)
    {
        return '/run/runway/' . (int)$domain->getId() . '.sock';
    }

    /**
     * Whether the current user may turn zero-downtime deployments on: administrators always,
     * customers when the server setting zeroDowntimeCustomers allows it (docs/DESIGN.md section 12.9).
     *
     * @param bool $isAdmin
     * @return bool
     */
    public static function zeroDowntimeAllowed($isAdmin)
    {
        return $isAdmin || Modules_Runway_Settings::get('zeroDowntimeCustomers');
    }

    /**
     * @return array ['ready' => int, 'drain' => int] Upper limits of readyTimeout and drainSeconds
     */
    public static function zeroDowntimeCaps()
    {
        return [
            'ready' => Modules_Runway_Settings::get('zeroDowntimeMaxReady'),
            'drain' => Modules_Runway_Settings::get('zeroDowntimeMaxDrain'),
        ];
    }

    /**
     * Whether the domain is active in Plesk (not suspended or disabled).
     *
     * @param pm_Domain $domain
     * @return bool
     */
    public static function domainIsActive(pm_Domain $domain)
    {
        try {
            if (method_exists($domain, 'isSuspended') && $domain->isSuspended()) {
                return false;
            }
            if (method_exists($domain, 'isDisabled') && $domain->isDisabled()) {
                return false;
            }
            if (method_exists($domain, 'isActive')) {
                return (bool)$domain->isActive();
            }
        } catch (Exception $e) {
            Modules_Runway_Log::debug('Domain status check failed: ' . $e->getMessage());
        }
        return true;
    }

    /**
     * The stored configuration of a domain without building a model (cheap; for lists).
     *
     * @param pm_Domain $domain
     * @return array|null null when the domain has no application
     */
    public static function storedConfig(pm_Domain $domain)
    {
        try {
            return self::readStored($domain);
        } catch (Exception $e) {
            return null;
        }
    }

    /**
     * @param pm_Domain $domain
     * @return array|null
     */
    private static function readStored(pm_Domain $domain)
    {
        $raw = $domain->getSetting(self::SETTING_KEY, '');
        if (!is_string($raw) || $raw === '') {
            return null;
        }
        $data = json_decode($raw, true);
        return is_array($data) ? $data : null;
    }

    /**
     * @return pm_Domain
     */
    public function getDomain()
    {
        return $this->domain;
    }

    /**
     * @return bool
     */
    public function isConfigured()
    {
        return $this->configured;
    }

    /**
     * @return bool
     */
    public function isEnabled()
    {
        return $this->configured && !empty($this->data['enabled']);
    }

    /**
     * @param string $key
     * @return mixed
     */
    public function get($key)
    {
        return array_key_exists($key, $this->data) ? $this->data[$key] : null;
    }

    /**
     * Configuration fields for the API (camelCase, without env and without the admin limits).
     *
     * @return array
     */
    public function config()
    {
        $config = [];
        foreach (['enabled', 'runtime', 'toolchain', 'appRoot', 'listen', 'mode', 'mountPath', 'staticPaths',
                     'healthPath', 'buildCmd', 'startCmd', 'autoDeploy', 'port', 'zeroDowntime', 'readyTimeout',
                     'drainSeconds', 'switchable'] as $key) {
            $config[$key] = $this->get($key);
        }
        $config['enabled'] = (bool)$config['enabled'];
        $config['autoDeploy'] = (bool)$config['autoDeploy'];
        $config['port'] = (int)$config['port'];
        $config['zeroDowntime'] = (bool)$config['zeroDowntime'];
        $config['readyTimeout'] = (int)$config['readyTimeout'];
        $config['drainSeconds'] = (int)$config['drainSeconds'];
        $config['switchable'] = (bool)$config['switchable'];
        $config['staticPaths'] = is_array($config['staticPaths']) ? array_values($config['staticPaths']) : [];
        return $config;
    }

    /**
     * @return array memoryMb, cpuPercent, tasks
     */
    public function limits()
    {
        return [
            'memoryMb' => (int)$this->data['memoryMb'],
            'cpuPercent' => (int)$this->data['cpuPercent'],
            'tasks' => (int)$this->data['tasks'],
        ];
    }

    /**
     * Validates API input and merges it into the configuration (does not persist).
     * Fields missing from $values keep their current value; "env" is only changed when
     * present. Booleans accept true/false, 1/0 and "1"/"0"/"true"/"false"/"on"/"off".
     *
     * @param array $values Decoded JSON body (camelCase fields)
     * @param bool $isAdmin Whether resource limits may be changed
     * @return array Validation errors keyed by field: ['field' => ['message', ...]] (empty on success)
     */
    public function update(array $values, $isAdmin)
    {
        $errors = [];
        $data = $this->data;
        $has = function ($key) use ($values) {
            return array_key_exists($key, $values) && $values[$key] !== null;
        };

        if ($has('runtime')) {
            $runtime = is_string($values['runtime']) ? $values['runtime'] : '';
            if (!in_array($runtime, Modules_Runway_Runtime::keys(), true)) {
                $errors['runtime'][] = pm_Locale::lmsg('errorRuntime');
            } else {
                $data['runtime'] = $runtime;
            }
        }
        if (!in_array($data['runtime'], Modules_Runway_Runtime::keys(), true)) {
            $errors['runtime'][] = pm_Locale::lmsg('errorRuntime');
        } elseif ($data['runtime'] !== $this->data['runtime']) {
            // Commands that were not customised follow the runtime (API and CLI clients may
            // change the runtime without sending commands).
            $old = self::defaultCommands($this->data['runtime']);
            $new = self::defaultCommands($data['runtime']);
            foreach (['buildCmd' => 'build', 'startCmd' => 'start'] as $field => $kind) {
                if (!$has($field) && (string)$data[$field] === $old[$kind]) {
                    $data[$field] = $new[$kind];
                }
            }
        }

        foreach (['enabled', 'autoDeploy'] as $key) {
            if ($has($key)) {
                $bool = self::toBool($values[$key]);
                if ($bool === null) {
                    $errors[$key][] = pm_Locale::lmsg('errorInvalidValue');
                } else {
                    $data[$key] = $bool;
                }
            }
        }

        // Zero-downtime deployments (docs/DESIGN.md section 12.9): customers may turn them on only
        // when the administrator allows it; anybody may turn them off. The timeouts are capped by
        // the server settings.
        if ($has('zeroDowntime')) {
            $bool = self::toBool($values['zeroDowntime']);
            if ($bool === null) {
                $errors['zeroDowntime'][] = pm_Locale::lmsg('errorInvalidValue');
            } elseif ($bool && empty($this->data['zeroDowntime']) && !self::zeroDowntimeAllowed($isAdmin)) {
                $errors['zeroDowntime'][] = pm_Locale::lmsg('errorZeroDowntimeAdmin');
            } else {
                $data['zeroDowntime'] = $bool;
            }
        }
        $caps = self::zeroDowntimeCaps();
        foreach (['readyTimeout' => [self::READY_TIMEOUT_MIN, $caps['ready'], 'errorReadyTimeout'],
                     'drainSeconds' => [self::DRAIN_SECONDS_MIN, $caps['drain'], 'errorDrainSeconds']] as $key => $rule) {
            if (!$has($key)) {
                continue;
            }
            $raw = is_scalar($values[$key]) && !is_bool($values[$key]) ? trim((string)$values[$key]) : 'x';
            if (!ctype_digit($raw) || (int)$raw < $rule[0] || (int)$raw > $rule[1]) {
                $errors[$key][] = pm_Locale::lmsg($rule[2], ['min' => $rule[0], 'max' => $rule[1]]);
                continue;
            }
            $data[$key] = (int)$raw;
        }

        // A toolchain id only makes sense for its runtime: reset it when the runtime changes.
        if ($has('toolchain') || $data['runtime'] !== $this->data['runtime']) {
            $toolchain = $has('toolchain') && is_scalar($values['toolchain']) ? trim((string)$values['toolchain']) : '';
            if (Modules_Runway_Runtime::toolchainKind($data['runtime']) === Modules_Runway_Runtime::TOOLCHAIN_NONE) {
                $toolchain = '';
            } elseif ($toolchain !== '' && !Modules_Runway_Runtime::isValidVersion($data['runtime'], $toolchain)) {
                $errors['toolchain'][] = pm_Locale::lmsg('errorToolchain');
            }
            $data['toolchain'] = $toolchain;
        }

        if ($has('appRoot')) {
            $appRoot = trim(str_replace('\\', '/', is_scalar($values['appRoot']) ? (string)$values['appRoot'] : ''), " /");
            if ($appRoot === '' || strlen($appRoot) > self::MAX_APP_ROOT || !preg_match(self::RE_APP_ROOT, $appRoot)
                || preg_match('#(^|/)\.{1,2}(/|$)#', $appRoot)) {
                $errors['appRoot'][] = pm_Locale::lmsg('errorAppRoot');
            }
            $data['appRoot'] = $appRoot;
        }

        $listenSent = false;
        if ($has('listen')) {
            $listen = is_string($values['listen']) ? $values['listen'] : '';
            if (!in_array($listen, [self::LISTEN_TCP, self::LISTEN_UNIX, self::LISTEN_NONE], true)) {
                $errors['listen'][] = pm_Locale::lmsg('errorListen');
            } else {
                $data['listen'] = $listen;
                $listenSent = true;
            }
        }
        $modeSent = false;
        if ($has('mode')) {
            $mode = is_string($values['mode']) ? $values['mode'] : '';
            if (!in_array($mode, [self::MODE_WEB, self::MODE_PATH, self::MODE_WORKER], true)) {
                $errors['mode'][] = pm_Locale::lmsg('errorMode');
            } else {
                $data['mode'] = $mode;
                $modeSent = true;
            }
        }
        // A worker has no listener, and an app without a listener is a worker. When the two
        // disagree, the one that was changed by this request decides (a form may send both).
        $isWorker = $data['mode'] === self::MODE_WORKER;
        $noListener = $data['listen'] === self::LISTEN_NONE;
        if ($isWorker !== $noListener) {
            $modeChanged = $modeSent && $data['mode'] !== $this->data['mode'];
            $listenChanged = $listenSent && $data['listen'] !== $this->data['listen'];
            if ($modeChanged && $listenChanged) {
                $errors['listen'][] = pm_Locale::lmsg('errorListenMode');
            } elseif ($modeChanged) {
                $data['listen'] = $isWorker ? self::LISTEN_NONE : self::defaultListen($data['runtime']);
            } else {
                $data['mode'] = $noListener ? self::MODE_WORKER : self::MODE_WEB;
            }
        }

        if ($has('mountPath')) {
            $data['mountPath'] = self::normalizeUrlPath($values['mountPath']);
        }
        $mountPath = (string)$data['mountPath'];
        if ($mountPath !== '' || $data['mode'] === self::MODE_PATH) {
            if (!self::isValidUrlPrefix($mountPath)) {
                $errors['mountPath'][] = pm_Locale::lmsg('errorMountPath');
            } elseif (self::isReservedPath($mountPath)) {
                $errors['mountPath'][] = pm_Locale::lmsg('errorMountPathReserved', ['path' => $mountPath]);
            }
        }

        if ($has('staticPaths')) {
            $raw = $values['staticPaths'];
            if (is_string($raw)) {
                $raw = preg_split('/[\r\n,]+/', $raw);
            }
            $paths = [];
            if (!is_array($raw)) {
                $errors['staticPaths'][] = pm_Locale::lmsg('errorStaticPaths');
            } else {
                foreach ($raw as $path) {
                    $path = self::normalizeUrlPath($path);
                    if ($path === '') {
                        continue;
                    }
                    if (!self::isValidUrlPrefix($path)) {
                        $errors['staticPaths'][] = pm_Locale::lmsg('errorStaticPath', ['path' => substr($path, 0, 100)]);
                        continue;
                    }
                    $paths[$path] = true;
                }
                if (count($paths) > self::MAX_STATIC_PATHS) {
                    $errors['staticPaths'][] = pm_Locale::lmsg('errorStaticPathsTooMany', ['max' => self::MAX_STATIC_PATHS]);
                } elseif (strlen(implode('', array_keys($paths))) > self::MAX_STATIC_CHARS) {
                    $errors['staticPaths'][] = pm_Locale::lmsg('errorStaticPathsTooLong', ['max' => self::MAX_STATIC_CHARS]);
                }
            }
            $data['staticPaths'] = array_keys($paths);
        }

        if ($has('healthPath')) {
            $health = is_scalar($values['healthPath']) && !is_bool($values['healthPath']) ? trim((string)$values['healthPath']) : '';
            if ($health !== '' && $health[0] !== '/') {
                $health = '/' . $health;
            }
            if ($health !== '' && (strlen($health) > self::MAX_HEALTH_PATH || !preg_match(self::RE_HEALTH_PATH, $health))) {
                $errors['healthPath'][] = pm_Locale::lmsg('errorHealthPath');
            }
            $data['healthPath'] = $health;
        }

        if ($has('buildCmd')) {
            $buildCmd = trim(str_replace("\r\n", "\n", is_scalar($values['buildCmd']) ? (string)$values['buildCmd'] : ''));
            if (strlen($buildCmd) > self::MAX_BUILD_CMD || preg_match('/[\x00-\x09\x0b-\x1f\x7f]/', $buildCmd)) {
                $errors['buildCmd'][] = pm_Locale::lmsg('errorBuildCmd');
            }
            $data['buildCmd'] = $buildCmd;
        }

        if ($has('startCmd')) {
            $startCmd = trim(is_scalar($values['startCmd']) ? (string)$values['startCmd'] : '');
            if (strlen($startCmd) > self::MAX_START_CMD || preg_match('/[\x00-\x1f\x7f]/', $startCmd)) {
                $errors['startCmd'][] = pm_Locale::lmsg('errorStartCmd');
            }
            $data['startCmd'] = $startCmd;
        }
        if (!isset($errors['startCmd']) && trim((string)$data['startCmd']) === '' && $data['enabled']) {
            $errors['startCmd'][] = pm_Locale::lmsg('errorStartCmdEmpty');
        }
        // A runtime without builds (prebuilt binary) never runs a build command, also not a hidden
        // one left over from another runtime.
        $runtimeMeta = Modules_Runway_Runtime::get($data['runtime']);
        if ($runtimeMeta && isset($runtimeMeta['supports_build']) && $runtimeMeta['supports_build'] === false) {
            $data['buildCmd'] = '';
            unset($errors['buildCmd']);
        }

        $env = null;
        if (array_key_exists('env', $values) && $values['env'] !== null) {
            if (!is_string($values['env'])) {
                // Never treat a malformed value (array, object, boolean) as "no variables".
                $errors['env'][] = pm_Locale::lmsg('errorInvalidValue');
            } else {
                $envErrors = [];
                $env = self::parseEnv($values['env'], $envErrors);
                if ($envErrors) {
                    $errors['env'] = $envErrors;
                }
            }
        }

        $limitsChanged = false;
        if ($isAdmin) {
            foreach (['memoryMb' => 1048576, 'cpuPercent' => 25600, 'tasks' => 1000000] as $key => $max) {
                if (!$has($key)) {
                    continue;
                }
                $raw = is_scalar($values[$key]) && !is_bool($values[$key]) ? trim((string)$values[$key]) : 'x';
                if ($raw === '') {
                    $raw = '0';
                }
                if (!ctype_digit($raw) || (int)$raw > $max) {
                    $errors[$key][] = pm_Locale::lmsg('errorLimit', ['name' => pm_Locale::lmsg('field' . ucfirst($key))]);
                    continue;
                }
                $data[$key] = (int)$raw;
                $limitsChanged = true;
            }
        }

        // The stored JSON must fit into Plesk's domain setting (see MAX_CONFIG_CHARS). Reported on the
        // longest variable field that this request sent, so the form can show it next to that field.
        if (!$errors) {
            $length = self::encodedLength($data);
            if ($length > self::MAX_CONFIG_CHARS) {
                $field = 'buildCmd';
                $longest = -1;
                foreach (['buildCmd', 'startCmd', 'staticPaths', 'healthPath', 'appRoot', 'mountPath'] as $candidate) {
                    $size = strlen(json_encode(isset($data[$candidate]) ? $data[$candidate] : ''));
                    if ($has($candidate) && $size > $longest) {
                        $field = $candidate;
                        $longest = $size;
                    }
                }
                $errors[$field][] = pm_Locale::lmsg('errorConfigTooLarge', ['length' => $length, 'max' => self::MAX_CONFIG_CHARS]);
            }
        }

        // Applications per subscription: checked when an application gets enabled, so lowering
        // the limit never blocks saving applications that already run.
        if (!$errors && !empty($data['enabled']) && !$this->isEnabled()) {
            $max = Modules_Runway_Settings::get('maxAppsPerSubscription');
            if ($max > 0 && self::countOtherEnabledApps($this->domain) >= $max) {
                $errors['enabled'][] = pm_Locale::lmsg('errorMaxApps', ['max' => $max]);
            }
        }

        if (!$errors) {
            $this->data = $data;
            $this->limitsChanged = $this->limitsChanged || $limitsChanged;
            if ($env !== null) {
                $this->env = $env;
            }
        }
        return $errors;
    }

    /**
     * Length in characters of the configuration as stored by save() (dom_param.val counts characters).
     *
     * @param array $data
     * @return int
     */
    private static function encodedLength(array $data)
    {
        $json = (string)json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        return function_exists('mb_strlen') ? mb_strlen($json, 'UTF-8') : strlen($json);
    }

    /**
     * @param mixed $value
     * @return bool|null null when the value is not a boolean
     */
    private static function toBool($value)
    {
        if (is_bool($value)) {
            return $value;
        }
        if (is_int($value) && ($value === 0 || $value === 1)) {
            return $value === 1;
        }
        if (is_string($value)) {
            $value = strtolower(trim($value));
            if (in_array($value, ['1', 'true', 'on', 'yes'], true)) {
                return true;
            }
            if (in_array($value, ['0', 'false', 'off', 'no', ''], true)) {
                return false;
            }
        }
        return null;
    }

    /**
     * Parses KEY=VALUE lines (dotenv style). Lines starting with # are comments.
     * One level of matching surrounding quotes is removed from values.
     *
     * @param string $text
     * @param string[] $errors
     * @return array
     */
    public static function parseEnv($text, array &$errors)
    {
        $env = [];
        $lines = preg_split('/\r\n|\r|\n/', (string)$text);
        foreach ($lines as $index => $line) {
            $trimmed = trim($line);
            if ($trimmed === '' || $trimmed[0] === '#') {
                continue;
            }
            if (strpos($trimmed, 'export ') === 0) {
                $trimmed = ltrim(substr($trimmed, 7));
            }
            $pos = strpos($trimmed, '=');
            if ($pos === false) {
                $errors[] = pm_Locale::lmsg('errorEnvLine', ['line' => $index + 1]);
                continue;
            }
            $key = trim(substr($trimmed, 0, $pos));
            $value = trim(substr($trimmed, $pos + 1));
            if (strlen($value) >= 2 && ($value[0] === '"' || $value[0] === "'") && substr($value, -1) === $value[0]) {
                $value = substr($value, 1, -1);
            }
            if (!preg_match(self::RE_ENV_KEY, $key)) {
                $errors[] = pm_Locale::lmsg('errorEnvKey', ['key' => $key, 'line' => $index + 1]);
                continue;
            }
            if (in_array($key, self::$reservedEnv, true)) {
                $errors[] = pm_Locale::lmsg('errorEnvReserved', ['key' => $key]);
                continue;
            }
            if (in_array($key, self::$loaderEnv, true)) {
                $errors[] = pm_Locale::lmsg('errorEnvLoader', ['key' => $key]);
                continue;
            }
            if (strlen($value) > 8192 || preg_match('/[\x00-\x08\x0a-\x1f\x7f]/', $value)) {
                $errors[] = pm_Locale::lmsg('errorEnvValue', ['key' => $key]);
                continue;
            }
            $env[$key] = $value;
        }
        if (count($env) > 200) {
            $errors[] = pm_Locale::lmsg('errorEnvTooMany');
        }
        return $env;
    }

    /**
     * @param array $env
     * @return string
     */
    public static function formatEnv(array $env)
    {
        $lines = [];
        foreach ($env as $key => $value) {
            $value = (string)$value;
            $needsQuotes = $value !== trim($value) || ($value !== '' && ($value[0] === '"' || $value[0] === "'"));
            $lines[] = $key . '=' . ($needsQuotes ? '"' . $value . '"' : $value);
        }
        return implode("\n", $lines);
    }

    /**
     * Payload for the root helper (snake_case, docs/DESIGN.md section 7).
     *
     * @param bool $restart
     * @return array
     */
    public function payload($restart = true)
    {
        list($portMin, $portMax) = Modules_Runway_Settings::portRange();
        $payload = [
            'domain_id' => (int)$this->domain->getId(),
            'domain' => (string)$this->domain->getName(),
            'sysuser' => (string)$this->domain->getSysUserLogin(),
            'app_root' => (string)$this->data['appRoot'],
            'runtime' => (string)$this->data['runtime'],
            'toolchain' => (string)$this->data['toolchain'],
            'build_cmd' => (string)$this->data['buildCmd'],
            'start_cmd' => (string)$this->data['startCmd'],
            'port' => (int)$this->data['port'],
            'port_range' => [$portMin, $portMax],
            'enabled' => (bool)$this->data['enabled'],
            'suspended' => !self::domainIsActive($this->domain),
            'auto_deploy' => (bool)$this->data['autoDeploy'],
            'listen' => (string)$this->data['listen'],
            'mode' => (string)$this->data['mode'],
            // Only meaningful in path mode / for applications that listen.
            'mount_path' => $this->data['mode'] === self::MODE_PATH ? (string)$this->data['mountPath'] : '',
            'static_paths' => is_array($this->data['staticPaths']) ? array_values($this->data['staticPaths']) : [],
            'health_path' => $this->data['listen'] !== self::LISTEN_NONE ? (string)$this->data['healthPath'] : '',
            // Zero-downtime deployments (docs/DESIGN.md section 12): never for workers; the
            // timeouts within the current caps of the server settings.
            'zero_downtime' => $this->data['listen'] !== self::LISTEN_NONE && !empty($this->data['zeroDowntime']),
            'ready_timeout' => self::clampSetting($this->data, 'readyTimeout', self::READY_TIMEOUT_MIN, self::zeroDowntimeCaps()['ready'], self::READY_TIMEOUT_DEFAULT),
            'drain_seconds' => self::clampSetting($this->data, 'drainSeconds', self::DRAIN_SECONDS_MIN, self::zeroDowntimeCaps()['drain'], self::DRAIN_SECONDS_DEFAULT),
            'build_timeout' => Modules_Runway_Settings::get('buildTimeout'),
            'limits' => [
                'memory_mb' => (int)$this->data['memoryMb'],
                'cpu_percent' => (int)$this->data['cpuPercent'],
                'tasks' => (int)$this->data['tasks'],
            ],
            'build_limits' => [
                'memory_mb' => Modules_Runway_Settings::get('buildMemoryMb'),
                'cpu_percent' => Modules_Runway_Settings::get('buildCpuPercent'),
                'tasks' => Modules_Runway_Settings::get('buildTasks'),
            ],
            'restart' => (bool)$restart,
        ];
        // When the variables were neither loaded nor edited, the helper keeps the stored ones.
        if ($this->env !== null) {
            $payload['env'] = (object)$this->env;
        }
        return $payload;
    }

    /**
     * @param array $data Configuration
     * @param string $key
     * @param int $min
     * @param int $max
     * @param int $default Used when the stored value is missing
     * @return int The stored value within [$min, $max]
     */
    private static function clampSetting(array $data, $key, $min, $max, $default)
    {
        $value = isset($data[$key]) && is_numeric($data[$key]) ? (int)$data[$key] : $default;
        return max($min, min($max, $value));
    }

    /**
     * @return array Environment variables (loaded from the root helper on first use)
     * @throws Modules_Runway_Exception
     */
    public function getEnv()
    {
        if ($this->env === null) {
            $env = [];
            if ($this->configured) {
                // Assign only after success: a failed load must leave env null, otherwise a
                // later save would send an empty set and wipe the stored variables.
                $result = Modules_Runway_Helper::call('app-config', ['domain_id' => (int)$this->domain->getId()]);
                if (isset($result['config']['env']) && is_array($result['config']['env'])) {
                    $env = $result['config']['env'];
                }
            }
            $this->env = $env;
        }
        return $this->env;
    }

    /**
     * Sends the configuration to the helper, persists it and refreshes the web server config.
     *
     * @param bool $restart Restart the service even if it is already running
     * @param bool $start Start the service at all (false when a deploy job builds and starts it)
     * @param bool $resume An explicit save by the user: clears a "stopped" application (Stop) so it
     *                     runs again. Reconcile and other automatic re-applies keep it stopped.
     * @return array Helper response
     * @throws Modules_Runway_Exception
     */
    public function apply($restart = true, $start = true, $resume = false)
    {
        $payload = $this->payload($restart);
        $payload['start'] = (bool)$start;
        $payload['resume'] = (bool)$resume;
        $result = Modules_Runway_Helper::call('app-apply', $payload);
        $this->data['port'] = isset($result['port']) ? (int)$result['port'] : 0;
        // The web server snippet follows the helper: the zero-downtime pointer while a slot runs.
        $this->data['switchable'] = !empty($result['switchable']);
        $this->configured = true;
        $this->save();
        Modules_Runway_WebConfig::reconfigure($this->domain);
        return $result;
    }

    /**
     * Applies the configuration saved in the panel. When the application is enabled and
     * has a build command, it is built first; the deploy job (re)starts it only after a
     * successful build, so a running app keeps serving the previous version meanwhile.
     *
     * @return array ['build' => bool (a build was requested), 'buildError' => string|null,
     *               'job' => string|null (the deploy job of a build or of a zero-downtime switch)]
     * @throws Modules_Runway_Exception When the configuration could not be applied
     */
    public function applyAndDeploy()
    {
        $build = !empty($this->data['enabled'])
            && trim((string)$this->data['buildCmd']) !== ''
            && self::domainIsActive($this->domain);
        $result = $this->apply(!$build, !$build, true);
        // Without a build, the restart of a zero-downtime application is a switch job of app-apply.
        $job = isset($result['job']) && is_string($result['job']) && $result['job'] !== '' ? $result['job'] : null;
        $buildError = null;
        if ($build) {
            try {
                $deploy = Modules_Runway_Helper::call('app-deploy', ['domain_id' => (int)$this->domain->getId(), 'build' => true]);
                $job = isset($deploy['job']) ? (string)$deploy['job'] : null;
            } catch (Modules_Runway_Exception $e) {
                // The configuration is saved at this point; only the build could not start.
                $buildError = $e->getMessage();
            }
        }
        return ['build' => $build, 'buildError' => $buildError, 'job' => $job];
    }

    /**
     * Stops and deletes the service and forgets the configuration. The web server config is
     * regenerated first, so the port is only released once no vhost points to it anymore.
     * Admin-set resource limits are kept.
     *
     * @throws Modules_Runway_Exception
     */
    public function remove()
    {
        $this->domain->setSetting(self::SETTING_KEY, '');
        Modules_Runway_WebConfig::reconfigure($this->domain);
        Modules_Runway_Helper::call('app-remove', ['domain_id' => (int)$this->domain->getId()]);
        $this->configured = false;
        $this->data = self::defaults($this->domain, self::RUNTIME_GO);
        $this->env = null;
    }

    /**
     * Persists the configuration in the domain settings (limits only when an admin set them).
     */
    public function save()
    {
        $this->domain->setSetting(self::SETTING_KEY, json_encode($this->data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
        if ($this->limitsChanged) {
            $this->domain->setSetting(self::LIMITS_KEY, json_encode($this->limits()));
        }
    }

    /**
     * Loads everything the domain page needs with one helper call (installed toolchains,
     * stored variables, service status, project inspection, default commands) and primes
     * the environment variable cache.
     *
     * @param array[] $documentRoots documentRoots(): the inspection names the one the
     *                               application root lies in with symbolic links resolved
     * @return array
     * @throws Modules_Runway_Exception
     */
    public function loadPage(array $documentRoots = [])
    {
        $result = Modules_Runway_Helper::call('app-page', [
            'domain_id' => (int)$this->domain->getId(),
            'sysuser' => (string)$this->domain->getSysUserLogin(),
            'app_root' => (string)$this->data['appRoot'],
            'runtime' => (string)$this->data['runtime'],
            'document_roots' => array_column($documentRoots, 'path'),
        ]);
        if ($this->env === null) {
            $this->env = isset($result['config']['env']) && is_array($result['config']['env'])
                ? $result['config']['env']
                : [];
        }
        return $result;
    }

    /**
     * @return array Service status from the helper
     */
    public function status()
    {
        return Modules_Runway_Helper::call('app-status', ['domain_id' => (int)$this->domain->getId()]);
    }

    /**
     * Writes the minimal sample application of a runtime into the application root, as the
     * subscription's system user (helper app-sample). The configuration is not changed.
     * The helper refuses a non-empty application root unless $force is set.
     *
     * @param string $runtime
     * @param string $listen tcp|unix|none
     * @param string $toolchain Toolchain the sample should target ('' = the helper picks one)
     * @param bool $force Overwrite files in a non-empty application root
     * @return array ['written' => string[] (relative paths), 'toolchain' => string|null (chosen by
     *               the helper), 'defaults' => array|null ({build_cmd, start_cmd} for the sample)]
     * @throws Modules_Runway_Exception
     */
    public function writeSample($runtime, $listen, $toolchain = '', $force = false)
    {
        $payload = [
            'domain_id' => (int)$this->domain->getId(),
            'sysuser' => (string)$this->domain->getSysUserLogin(),
            'app_root' => (string)$this->data['appRoot'],
            'runtime' => (string)$runtime,
            'listen' => (string)$listen,
            'force' => (bool)$force,
        ];
        if ((string)$toolchain !== '') {
            $payload['toolchain'] = (string)$toolchain;
        }
        $result = Modules_Runway_Helper::call('app-sample', $payload);
        $written = isset($result['written']) && is_array($result['written']) ? $result['written'] : [];
        return [
            'written' => array_values(array_map('strval', array_filter($written, 'is_scalar'))),
            'toolchain' => isset($result['toolchain']) && is_scalar($result['toolchain']) ? (string)$result['toolchain'] : null,
            'defaults' => isset($result['defaults']) && is_array($result['defaults']) ? $result['defaults'] : null,
        ];
    }

    /**
     * Starts a deploy job in fetch mode: the helper downloads the URL as the subscription's
     * system user into the application root, verifies the checksum, makes the file executable
     * or extracts the archive, and restarts the application.
     *
     * @param array $fetch Output of validateFetch(): url, sha256 ('' = no check), extract,
     *                     filename ('' = the helper derives it), build (run the build command after
     *                     the download)
     * @return string Job id (deploy-<domain id>)
     * @throws Modules_Runway_Exception
     */
    public function fetch(array $fetch)
    {
        $result = Modules_Runway_Helper::call('app-deploy', [
            'domain_id' => (int)$this->domain->getId(),
            'fetch' => [
                'url' => (string)$fetch['url'],
                'sha256' => (string)$fetch['sha256'],
                'extract' => (bool)$fetch['extract'],
                'filename' => (string)$fetch['filename'],
                'build' => (bool)$fetch['build'],
            ],
        ]);
        return isset($result['job']) ? (string)$result['job'] : 'deploy-' . (int)$this->domain->getId();
    }

    /**
     * Validates the input of a fetch request (api/app/fetch).
     *
     * @param array $values url, sha256, extract, filename, build (all but url optional)
     * @param array $errors Validation errors keyed by field (output)
     * @return array|null url, sha256, extract, filename, build; null when invalid
     */
    public static function validateFetch(array $values, array &$errors)
    {
        $filename = isset($values['filename']) && is_scalar($values['filename']) && !is_bool($values['filename'])
            ? trim((string)$values['filename']) : '';
        if ($filename !== '' && !preg_match('/^[A-Za-z0-9_+-][A-Za-z0-9._+-]{0,127}$/', $filename)) {
            $errors['filename'][] = pm_Locale::lmsg('errorFetchFilename');
        }
        $build = false;
        if (isset($values['build'])) {
            $build = self::toBool($values['build']);
            if ($build === null) {
                $errors['build'][] = pm_Locale::lmsg('errorInvalidValue');
            }
        }
        $url = isset($values['url']) && is_string($values['url']) ? trim($values['url']) : '';
        $parts = $url !== '' ? parse_url($url) : false;
        if ($url === '' || strlen($url) > 2048 || preg_match('/[\x00-\x20\x7f]/', $url) || !is_array($parts)
            || !isset($parts['scheme'], $parts['host']) || $parts['host'] === '') {
            $errors['url'][] = pm_Locale::lmsg('errorFetchUrl');
        } elseif (strtolower($parts['scheme']) !== 'https'
            && !(strtolower($parts['scheme']) === 'http' && self::insecureFetchAllowed())) {
            // The helper downloads over https only (plain http only with its root-only test flag).
            $errors['url'][] = pm_Locale::lmsg('errorFetchHttps');
        }
        $sha256 = isset($values['sha256']) && is_scalar($values['sha256']) && !is_bool($values['sha256'])
            ? strtolower(trim((string)$values['sha256'])) : '';
        if ($sha256 !== '' && !preg_match('/^[0-9a-f]{64}$/', $sha256)) {
            $errors['sha256'][] = pm_Locale::lmsg('errorFetchSha256');
        }
        $extract = false;
        if (isset($values['extract'])) {
            $extract = self::toBool($values['extract']);
            if ($extract === null) {
                $errors['extract'][] = pm_Locale::lmsg('errorInvalidValue');
            }
        }
        return $errors
            ? null
            : ['url' => $url, 'sha256' => $sha256, 'extract' => (bool)$extract, 'filename' => $filename, 'build' => (bool)$build];
    }

    /**
     * True when the helper accepts plain http:// downloads (root-only test flag
     * /etc/runway/allow-insecure-fetch, never set on production servers).
     *
     * @return bool
     */
    private static function insecureFetchAllowed()
    {
        try {
            $info = Modules_Runway_Helper::call('info');
        } catch (Exception $e) {
            return false;
        }
        return !empty($info['fetch_insecure']);
    }

    /**
     * Inspects the application root as the subscription's system user.
     *
     * @param string|null $appRoot Relative path, defaults to the configured one
     * @param array[] $documentRoots documentRoots(): "document_root" of the result names the one
     *                               the application root lies in with symbolic links resolved
     * @return array
     */
    public function inspect($appRoot = null, array $documentRoots = [])
    {
        return Modules_Runway_Helper::call('app-inspect', [
            'sysuser' => (string)$this->domain->getSysUserLogin(),
            'app_root' => (string)($appRoot !== null ? $appRoot : $this->data['appRoot']),
            'document_roots' => array_column($documentRoots, 'path'),
        ]);
    }
}
