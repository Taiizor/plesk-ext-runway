<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Logic of the command line interface "plesk ext runway --<command> [arguments]"
 * (docs/DESIGN.md section 9). The pm_Hook_ApiCli hook (hooks/ApiCli.php) only forwards the
 * command and its arguments here. Plesk runs these commands in the administrator's context.
 *
 * Output is plain text. Exit codes: 0 success, 1 the operation failed (helper error,
 * validation error, failed job), 2 usage error (missing or invalid argument, unknown domain).
 *
 * Commands:
 *   --list                                       configured applications and their state
 *   --status <domain>                            details of one application
 *   --start|--stop|--restart <domain>            service control
 *   --deploy <domain> [-no-wait]                 build and restart (waits for the job by default)
 *   --enable|--disable <domain>                  enable or disable a configured application
 *   --toolchains                                 installed toolchains per runtime
 *   --install-toolchain <runtime> <version> [-no-wait]
 *   --reconcile                                  converge the services with Plesk now
 * <domain> is a domain name or a numeric domain id.
 */
class Modules_Runway_Cli
{
    const EXIT_OK = 0;
    const EXIT_FAILED = 1;
    const EXIT_USAGE = 2;

    /** Seconds between two job status polls. */
    const POLL_SECONDS = 2;

    /** @var array command => usage (arguments after the command) */
    private static $usage = [
        'list' => '',
        'status' => '<domain>',
        'start' => '<domain>',
        'stop' => '<domain>',
        'restart' => '<domain>',
        'deploy' => '<domain> [-no-wait]',
        'enable' => '<domain>',
        'disable' => '<domain>',
        'toolchains' => '',
        'install-toolchain' => '<runtime> <version> [-no-wait]',
        'reconcile' => '',
    ];

    /** @var array command => flags it accepts */
    private static $flags = [
        'deploy' => ['no-wait'],
        'install-toolchain' => ['no-wait'],
    ];

    /** @var callable */
    private $stdout;

    /** @var callable */
    private $stderr;

    /** @var string Output collected when no stdout callback is given */
    private $buffer = '';

    /**
     * @param callable|null $stdout Receives standard output text (default: buffered, see output())
     * @param callable|null $stderr Receives error text (default: same as $stdout)
     */
    public function __construct(?callable $stdout = null, ?callable $stderr = null)
    {
        $this->stdout = $stdout ?: function ($text) {
            $this->buffer .= $text;
        };
        $this->stderr = $stderr ?: $this->stdout;
    }

    /**
     * @return string Buffered output (only when no stdout callback was given)
     */
    public function output()
    {
        return $this->buffer;
    }

    /**
     * @return string[] Supported commands
     */
    public static function commands()
    {
        return array_keys(self::$usage);
    }

    /**
     * Runs one command.
     *
     * @param string $command Command name without the leading "--"
     * @param string[] $arguments Positional arguments and "-flag" options
     * @return int Exit code
     */
    public function execute($command, array $arguments)
    {
        try {
            if (!isset(self::$usage[$command])) {
                throw new InvalidArgumentException('Unknown command: ' . $command);
            }
            list($args, $flags) = $this->parse($command, $arguments);
            switch ($command) {
                case 'list':
                    return $this->listApps();
                case 'status':
                    return $this->status($this->domain($command, $args));
                case 'start':
                case 'stop':
                case 'restart':
                    return $this->action($this->domain($command, $args), $command);
                case 'deploy':
                    return $this->deploy($this->domain($command, $args), empty($flags['no-wait']));
                case 'enable':
                case 'disable':
                    return $this->enable($this->domain($command, $args), $command === 'enable');
                case 'toolchains':
                    return $this->toolchains();
                case 'install-toolchain':
                    return $this->installToolchain($command, $args, empty($flags['no-wait']));
                case 'reconcile':
                    return $this->reconcile();
            }
        } catch (InvalidArgumentException $e) {
            $this->error($e->getMessage());
            if (isset(self::$usage[$command])) {
                $this->error('Usage: plesk ext runway --' . $command . (self::$usage[$command] !== '' ? ' ' . self::$usage[$command] : ''));
            }
            return self::EXIT_USAGE;
        } catch (pm_Exception $e) {
            // Modules_Runway_Exception and Modules_Runway_ValidationException included.
            $this->error('Error: ' . $e->getMessage());
            return self::EXIT_FAILED;
        } catch (Exception $e) {
            $this->error('Error: ' . get_class($e) . ': ' . $e->getMessage());
            return self::EXIT_FAILED;
        }
        return self::EXIT_FAILED;
    }

    // -----------------------------------------------------------------------
    // Commands
    // -----------------------------------------------------------------------

    /**
     * --list: one line per configured application.
     *
     * @return int
     */
    private function listApps()
    {
        $states = $this->helperStates();
        $rows = [];
        foreach (pm_Domain::getAllDomains() as $domain) {
            $config = Modules_Runway_App::storedConfig($domain);
            if ($config === null) {
                continue;
            }
            $id = (int)$domain->getId();
            $state = isset($states[$id]) ? $states[$id] : null;
            $listen = isset($config['listen']) ? (string)$config['listen'] : Modules_Runway_App::LISTEN_TCP;
            $rows[] = [
                (string)$domain->getName(),
                isset($config['runtime']) ? (string)$config['runtime'] : '-',
                !empty($config['toolchain']) ? (string)$config['toolchain'] : '-',
                $listen,
                isset($config['mode']) ? (string)$config['mode'] . (!empty($config['mountPath']) && $config['mode'] === Modules_Runway_App::MODE_PATH ? ' ' . $config['mountPath'] : '') : Modules_Runway_App::MODE_WEB,
                $listen === Modules_Runway_App::LISTEN_TCP && !empty($config['port']) ? (string)(int)$config['port'] : '-',
                !empty($config['enabled']) ? 'yes' : 'no',
                Modules_Runway_App::uiState($config, $state),
            ];
        }
        if (!$rows) {
            $this->line('No application is configured.');
            return self::EXIT_OK;
        }
        usort($rows, function ($a, $b) {
            return strcmp($a[0], $b[0]);
        });
        $this->table(['DOMAIN', 'RUNTIME', 'TOOLCHAIN', 'LISTEN', 'MODE', 'PORT', 'ENABLED', 'STATE'], $rows);
        return self::EXIT_OK;
    }

    /**
     * --status <domain>
     *
     * @param pm_Domain $domain
     * @return int
     */
    private function status(pm_Domain $domain)
    {
        $app = new Modules_Runway_App($domain);
        $facts = [['Domain', $domain->getName() . ' (#' . (int)$domain->getId() . ')']];
        if (!$app->isConfigured()) {
            $facts[] = ['Application', 'not configured'];
            $this->facts($facts);
            return self::EXIT_OK;
        }
        $config = $app->config();
        $status = $app->status();
        $service = isset($status['service']) && is_array($status['service']) ? $status['service'] : [];
        $helperState = [
            'active_state' => isset($service['active_state']) ? $service['active_state'] : null,
            'suspended' => !empty($status['suspended']),
            'tampered' => !empty($status['tampered']),
        ];
        $facts[] = ['Application', $config['enabled'] ? 'enabled' : 'disabled'];
        $facts[] = ['State', Modules_Runway_App::uiState($config, $helperState)
            . (isset($service['active_state']) ? ' (' . $service['active_state'] . '/' . (isset($service['sub_state']) ? $service['sub_state'] : '?') . ')' : '')];
        if (!empty($status['tampered'])) {
            $facts[] = ['Stopped', 'by Runway: the socket path was tampered with ('
                . (isset($status['tampered_detail']) ? (string)$status['tampered_detail'] : '') . '); --start runs it again'];
        } elseif (!empty($status['stopped'])) {
            $facts[] = ['Stopped', 'yes: it stays stopped (also after a reboot or a deployment) until --start or --restart'];
        }
        $facts[] = ['Runtime', $config['runtime'] . ($config['toolchain'] !== '' ? ' ' . $config['toolchain'] : '')];
        $facts[] = ['App root', $config['appRoot']];
        $facts[] = ['Mode', $config['mode'] . ($config['mode'] === Modules_Runway_App::MODE_PATH ? ' ' . $config['mountPath'] : '')];
        if ($config['listen'] === Modules_Runway_App::LISTEN_TCP) {
            $facts[] = ['Listen', 'tcp 127.0.0.1:' . (isset($status['port']) ? (int)$status['port'] : $config['port'])];
        } elseif ($config['listen'] === Modules_Runway_App::LISTEN_UNIX) {
            $facts[] = ['Listen', 'unix ' . (isset($status['socket']) ? $status['socket'] : Modules_Runway_App::socketPath($domain))];
        } else {
            $facts[] = ['Listen', 'none (worker)'];
        }
        if ($config['staticPaths']) {
            $facts[] = ['Static paths', implode(' ', $config['staticPaths'])];
        }
        if (!empty($service['main_pid'])) {
            $facts[] = ['PID', (string)(int)$service['main_pid']];
        }
        if (isset($service['memory_bytes']) && $service['memory_bytes'] !== null) {
            $facts[] = ['Memory', self::bytes($service['memory_bytes'])];
        }
        if (!empty($service['started_at'])) {
            $facts[] = ['Started', (string)$service['started_at']];
        }
        if (isset($service['restarts'])) {
            $facts[] = ['Restarts', (string)(int)$service['restarts']];
        }
        if (isset($status['listener'])) {
            $facts[] = ['Listener', (string)$status['listener'] . (!empty($status['listener_detail']) ? ' (' . $status['listener_detail'] . ')' : '')];
        }
        if (isset($status['health'])) {
            $health = $status['health'];
            if (is_array($health)) {
                $health = isset($health['state']) ? $health['state'] : (isset($health['status']) ? $health['status'] : json_encode($health));
            }
            $facts[] = ['Health', (string)$health . ($config['healthPath'] !== '' ? ' (' . $config['healthPath'] . ')' : '')];
        }
        if (isset($status['deploy']) && is_array($status['deploy'])) {
            $deploy = $status['deploy'];
            $state = isset($deploy['state']) ? (string)$deploy['state'] : 'none';
            $facts[] = ['Last deploy', $state === 'none' ? 'none' : $state
                . (!empty($deploy['finished_at']) ? ', finished ' . $deploy['finished_at'] : '')
                . (!empty($deploy['message']) ? ': ' . $deploy['message'] : '')];
        }
        $url = Modules_Runway_App::appUrl($domain, $config);
        if ($url !== null) {
            $facts[] = ['URL', $url];
        }
        $this->facts($facts);
        return self::EXIT_OK;
    }

    /**
     * --start, --stop, --restart <domain>
     *
     * @param pm_Domain $domain
     * @param string $action
     * @return int
     */
    private function action(pm_Domain $domain, $action)
    {
        $this->requireConfigured($domain);
        Modules_Runway_Helper::call('app-action', ['domain_id' => (int)$domain->getId(), 'action' => $action]);
        $this->line(pm_Locale::lmsg('messageAction_' . $action));
        return self::EXIT_OK;
    }

    /**
     * --deploy <domain> [-no-wait]: build and restart.
     *
     * @param pm_Domain $domain
     * @param bool $wait Wait for the deploy job and report its result
     * @return int
     */
    private function deploy(pm_Domain $domain, $wait)
    {
        $this->requireConfigured($domain);
        $result = Modules_Runway_Helper::call('app-deploy', ['domain_id' => (int)$domain->getId(), 'build' => true]);
        $job = isset($result['job']) ? (string)$result['job'] : 'deploy-' . (int)$domain->getId();
        $this->line('The build of ' . $domain->getName() . ' has started (job ' . $job . ').');
        if (!$wait) {
            return self::EXIT_OK;
        }
        return $this->waitForJob($job, Modules_Runway_Settings::get('buildTimeout') + 300);
    }

    /**
     * --enable, --disable <domain>
     *
     * @param pm_Domain $domain
     * @param bool $enabled
     * @return int
     */
    private function enable(pm_Domain $domain, $enabled)
    {
        $app = $this->requireConfigured($domain);
        $errors = $app->update(['enabled' => $enabled], true);
        if ($errors) {
            foreach ($errors as $field => $messages) {
                foreach ((array)$messages as $message) {
                    $this->error($field . ': ' . $message);
                }
            }
            return self::EXIT_FAILED;
        }
        $result = $app->applyAndDeploy();
        if ($result['buildError'] !== null) {
            $this->error(pm_Locale::lmsg('messageSavedBuildNotStarted', ['details' => $result['buildError']]));
            return self::EXIT_FAILED;
        }
        if ($result['build']) {
            $this->line('The application of ' . $domain->getName() . ' is enabled; it is being built and will start when the build succeeds.');
        } else {
            $this->line('The application of ' . $domain->getName() . ' is ' . ($enabled ? 'enabled.' : 'disabled.'));
        }
        return self::EXIT_OK;
    }

    /**
     * --toolchains: installed toolchains per runtime, their users, build dependencies.
     *
     * @return int
     */
    private function toolchains()
    {
        $data = Modules_Runway_Helper::call('toolchains');
        $runtimes = isset($data['runtimes']) && is_array($data['runtimes']) ? $data['runtimes'] : [];
        foreach (Modules_Runway_Runtime::all() as $meta) {
            $key = (string)$meta['key'];
            $kind = isset($meta['toolchain']) ? (string)$meta['toolchain'] : Modules_Runway_Runtime::TOOLCHAIN_NONE;
            $label = isset($meta['label']) ? (string)$meta['label'] : $key;
            $this->line($label . ' (' . $key . ', ' . $kind . ')');
            if ($kind === Modules_Runway_Runtime::TOOLCHAIN_NONE) {
                $this->line('  no toolchain needed');
                continue;
            }
            $entry = isset($runtimes[$key]) && is_array($runtimes[$key]) ? $runtimes[$key] : [];
            $installed = isset($entry['installed']) && is_array($entry['installed']) ? $entry['installed'] : [];
            $inUse = isset($entry['in_use']) && is_array($entry['in_use']) ? $entry['in_use'] : [];
            if (!$installed) {
                $this->line('  none installed');
                continue;
            }
            $rows = [];
            foreach ($installed as $toolchain) {
                $id = isset($toolchain['id']) ? (string)$toolchain['id'] : '?';
                $users = isset($inUse[$id]) && is_array($inUse[$id]) ? implode(', ', $inUse[$id]) : '';
                $rows[] = ['  ' . $id, isset($toolchain['path']) ? (string)$toolchain['path'] : '', $users !== '' ? 'used by ' . $users : 'unused'];
            }
            $this->table(null, $rows);
        }
        if (isset($data['build_deps']) && is_array($data['build_deps']) && $data['build_deps']) {
            $deps = [];
            foreach ($data['build_deps'] as $name => $present) {
                $deps[] = $name . ' ' . ($present ? 'yes' : 'no');
            }
            $this->line('Build dependencies: ' . implode(', ', $deps));
        }
        if (isset($data['job']['state']) && $data['job']['state'] !== 'none') {
            $this->line('Last toolchain job: ' . (isset($data['job']['title']) ? $data['job']['title'] . ': ' : '') . $data['job']['state']);
        }
        return self::EXIT_OK;
    }

    /**
     * --install-toolchain <runtime> <version> [-no-wait]
     *
     * @param string $command
     * @param string[] $args
     * @param bool $wait
     * @return int
     */
    private function installToolchain($command, array $args, $wait)
    {
        if (count($args) !== 2) {
            throw new InvalidArgumentException('Expected a runtime and a version.');
        }
        list($runtime, $version) = $args;
        $keys = Modules_Runway_Runtime::keys();
        if (!in_array($runtime, $keys, true)) {
            throw new InvalidArgumentException('Unknown runtime "' . $runtime . '". Runtimes: ' . implode(', ', $keys) . '.');
        }
        if (Modules_Runway_Runtime::toolchainKind($runtime) === Modules_Runway_Runtime::TOOLCHAIN_NONE) {
            throw new InvalidArgumentException('The ' . $runtime . ' runtime needs no toolchain.');
        }
        if (!Modules_Runway_Runtime::isValidVersion($runtime, $version)) {
            throw new InvalidArgumentException('"' . $version . '" is not a valid ' . $runtime . ' version.');
        }
        $result = Modules_Runway_Helper::call('toolchain-install', ['runtime' => $runtime, 'version' => $version]);
        $job = isset($result['job']) && is_string($result['job']) ? $result['job'] : 'admin';
        $this->line('The installation of ' . $runtime . ' ' . $version . ' has started (job ' . $job . ').');
        if (!$wait) {
            return self::EXIT_OK;
        }
        return $this->waitForJob($job, 3 * 3600);
    }

    /**
     * --reconcile
     *
     * @return int
     */
    private function reconcile()
    {
        $summary = Modules_Runway_Reconcile::run();
        if (!empty($summary['paused'])) {
            $this->line('Paused: /var/lib/runway/pause-reconcile exists (test flag, honoured for one hour)');
        }
        $this->line('Removed: ' . ($summary['removed'] ? '#' . implode(', #', $summary['removed']) : 'none'));
        $this->line('Re-applied: ' . ($summary['reapplied'] ? '#' . implode(', #', $summary['reapplied']) : 'none'));
        foreach ($summary['errors'] as $error) {
            $this->error('Error: ' . $error);
        }
        return $summary['errors'] ? self::EXIT_FAILED : self::EXIT_OK;
    }

    // -----------------------------------------------------------------------
    // Plumbing
    // -----------------------------------------------------------------------

    /**
     * Splits the arguments into positional arguments and "-flag" options.
     *
     * @param string $command
     * @param string[] $arguments
     * @return array [string[] positional, array flag => true]
     */
    private function parse($command, array $arguments)
    {
        $args = [];
        $flags = [];
        $allowed = isset(self::$flags[$command]) ? self::$flags[$command] : [];
        foreach ($arguments as $argument) {
            $argument = (string)$argument;
            if (strpos($argument, '--') === 0) {
                throw new InvalidArgumentException('Only one command can be given at a time (' . $argument . ').');
            }
            if (strlen($argument) > 1 && $argument[0] === '-') {
                $flag = strtolower(substr($argument, 1));
                if (!in_array($flag, $allowed, true)) {
                    throw new InvalidArgumentException('Unknown option ' . $argument . '.');
                }
                $flags[$flag] = true;
                continue;
            }
            $args[] = $argument;
        }
        $expected = self::$usage[$command] === '' ? 0 : substr_count(self::$usage[$command], '<');
        if ($expected === 0 && $args) {
            throw new InvalidArgumentException('Unexpected argument "' . $args[0] . '".');
        }
        return [$args, $flags];
    }

    /**
     * Resolves the <domain> argument (name or numeric id) of a command.
     *
     * @param string $command
     * @param string[] $args
     * @return pm_Domain
     */
    private function domain($command, array $args)
    {
        if (count($args) !== 1 || $args[0] === '') {
            throw new InvalidArgumentException('Expected one domain name or domain id.');
        }
        $name = strtolower(trim($args[0]));
        try {
            $domain = ctype_digit($name) ? pm_Domain::getByDomainId((int)$name) : pm_Domain::getByName($name);
        } catch (Exception $e) {
            throw new InvalidArgumentException('Domain "' . $args[0] . '" was not found.');
        }
        if (!$domain->hasHosting()) {
            throw new InvalidArgumentException('Domain "' . $domain->getName() . '" has no web hosting.');
        }
        return $domain;
    }

    /**
     * @param pm_Domain $domain
     * @return Modules_Runway_App
     * @throws Modules_Runway_Exception
     */
    private function requireConfigured(pm_Domain $domain)
    {
        $app = new Modules_Runway_App($domain);
        if (!$app->isConfigured()) {
            throw new Modules_Runway_Exception('The application of ' . $domain->getName() . ' is not configured. Configure it in Plesk (Websites & Domains > Runway) first.');
        }
        return $app;
    }

    /**
     * @return array domain id => apps-list entry of the helper
     */
    private function helperStates()
    {
        $states = [];
        $result = Modules_Runway_Helper::call('apps-list');
        foreach (isset($result['apps']) && is_array($result['apps']) ? $result['apps'] : [] as $app) {
            $states[(int)$app['domain_id']] = $app;
        }
        return $states;
    }

    /**
     * Polls a background job until it finishes, then prints the end of its log.
     *
     * @param string $job Job id (admin, deploy-<id>)
     * @param int $timeout Seconds
     * @return int EXIT_OK when the job succeeded
     */
    private function waitForJob($job, $timeout)
    {
        $deadline = time() + max(60, (int)$timeout);
        $last = null;
        $status = [];
        do {
            sleep(self::POLL_SECONDS);
            $status = Modules_Runway_Helper::call('job-status', ['job' => $job, 'lines' => 40]);
            $state = isset($status['state']) ? (string)$status['state'] : 'none';
            if ($state !== $last) {
                $this->line('Job ' . $job . ': ' . $state);
                $last = $state;
            }
        } while (in_array($state, ['queued', 'running'], true) && time() < $deadline);

        if (!empty($status['log'])) {
            $this->line('--- last lines of the log ---');
            $this->line(rtrim((string)$status['log']));
            $this->line('---');
        }
        if (in_array($state, ['queued', 'running'], true)) {
            $this->error('The job is still running; check it later with --status or in Plesk.');
            return self::EXIT_FAILED;
        }
        if ($state !== 'succeeded') {
            $this->error('The job ' . $state . (!empty($status['message']) ? ': ' . $status['message'] : '.'));
            return self::EXIT_FAILED;
        }
        return self::EXIT_OK;
    }

    /**
     * @param string $text
     */
    private function line($text)
    {
        call_user_func($this->stdout, $text . "\n");
    }

    /**
     * @param string $text
     */
    private function error($text)
    {
        call_user_func($this->stderr, $text . "\n");
    }

    /**
     * Prints "Label:  value" lines with aligned values.
     *
     * @param array $facts [[label, value], ...]
     */
    private function facts(array $facts)
    {
        $width = 0;
        foreach ($facts as $fact) {
            $width = max($width, strlen($fact[0]) + 1);
        }
        foreach ($facts as $fact) {
            $this->line(str_pad($fact[0] . ':', $width + 2) . $fact[1]);
        }
    }

    /**
     * Prints rows as columns separated by two spaces.
     *
     * @param string[]|null $header
     * @param array $rows
     */
    private function table($header, array $rows)
    {
        $all = $header ? array_merge([$header], $rows) : $rows;
        $widths = [];
        foreach ($all as $row) {
            foreach (array_values($row) as $index => $cell) {
                $widths[$index] = max(isset($widths[$index]) ? $widths[$index] : 0, strlen((string)$cell));
            }
        }
        foreach ($all as $row) {
            $cells = [];
            foreach (array_values($row) as $index => $cell) {
                $cells[] = str_pad((string)$cell, $widths[$index]);
            }
            $this->line(rtrim(implode('  ', $cells)));
        }
    }

    /**
     * @param int|float $bytes
     * @return string
     */
    private static function bytes($bytes)
    {
        $units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
        $value = (float)$bytes;
        $unit = 0;
        while ($value >= 1024 && $unit < count($units) - 1) {
            $value /= 1024;
            $unit++;
        }
        return ($unit === 0 ? (string)(int)$value : number_format($value, 1, '.', '')) . ' ' . $units[$unit];
    }
}
