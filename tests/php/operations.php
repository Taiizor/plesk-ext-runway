<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Pure fixtures: no Plesk installation, helper process or service is contacted.

class pm_Settings
{
    public static $values = [];
    public static function get($key, $default = null) { return array_key_exists($key, self::$values) ? self::$values[$key] : $default; }
    public static function set($key, $value) { self::$values[$key] = $value; }
}
class pm_Locale
{
    public static function lmsg($key, $params = []) { return $key; }
}
class pm_Domain
{
    public $settings = [];
    public $limits = [];
    public $permissions = [];
    public static $all = [];
    public function getId() { return 17; }
    public function getName() { return 'api.test'; }
    public function getHomePath() { return '/srv/fixture'; }
    public function getDocumentRoot() { return '/srv/fixture/httpdocs'; }
    public function getSysUserLogin() { return 'fixture'; }
    public function getSetting($key, $default = '') { return isset($this->settings[$key]) ? $this->settings[$key] : $default; }
    public function setSetting($key, $value) { $this->settings[$key] = $value; }
    public function getLimit($key) { return array_key_exists($key, $this->limits) ? $this->limits[$key] : false; }
    public function hasPermission($key) { return !empty($this->permissions[$key]); }
    public function hasHosting() { return true; }
    public function isActive() { return true; }
    public static function getAllDomains() { return self::$all; }
}
abstract class pm_Hook_Limits { const PLACE_ADDITIONAL = 'additional'; }
abstract class pm_Hook_Permissions { const PLACE_MAIN = 'main'; const PLACE_ADDITIONAL = 'additional'; }
abstract class pm_Hook_Backup_Domain
{
    public function backup(pm_Domain $domain) { return []; }
    public function restore(pm_Domain $domain, $pleskVersion, $extVersion, $config, $contentDir) {}
}
class Modules_Runway_Runtime
{
    const TOOLCHAIN_NONE = 'none';
    public static function keys() { return ['go', 'rust', 'bun', 'java', 'dotnet', 'python', 'ruby', 'php', 'binary']; }
    public static function get($runtime) { return ['default_listen' => 'tcp']; }
    public static function toolchainKind($runtime) { return self::TOOLCHAIN_NONE; }
    public static function isValidVersion($runtime, $version) { return true; }
    public static function unixSupported($runtime, $version) { return true; }
}
class Modules_Runway_Exception extends Exception {}
class Modules_Runway_ValidationException extends Modules_Runway_Exception {}
class Modules_Runway_Access
{
    const PERMISSION = 'manage_runway_apps';
    public static function isAdmin() { return false; }
}
class Modules_Runway_WebConfig
{
    public static function reconfigure($domain) {}
}
class Modules_Runway_Log
{
    public static function info($message) {}
    public static function debug($message) {}
    public static function err($message) {}
}
class Modules_Runway_Helper
{
    public static $calls = [];
    public static $backup = false;
    public static $apps = [];
    public static function call($command, array $payload = [])
    {
        self::$calls[] = [$command, $payload];
        if ($command === 'apps-list') {
            return ['apps' => self::$apps];
        }
        if ($command === 'app-apply') {
            return ['port' => 25001, 'switchable' => false];
        }
        if ($command === 'operations' && $payload['action'] === 'export') {
            return ['bundle' => ['schema' => 1, 'operations' => ['backup' => true]]];
        }
        if ($command === 'operations' && $payload['action'] === 'validate-import') {
            if ($payload['backup']['schema'] !== 1) {
                throw new Modules_Runway_Exception('Invalid bundle');
            }
            return ['valid' => true];
        }
        return ['options' => ['backup' => self::$backup], 'restored' => true];
    }
}

$root = dirname(__DIR__, 2) . '/src/plib/';
foreach (['library/Settings.php', 'library/Policies.php', 'library/App.php', 'library/Operations.php', 'library/Reconcile.php',
             'hooks/Limits.php', 'hooks/Permissions.php', 'hooks/Backup/Domain.php'] as $file) {
    require $root . $file;
}
function check($condition, $message)
{
    if (!$condition) {
        throw new RuntimeException($message);
    }
}
$domain = new pm_Domain();
pm_Domain::$all = [$domain];
$domain->limits = ['app_memory_mb' => 256, 'app_cpu_percent' => 50, 'app_tasks' => 128, 'app_count' => 0];
$raw = ['memoryMb' => 1024, 'cpuPercent' => 0, 'tasks' => 512];
check(Modules_Runway_Settings::get('planPolicies') === false, 'Plan policies must default off');
check(Modules_Runway_Policies::clamp($domain, $raw) === $raw, 'Disabled policies must not clamp');
check(Modules_Runway_Policies::allows($domain, 'binary'), 'Disabled policies must not deny runtimes');
Modules_Runway_Settings::set('planPolicies', true);
check(Modules_Runway_Policies::clamp($domain, $raw) === ['memoryMb' => 256, 'cpuPercent' => 50, 'tasks' => 128], 'Positive plan caps must apply');
$app = new Modules_Runway_App($domain);
check(isset($app->update(['runtime' => 'binary'], false)['runtime']), 'New forbidden runtime must fail');
$domain->permissions['runtime_binary'] = true;
check(isset($app->update(['runtime' => 'binary', 'enabled' => true], false)['enabled']), 'Zero application allowance must deny enabling');
$domain->limits['app_count'] = false;
check(!$app->update(['runtime' => 'binary', 'enabled' => true, 'memoryMb' => 1024, 'cpuPercent' => 0, 'tasks' => 512], true), 'Administrator configuration should validate');
$app->save();
check($app->limits() === ['memoryMb' => 256, 'cpuPercent' => 50, 'tasks' => 128], 'Effective limits must be clamped');
check(json_decode($domain->getSetting(Modules_Runway_App::LIMITS_KEY), true) === $raw, 'Requested admin limits must be preserved');
check($app->payload()['limits'] === ['memory_mb' => 256, 'cpu_percent' => 50, 'tasks' => 128], 'Helper must receive effective limits');
$app = new Modules_Runway_App($domain);
$domain->permissions['runtime_binary'] = false;
check(!$app->update(['buildCmd' => 'echo build'], false), 'Permission changes must preserve existing enabled apps');
check(isset($app->update(['runtime' => 'go'], false)['runtime']), 'Switching to a forbidden runtime must fail');
check(!$app->update(['enabled' => false], false), 'Disabling must always remain possible');
check(isset($app->update(['enabled' => true], false)['runtime']), 'Re-enabling must check runtime permission');

Modules_Runway_Settings::set('planPolicies', false);
$app = new Modules_Runway_App($domain);
$app->apply(false, false);
Modules_Runway_Settings::set('planPolicies', true);
Modules_Runway_Helper::$apps = [['domain_id' => 17, 'domain' => 'api.test', 'sysuser' => 'fixture',
    'enabled' => true, 'suspended' => false, 'active_state' => 'active', 'switchable' => false, 'port' => 25001,
    'limits' => ['memory_mb' => 1024, 'cpu_percent' => 0, 'tasks' => 512]]];
Modules_Runway_Helper::$calls = [];
$reconciled = Modules_Runway_Reconcile::run();
check(!$reconciled['errors'] && $reconciled['reapplied'] === [17], 'Reconcile must apply changed plan caps');
$applies = array_values(array_filter(Modules_Runway_Helper::$calls, function ($item) { return $item[0] === 'app-apply'; }));
check($applies[0][1]['restart'] && $applies[0][1]['limits']['memory_mb'] === 256, 'Changed policy caps must restart with effective limits');
Modules_Runway_Helper::$apps[0]['limits'] = $applies[0][1]['limits'];
Modules_Runway_Settings::set('planPolicies', false);
Modules_Runway_Helper::$calls = [];
$reconciled = Modules_Runway_Reconcile::run();
check(!$reconciled['errors'] && $reconciled['reapplied'] === [17], 'Disabling policy must restore earlier requested limits');
$applies = array_values(array_filter(Modules_Runway_Helper::$calls, function ($item) { return $item[0] === 'app-apply'; }));
check($applies[0][1]['limits']['memory_mb'] === 1024, 'Original admin limit must survive the round trip');
Modules_Runway_Helper::$apps = [];

$limits = (new Modules_Runway_Limits())->getLimits();
check(count($limits) === 4 && $limits['app_count']['default'] === false, 'Plesk limits must default unlimited');
$permissions = (new Modules_Runway_Permissions())->getPermissions();
check(count($permissions) === 10 && $permissions['runtime_dotnet']['default'] === true, 'Runtime permissions should preserve existing plan access');

Modules_Runway_Settings::set('planPolicies', false);
$app = new Modules_Runway_App($domain);
$bundle = ['schema' => 1, 'operations' => ['backup' => true, 'restore_start' => false], 'application' => $app->config()];
$bundle['application'] += ['env' => 'INJECTED=bad', 'documentRoot' => 'apps/api'];
$bundle['application']['port'] = 19999;
$bundle['application']['switchable'] = true;
Modules_Runway_Helper::$calls = [];
$result = Modules_Runway_Operations::restore($app, $bundle, false, true);
check($result['requiresStart'] === true && !$app->isEnabled(), 'Native recovery must default disabled/manual start');
$applies = array_values(array_filter(Modules_Runway_Helper::$calls, function ($item) { return $item[0] === 'app-apply'; }));
check(count($applies) === 2, 'Native restore must reconstruct and apply destination state');
$payload = $applies[0][1];
check($payload['domain_id'] === 17 && $payload['sysuser'] === 'fixture' && $payload['port'] === 0, 'Recovery must rebuild destination identity and ports');
check(!isset($payload['env']) && !$payload['start'], 'Recovery must not import environment through application settings or auto-start');
check($payload['document_root'] === 'httpdocs', 'Recovery must preserve the destination document root');
Modules_Runway_Helper::$calls = [];
$bundle['schema'] = 9;
try {
    Modules_Runway_Operations::restore(new Modules_Runway_App($domain), $bundle, false, true);
    throw new RuntimeException('Invalid recovery bundle accepted');
} catch (Modules_Runway_Exception $expected) {
    check(count(Modules_Runway_Helper::$calls) === 1, 'Invalid bundle must fail before applying settings');
}

$hook = new Modules_Runway_Backup_Domain();
Modules_Runway_Helper::$calls = [];
$domain->setSetting('runwayRecoveryBackup', '0');
check($hook->backup($domain) === ['', [], [], []], 'Native backup must be opt-in');
check(!Modules_Runway_Helper::$calls, 'Disabled native backup must not depend on the helper');
Modules_Runway_Helper::$backup = true;
$domain->setSetting('runwayRecoveryBackup', '1');
$backup = $hook->backup($domain);
check(json_decode($backup[0], true)['application']['runtime'] === 'binary', 'Native backup must include application configuration');
check(array_slice($backup, 1) === [[], [], []], 'Native backup must not duplicate or claim shared content');
echo "PHP operation, recovery and plan-policy contracts passed.\n";
