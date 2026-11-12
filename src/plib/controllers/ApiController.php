<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * JSON API of the extension (docs/DESIGN.md section 6), used by the React frontend.
 *
 * URLs: <baseUrl>index.php/api/<action>. The domain actions live under api/app/<sub> and the
 * updater under api/update/<sub>: Zend's module route maps "api/app/save" to appAction() (the
 * extra segment becomes a request parameter), which dispatches on the path segment after "app".
 *
 * Responses: {"status": "success", "data": ...} or {"status": "error", "errors": ["..."]};
 * validation errors are keyed by field: {"status": "error", "errors": {"field": ["..."]}}.
 * Mutations require POST with a JSON body; Plesk checks the X-Forgery-Protection-Token
 * header (CSRF) of every POST. Domain actions resolve the domain from site_id (query
 * string or body) and check access; admin-only actions check Access::requireAdmin().
 */
class ApiController extends pm_Controller_Action
{
    /** @var array|null Decoded request body */
    private $body = null;

    public function init()
    {
        parent::init();
        $this->_helper->viewRenderer->setNoRender(true);
    }

    // -----------------------------------------------------------------------
    // Everybody
    // -----------------------------------------------------------------------

    /**
     * GET api/context: who is using the UI and what the server supports.
     */
    public function contextAction()
    {
        $this->respond(function () {
            return [
                'isAdmin' => Modules_Runway_Access::isAdmin(),
                'locale' => (string)pm_Locale::getCode(),
                'runtimes' => Modules_Runway_Runtime::all(),
                'urls' => self::urls(),
                'limits' => ['maxStaticPaths' => Modules_Runway_App::MAX_STATIC_PATHS],
            ];
        });
    }

    /**
     * GET api/overview: server facts and every domain (with hosting) the user may manage.
     */
    public function overviewAction()
    {
        $this->respond(function () {
            $isAdmin = Modules_Runway_Access::isAdmin();
            $errors = [];
            $states = [];
            try {
                $result = Modules_Runway_Helper::call('apps-list');
                foreach ($result['apps'] as $app) {
                    $states[(int)$app['domain_id']] = $app;
                }
            } catch (Exception $e) {
                $errors[] = $e->getMessage();
            }
            // Server facts are for administrators only (customers do not need OS or helper details).
            $server = null;
            if ($isAdmin) {
                try {
                    $info = Modules_Runway_Helper::call('info');
                    $server = [
                        'os' => isset($info['os']) ? $info['os'] : '',
                        'arch' => isset($info['arch']) ? $info['arch'] : '',
                        'systemd' => isset($info['systemd']) ? (int)$info['systemd'] : 0,
                        'python' => isset($info['python']) ? $info['python'] : '',
                        'build_deps' => isset($info['build_deps']) ? (object)$info['build_deps'] : (object)[],
                        'helperVersion' => isset($info['helper_version']) ? $info['helper_version'] : '',
                        // enforcing|permissive|null: nginx/Apache may need SELinux policy changes (README).
                        'selinux' => isset($info['selinux']) && is_string($info['selinux']) ? $info['selinux'] : null,
                    ];
                } catch (Exception $e) {
                    $errors[] = $e->getMessage();
                }
            }

            $apps = [];
            foreach (pm_Domain::getAllDomains() as $domain) {
                try {
                    if (!$domain->hasHosting() || (!$isAdmin && !Modules_Runway_Access::canManage($domain))) {
                        continue;
                    }
                } catch (Exception $e) {
                    continue;
                }
                $id = (int)$domain->getId();
                $config = Modules_Runway_App::storedConfig($domain);
                $state = isset($states[$id]) ? $states[$id] : null;
                $apps[] = [
                    'domainId' => $id,
                    'domain' => (string)$domain->getName(),
                    'displayName' => (string)$domain->getDisplayName(),
                    'configured' => $config !== null,
                    'runtime' => $config && isset($config['runtime']) ? (string)$config['runtime'] : null,
                    'toolchain' => $config && isset($config['toolchain']) ? (string)$config['toolchain'] : null,
                    'listen' => $config && isset($config['listen']) ? (string)$config['listen'] : null,
                    'mode' => $config ? (isset($config['mode']) ? (string)$config['mode'] : Modules_Runway_App::MODE_WEB) : null,
                    // Only TCP applications have a port worth showing.
                    'port' => $config && !empty($config['port'])
                        && (!isset($config['listen']) || $config['listen'] === Modules_Runway_App::LISTEN_TCP)
                        ? (int)$config['port'] : null,
                    'enabled' => $config && !empty($config['enabled']),
                    'state' => self::appState($config, $state),
                    'memoryBytes' => $state && isset($state['memory_bytes']) ? $state['memory_bytes'] : null,
                    'url' => Modules_Runway_App::siteUrl($domain),
                    'appUrl' => Modules_Runway_App::appUrl($domain, $config),
                ];
            }
            usort($apps, function ($a, $b) {
                if ($a['configured'] !== $b['configured']) {
                    return $a['configured'] ? -1 : 1;
                }
                return strcmp($a['displayName'], $b['displayName']);
            });
            return ['server' => $server, 'apps' => $apps, 'errors' => $errors];
        });
    }

    // -----------------------------------------------------------------------
    // Administrator
    // -----------------------------------------------------------------------

    /**
     * GET api/toolchains[?runtime=<key>][&available=0][&force=1]: installed and installable
     * toolchains per runtime, build dependencies and the admin job.
     */
    public function toolchainsAction()
    {
        $this->respond(function () {
            Modules_Runway_Access::requireAdmin();
            $request = $this->getRequest();
            $only = (string)$request->getQuery('runtime', '');
            $withAvailable = (string)$request->getQuery('available', '1') !== '0';
            $force = (string)$request->getQuery('force', '0') === '1';

            $installed = Modules_Runway_Helper::call('toolchains');
            $runtimes = [];
            foreach (Modules_Runway_Runtime::all() as $meta) {
                $key = (string)$meta['key'];
                if ($only !== '' && $only !== $key) {
                    continue;
                }
                $entry = isset($installed['runtimes'][$key]) ? $installed['runtimes'][$key] : [];
                $kind = isset($meta['toolchain']) ? (string)$meta['toolchain'] : Modules_Runway_Runtime::TOOLCHAIN_NONE;
                $available = [];
                $availableError = null;
                if ($withAvailable && $kind !== Modules_Runway_Runtime::TOOLCHAIN_NONE) {
                    try {
                        $releases = Modules_Runway_Helper::call('releases', ['runtime' => $key, 'force' => $force]);
                        $available = isset($releases['available']) ? $releases['available'] : [];
                        $availableError = isset($releases['error']) ? $releases['error'] : null;
                    } catch (Exception $e) {
                        $availableError = $e->getMessage();
                    }
                }
                $runtimes[$key] = [
                    'installed' => isset($entry['installed']) ? $entry['installed'] : [],
                    'available' => $available,
                    'availableError' => $availableError,
                    'inUse' => (object)(isset($entry['in_use']) ? $entry['in_use'] : []),
                    'toolchainKind' => $kind,
                ];
            }
            return [
                'runtimes' => (object)$runtimes,
                'buildDeps' => (object)(isset($installed['build_deps']) ? $installed['build_deps'] : []),
                'job' => isset($installed['job']) ? $installed['job'] : null,
            ];
        });
    }

    /**
     * POST api/toolchain {runtime, op: install|update|remove, version}
     */
    public function toolchainAction()
    {
        $this->respond(function () {
            Modules_Runway_Access::requireAdmin();
            $this->requirePost();
            $body = $this->body();
            $runtime = isset($body['runtime']) && is_string($body['runtime']) ? $body['runtime'] : '';
            $op = isset($body['op']) && is_string($body['op']) ? $body['op'] : '';
            $version = isset($body['version']) && is_scalar($body['version']) ? trim((string)$body['version']) : '';
            if (!in_array($runtime, Modules_Runway_Runtime::keys(), true)) {
                throw new Modules_Runway_ValidationException(['runtime' => [pm_Locale::lmsg('errorRuntime')]]);
            }
            if ($version === '') {
                throw new Modules_Runway_ValidationException(['version' => [pm_Locale::lmsg('errorToolchain')]]);
            }
            $payload = ['runtime' => $runtime, 'version' => $version];
            switch ($op) {
                case 'install':
                case 'update':
                    $result = Modules_Runway_Helper::call('toolchain-' . $op, $payload);
                    return ['job' => $result['job'], 'message' => pm_Locale::lmsg('messageJobStarted')];
                case 'remove':
                    $result = Modules_Runway_Helper::call('toolchain-remove', $payload);
                    return [
                        'removed' => $result['removed'],
                        'message' => pm_Locale::lmsg('messageToolchainRemoved', ['version' => $version]),
                    ];
                default:
                    throw new Modules_Runway_ValidationException(['op' => [pm_Locale::lmsg('errorInvalidOperation')]]);
            }
        });
    }

    /**
     * POST api/build-deps: installs compilers and headers with the system package manager.
     */
    public function buildDepsAction()
    {
        $this->respond(function () {
            Modules_Runway_Access::requireAdmin();
            $this->requirePost();
            $result = Modules_Runway_Helper::call('build-deps-install');
            return ['job' => $result['job'], 'message' => pm_Locale::lmsg('messageJobStarted')];
        });
    }

    /**
     * GET api/job?job=admin|deploy-<id>[&lines=N]: state and log tail of a background job.
     */
    public function jobAction()
    {
        $this->respond(function () {
            Modules_Runway_Access::requireAdmin();
            $request = $this->getRequest();
            $job = (string)$request->getQuery('job', 'admin');
            $lines = max(10, min(5000, (int)$request->getQuery('lines', 400)));
            return Modules_Runway_Helper::call('job-status', ['job' => $job, 'lines' => $lines]);
        });
    }

    /**
     * GET api/settings: server-wide settings. POST api/settings {key: value, ...}: saves them.
     */
    public function settingsAction()
    {
        $this->respond(function () {
            Modules_Runway_Access::requireAdmin();
            if ($this->getRequest()->isPost()) {
                $errors = Modules_Runway_Settings::update($this->body());
                if ($errors) {
                    throw new Modules_Runway_ValidationException($errors);
                }
            }
            return Modules_Runway_Settings::all();
        });
    }

    /**
     * Built-in updater: GET api/update (installed version, last check, admin job and the
     * settings updateCheck/updateAuto; no network), POST api/update/check (asks GitHub now),
     * POST api/update/install {version: "X.Y.Z-R"} (starts the self-update job).
     */
    public function updateAction()
    {
        $this->respond(function () {
            Modules_Runway_Access::requireAdmin();
            switch ($this->subAction('update')) {
                case '':
                    return Modules_Runway_Updater::status();
                case 'check':
                    $this->requirePost();
                    return Modules_Runway_Updater::check(true);
                case 'install':
                    $this->requirePost();
                    $body = $this->body();
                    $version = isset($body['version']) && is_string($body['version']) ? trim($body['version']) : '';
                    if (!preg_match(Modules_Runway_Updater::VERSION_PATTERN, $version)) {
                        throw new Modules_Runway_ValidationException(['version' => [pm_Locale::lmsg('errorUpdateVersion')]]);
                    }
                    $result = Modules_Runway_Updater::install($version);
                    return [
                        'job' => isset($result['job']) ? $result['job'] : 'admin',
                        'version' => $version,
                        'message' => pm_Locale::lmsg('messageUpdateStarted', ['version' => $version]),
                    ];
                default:
                    throw new Modules_Runway_Exception(pm_Locale::lmsg('errorInvalidOperation'));
            }
        });
    }

    // -----------------------------------------------------------------------
    // Domain (administrator, or customer with the permission and access to the domain)
    // -----------------------------------------------------------------------

    /**
     * api/app, api/app/save, api/app/control, api/app/status, api/app/logs, api/app/remove,
     * api/app/sample, api/app/fetch.
     */
    public function appAction()
    {
        $this->respond(function () {
            $sub = $this->subAction('app');
            switch ($sub) {
                case '':
                    return $this->appGet();
                case 'save':
                    return $this->appSave();
                case 'control':
                    return $this->appControl();
                case 'status':
                    return $this->appModel()->status();
                case 'logs':
                    return $this->appLogs();
                case 'remove':
                    return $this->appRemove();
                case 'sample':
                    return $this->appSample();
                case 'fetch':
                    return $this->appFetch();
                default:
                    throw new Modules_Runway_Exception(pm_Locale::lmsg('errorInvalidOperation'));
            }
        });
    }

    /**
     * GET api/app: everything the domain page needs.
     *
     * @param Modules_Runway_App|null $app Model to describe (default: the requested domain)
     * @return array
     */
    private function appGet(?Modules_Runway_App $app = null)
    {
        if ($app === null) {
            $app = $this->appModel();
        }
        $domain = $app->getDomain();
        $isAdmin = Modules_Runway_Access::isAdmin();
        $page = null;
        $pageError = null;
        try {
            $page = $app->loadPage();
        } catch (Exception $e) {
            $pageError = $e->getMessage();
        }
        $home = null;
        try {
            $home = method_exists($domain, 'getHomePath') ? (string)$domain->getHomePath() : null;
        } catch (Exception $e) {
            $home = null;
        }
        if (isset($page['inspect']['home'])) {
            $home = (string)$page['inspect']['home'];
        }
        return [
            'domain' => [
                'id' => (int)$domain->getId(),
                'name' => (string)$domain->getName(),
                'displayName' => (string)$domain->getDisplayName(),
                'home' => $home,
                'sysuser' => (string)$domain->getSysUserLogin(),
                'active' => Modules_Runway_App::domainIsActive($domain),
            ],
            'configured' => $app->isConfigured(),
            'config' => $app->config(),
            // null when the stored variables could not be loaded: omit "env" when saving then.
            'env' => $page !== null ? Modules_Runway_App::formatEnv($app->getEnv()) : null,
            'limits' => $app->limits(),
            'status' => isset($page['status']) ? $page['status'] : null,
            'inspect' => isset($page['inspect']) ? $page['inspect'] : null,
            'toolchains' => (object)self::pageToolchains($page, $isAdmin),
            'defaults' => (object)self::pageDefaults($page),
            'buildDeps' => isset($page['build_deps']) ? (object)$page['build_deps'] : null,
            'appUrl' => Modules_Runway_App::appUrl($domain, $app->isConfigured() ? $app->config() : null),
            'isAdmin' => $isAdmin,
            'pageError' => $pageError,
        ];
    }

    /**
     * Installed toolchains per runtime from the helper's app-page (an empty list for every
     * runtime it did not report). Usage lists name other customers' domains: only
     * administrators get them.
     *
     * @param array|null $page
     * @param bool $isAdmin
     * @return array runtime => list
     */
    private static function pageToolchains($page, $isAdmin)
    {
        $toolchains = isset($page['toolchains']) && is_array($page['toolchains']) ? $page['toolchains'] : [];
        $result = [];
        foreach (Modules_Runway_Runtime::keys() as $key) {
            $list = isset($toolchains[$key]) && is_array($toolchains[$key]) ? $toolchains[$key] : [];
            if (!$isAdmin) {
                unset($list['in_use'], $list['inUse'], $list['used_by']);
                foreach ($list as $index => $entry) {
                    if (is_array($entry)) {
                        unset($list[$index]['in_use'], $list[$index]['inUse'], $list[$index]['used_by']);
                    }
                }
            }
            $result[$key] = $list;
        }
        return $result;
    }

    /**
     * Default build/start commands per runtime: the helper's project-aware defaults, with the
     * static fallback for runtimes it did not report.
     *
     * @param array|null $page
     * @return array runtime => {build_cmd, start_cmd}
     */
    private static function pageDefaults($page)
    {
        $defaults = isset($page['defaults']) && is_array($page['defaults']) ? $page['defaults'] : [];
        $result = [];
        foreach (Modules_Runway_Runtime::keys() as $key) {
            if (isset($defaults[$key]) && is_array($defaults[$key])) {
                $result[$key] = $defaults[$key];
                continue;
            }
            $commands = Modules_Runway_App::defaultCommands($key);
            $result[$key] = ['build_cmd' => $commands['build'], 'start_cmd' => $commands['start']];
        }
        return $result;
    }

    /**
     * POST api/app/sample {runtime, listen, force?}: writes the runtime's sample application into the
     * application root (as the subscription's system user), points the configuration at it
     * (runtime, listen mode, installed toolchain, default commands), applies it like
     * api/app/save and answers like api/app plus {written, build, buildError, message}.
     *
     * @return array
     */
    private function appSample()
    {
        $this->requirePost();
        $app = $this->appModel();
        $body = $this->body();
        $runtime = isset($body['runtime']) && is_string($body['runtime']) && $body['runtime'] !== ''
            ? $body['runtime'] : (string)$app->get('runtime');
        if (!in_array($runtime, Modules_Runway_Runtime::keys(), true)) {
            throw new Modules_Runway_ValidationException(['runtime' => [pm_Locale::lmsg('errorRuntime')]]);
        }
        $listen = isset($body['listen']) && is_string($body['listen']) && $body['listen'] !== ''
            ? $body['listen'] : Modules_Runway_App::defaultListen($runtime);
        if (!in_array($listen, [Modules_Runway_App::LISTEN_TCP, Modules_Runway_App::LISTEN_UNIX, Modules_Runway_App::LISTEN_NONE], true)) {
            throw new Modules_Runway_ValidationException(['listen' => [pm_Locale::lmsg('errorListen')]]);
        }

        $force = false;
        if (isset($body['force'])) {
            $force = in_array($body['force'], [true, 1, '1', 'true', 'on', 'yes'], true);
        }
        // Keep the configured toolchain when the runtime stays the same; else the helper picks one.
        $current = (string)$app->get('toolchain');
        $wanted = $app->get('runtime') === $runtime && $current !== '' && Modules_Runway_Runtime::isValidVersion($runtime, $current)
            ? $current : '';
        if ($listen === Modules_Runway_App::LISTEN_UNIX && $wanted !== '' && !Modules_Runway_Runtime::unixSupported($runtime, $wanted)) {
            // e.g. PHP: the configured Plesk PHP cannot serve a socket, let the helper pick FrankenPHP.
            $wanted = '';
        }

        try {
            $sample = $app->writeSample($runtime, $listen, $wanted, $force);
        } catch (Modules_Runway_Exception $e) {
            // Expected refusals of the helper become field errors: the drawer then asks to
            // overwrite (force) or to choose TCP.
            if ($e->getHelperCode() === 'not_empty') {
                throw new Modules_Runway_ValidationException(['force' => [pm_Locale::lmsg('errorSampleNotEmpty', ['details' => $e->getMessage()])]]);
            }
            if ($e->getHelperCode() === 'unix_unsupported') {
                throw new Modules_Runway_ValidationException(['listen' => [pm_Locale::lmsg('errorSampleUnix')]]);
            }
            throw $e;
        }

        // The helper answers with the toolchain and the commands of the sample; older helpers
        // did not, then the project-aware defaults of app-page (or the static ones) are used.
        $defaults = $sample['defaults'];
        $toolchain = $sample['toolchain'];
        if ($defaults === null || $toolchain === null) {
            $page = null;
            try {
                $page = $app->loadPage();
            } catch (Exception $e) {
                Modules_Runway_Log::debug('app-page after app-sample failed: ' . $e->getMessage());
            }
            if ($defaults === null) {
                $all = self::pageDefaults($page);
                $defaults = $all[$runtime];
            }
            if ($toolchain === null) {
                $toolchain = self::pickToolchain($app, $runtime, isset($page['toolchains'][$runtime]) ? $page['toolchains'][$runtime] : []);
            }
        }
        $mode = $listen === Modules_Runway_App::LISTEN_NONE
            ? Modules_Runway_App::MODE_WORKER
            : ($app->get('mode') === Modules_Runway_App::MODE_PATH ? Modules_Runway_App::MODE_PATH : Modules_Runway_App::MODE_WEB);
        $values = [
            'runtime' => $runtime,
            'listen' => $listen,
            'mode' => $mode,
            'toolchain' => $toolchain,
            'buildCmd' => isset($defaults['build_cmd']) ? (string)$defaults['build_cmd'] : '',
            'startCmd' => isset($defaults['start_cmd']) ? (string)$defaults['start_cmd'] : '',
        ];
        $errors = $app->update($values, Modules_Runway_Access::isAdmin());
        if ($errors) {
            throw new Modules_Runway_ValidationException($errors);
        }
        $result = $app->applyAndDeploy();

        $data = $this->appGet($app);
        $data['written'] = $sample['written'];
        $data['build'] = $result['build'];
        $data['buildError'] = $result['buildError'];
        $message = count($sample['written']) === 1
            ? pm_Locale::lmsg('messageSampleWrittenOne')
            : pm_Locale::lmsg('messageSampleWritten', ['count' => count($sample['written'])]);
        if ($result['buildError'] !== null) {
            $message .= ' ' . pm_Locale::lmsg('messageSavedBuildNotStarted', ['details' => $result['buildError']]);
        } elseif ($result['build']) {
            $message .= ' ' . pm_Locale::lmsg('messageDeployStarted');
        }
        $data['message'] = $message;
        return $data;
    }

    /**
     * Toolchain for a runtime: the configured one when it is installed, else the newest
     * installed one ('' when none is installed or the runtime needs none).
     *
     * @param Modules_Runway_App $app
     * @param string $runtime
     * @param mixed $installed Installed toolchains of the runtime (helper entries with "id")
     * @return string
     */
    private static function pickToolchain(Modules_Runway_App $app, $runtime, $installed)
    {
        if (Modules_Runway_Runtime::toolchainKind($runtime) === Modules_Runway_Runtime::TOOLCHAIN_NONE) {
            return '';
        }
        $ids = [];
        foreach (is_array($installed) ? $installed : [] as $entry) {
            if (is_array($entry) && isset($entry['id']) && is_scalar($entry['id'])
                && Modules_Runway_Runtime::isValidVersion($runtime, (string)$entry['id'])) {
                $ids[] = (string)$entry['id'];
            }
        }
        $current = (string)$app->get('toolchain');
        if ($app->get('runtime') === $runtime && $current !== '' && ($ids === [] || in_array($current, $ids, true))) {
            return $current;
        }
        if ($ids === []) {
            return '';
        }
        usort($ids, function ($a, $b) {
            return version_compare($b, $a);
        });
        return $ids[0];
    }

    /**
     * POST api/app/fetch {url, sha256?, extract?, filename?, build?}: starts a deploy job that downloads a
     * prebuilt binary or archive into the application root (helper app-deploy with fetch).
     *
     * @return array {job, message}
     */
    private function appFetch()
    {
        $this->requirePost();
        $app = $this->appModel();
        if (!$app->isConfigured()) {
            throw new Modules_Runway_Exception(pm_Locale::lmsg('errorNotConfigured'));
        }
        $errors = [];
        $fetch = Modules_Runway_App::validateFetch($this->body(), $errors);
        if ($fetch === null) {
            throw new Modules_Runway_ValidationException($errors);
        }
        return ['job' => $app->fetch($fetch), 'message' => pm_Locale::lmsg('messageFetchStarted')];
    }

    /**
     * @return array
     */
    private function appSave()
    {
        $this->requirePost();
        $app = $this->appModel();
        $errors = $app->update($this->body(), Modules_Runway_Access::isAdmin());
        if ($errors) {
            throw new Modules_Runway_ValidationException($errors);
        }
        try {
            $result = $app->applyAndDeploy();
        } catch (Modules_Runway_Exception $e) {
            Modules_Runway_Log::warn('Applying the configuration of ' . $app->getDomain()->getName() . ' failed: ' . $e->getMessage());
            throw $e;
        }
        if ($result['buildError'] !== null) {
            $message = pm_Locale::lmsg('messageSavedBuildNotStarted', ['details' => $result['buildError']]);
        } elseif ($result['build']) {
            $message = pm_Locale::lmsg('messageSavedBuilding');
        } else {
            $message = pm_Locale::lmsg($app->isEnabled() ? 'messageSavedEnabled' : 'messageSavedDisabled');
        }
        return [
            'config' => $app->config(),
            'limits' => $app->limits(),
            'build' => $result['build'],
            'buildError' => $result['buildError'],
            'message' => $message,
        ];
    }

    /**
     * POST api/app/control {op: start|stop|restart|deploy}
     *
     * @return array
     */
    private function appControl()
    {
        $this->requirePost();
        $app = $this->appModel();
        if (!$app->isConfigured()) {
            throw new Modules_Runway_Exception(pm_Locale::lmsg('errorNotConfigured'));
        }
        $body = $this->body();
        $op = isset($body['op']) && is_string($body['op']) ? $body['op'] : '';
        $domainId = (int)$app->getDomain()->getId();
        switch ($op) {
            case 'start':
            case 'stop':
            case 'restart':
                Modules_Runway_Helper::call('app-action', ['domain_id' => $domainId, 'action' => $op]);
                return ['message' => pm_Locale::lmsg('messageAction_' . $op)];
            case 'deploy':
                // "Build & restart" is an explicit start: a stopped application runs again afterwards.
                $result = Modules_Runway_Helper::call('app-deploy', ['domain_id' => $domainId, 'build' => true, 'start' => true]);
                return ['message' => pm_Locale::lmsg('messageDeployStarted'), 'job' => $result['job']];
            default:
                throw new Modules_Runway_ValidationException(['op' => [pm_Locale::lmsg('errorInvalidOperation')]]);
        }
    }

    /**
     * GET api/app/logs?kind=app|deploy&lines=N
     *
     * @return array
     */
    private function appLogs()
    {
        $app = $this->appModel();
        $request = $this->getRequest();
        $kind = (string)$request->getQuery('kind', 'app') === 'deploy' ? 'deploy' : 'app';
        $lines = max(10, min(2000, (int)$request->getQuery('lines', 200)));
        if (!$app->isConfigured()) {
            return ['log' => '', 'kind' => $kind];
        }
        $result = Modules_Runway_Helper::call('app-logs', [
            'domain_id' => (int)$app->getDomain()->getId(),
            'kind' => $kind,
            'lines' => $lines,
        ]);
        return ['log' => isset($result['log']) ? (string)$result['log'] : '', 'kind' => $kind];
    }

    /**
     * POST api/app/remove: stops the service and deletes the configuration (files are kept).
     *
     * @return array
     */
    private function appRemove()
    {
        $this->requirePost();
        $app = $this->appModel();
        if ($app->isConfigured()) {
            $app->remove();
        }
        return ['message' => pm_Locale::lmsg('messageRemoved')];
    }

    // -----------------------------------------------------------------------
    // Plumbing
    // -----------------------------------------------------------------------

    /**
     * @return Modules_Runway_App The app of the requested domain (access checked)
     */
    private function appModel()
    {
        $domain = Modules_Runway_Access::domainFromRequest($this->getRequest(), $this->body());
        return new Modules_Runway_App($domain);
    }

    /**
     * The path segment after "api/<action>" ('' for api/<action> itself), e.g. "save" of
     * api/app/save or "check" of api/update/check.
     *
     * @param string $action
     * @return string
     */
    private function subAction($action)
    {
        $parts = array_values(array_filter(explode('/', (string)$this->getRequest()->getPathInfo()), 'strlen'));
        $index = array_search('api', $parts, true);
        if ($index === false || !isset($parts[$index + 1]) || $parts[$index + 1] !== $action) {
            return '';
        }
        return isset($parts[$index + 2]) ? strtolower($parts[$index + 2]) : '';
    }

    /**
     * Decoded JSON body (form-encoded POST data is accepted as well).
     *
     * @return array
     */
    private function body()
    {
        if ($this->body === null) {
            $request = $this->getRequest();
            $data = null;
            if ($request->isPost()) {
                $raw = (string)$request->getRawBody();
                $data = $raw !== '' ? json_decode($raw, true) : null;
                if (!is_array($data)) {
                    $data = $request->getPost();
                }
            }
            $this->body = is_array($data) ? $data : [];
        }
        return $this->body;
    }

    /**
     * @throws Modules_Runway_Exception
     */
    private function requirePost()
    {
        if (!$this->getRequest()->isPost()) {
            throw new Modules_Runway_Exception(pm_Locale::lmsg('errorPostRequired'));
        }
    }

    /**
     * Runs the callback and sends its result, or the error, as JSON.
     *
     * @param callable $callback
     */
    private function respond(callable $callback)
    {
        try {
            $data = $callback();
            $response = ['status' => 'success', 'data' => $data];
        } catch (Modules_Runway_ValidationException $e) {
            $response = ['status' => 'error', 'errors' => $e->getErrors()];
        } catch (pm_Exception $e) {
            // Modules_Runway_Exception and pm_Exception messages are safe to show.
            $response = ['status' => 'error', 'errors' => [$e->getMessage()]];
        } catch (Exception $e) {
            Modules_Runway_Log::err('API ' . $this->getRequest()->getPathInfo() . ' failed: ' . get_class($e) . ': ' . $e->getMessage());
            $response = ['status' => 'error', 'errors' => [pm_Locale::lmsg('errorInternal')]];
        }
        $this->_helper->json($response);
    }

    /**
     * Mapping of a stored configuration + helper state to one UI state.
     *
     * @param array|null $config Stored configuration
     * @param array|null $state Entry of the helper's apps-list
     * @return string notConfigured|disabled|suspended|running|starting|stopping|failed|stopped
     */
    private static function appState($config, $state)
    {
        return Modules_Runway_App::uiState($config, $state);
    }

    /**
     * @return array URLs the frontend needs (absolute paths)
     */
    private static function urls()
    {
        $base = pm_Context::getBaseUrl();
        return [
            'base' => $base,
            'api' => $base . 'index.php/api',
            'overview' => $base . 'index.php/overview',
            'toolchains' => $base . 'index.php/toolchains',
            'settings' => $base . 'index.php/settings',
            'domain' => $base . 'index.php/domain',
            'logo' => $base . 'images/logo.png',
        ];
    }
}
