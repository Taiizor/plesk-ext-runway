<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Pure authorization and web-server rendering fixtures; no Plesk or network access.

class Modules_Runway_Exception extends Exception {}
class Modules_Runway_App
{
    const MODE_PATH = 'path';
    const MODE_WEB = 'web';
    const MAX_STATIC_PATHS = 20;
    public $configured = true;
    public function isConfigured() { return $this->configured; }
    public function getDomain() { return $this; }
    public function getId() { return 17; }
    public static function isValidUrlPrefix($path) { return is_string($path) && preg_match('#^/[A-Za-z0-9._~/-]+$#D', $path); }
    public static function isReservedPath($path) { return false; }
}
class Modules_Runway_Access
{
    public static $admin = false;
    public static function isAdmin() { return self::$admin; }
    public static function requireAdmin() { if (!self::$admin) { throw new Modules_Runway_Exception('Denied'); } }
}
class Modules_Runway_Helper
{
    public static $calls = [];
    public static function call($command, array $payload = []) { self::$calls[] = [$command, $payload]; return ['options' => []]; }
}
class pm_Locale
{
    public static function lmsg($key) { return $key; }
}
require dirname(__DIR__, 2) . '/src/plib/library/Isolation.php';
require dirname(__DIR__, 2) . '/src/plib/library/WebConfig.php';
function check($condition, $message)
{
    if (!$condition) { throw new RuntimeException($message); }
}
$app = new Modules_Runway_App();
Modules_Runway_Isolation::call($app, ['domain_id' => 99, 'action' => 'save']);
check(Modules_Runway_Helper::$calls[0][1] === ['domain_id' => 17, 'action' => 'status'], 'GET cannot change policies or target another domain');
$calls = count(Modules_Runway_Helper::$calls);
try {
    Modules_Runway_Isolation::call($app, ['options' => ['enabled' => false]], true);
    throw new RuntimeException('A customer changed the administrator policy');
} catch (Modules_Runway_Exception $e) {
    check(count(Modules_Runway_Helper::$calls) === $calls, 'Denied writes must not reach the helper');
}
Modules_Runway_Access::$admin = true;
Modules_Runway_Isolation::call($app, ['domain_id' => 99, 'options' => ['enabled' => true]], true);
check(end(Modules_Runway_Helper::$calls)[1]['domain_id'] === 17, 'POST uses the authorized domain identity');
$app->configured = false;
try {
    Modules_Runway_Isolation::call($app);
    throw new RuntimeException('An unconfigured application exposed an isolation endpoint');
} catch (Modules_Runway_Exception $e) {}

foreach (['web', 'path'] as $mode) {
    $prefix = $mode === 'path' ? '/api/assets' : '/assets';
    $target = ['port' => 25001, 'mode' => $mode, 'mountPath' => '/api', 'staticPaths' => [$prefix],
               'documentRoot' => '/srv/fixture/wwwroot'];
    $nginx = Modules_Runway_WebConfig::nginx($target);
    $apache = Modules_Runway_WebConfig::apache($target);
    preg_match('/if \(\$uri ~ "(.+)"\) \{ return 403; \}/', $nginx, $matches);
    check(isset($matches[1]), 'A static execution guard was not rendered');
    foreach (['x.php', 'x.PHTML', 'x.py', 'x.rb', 'x.cgi', 'x.jsp', 'x.shtml', '.env', '.git/config', 'x.php/path-info'] as $file) {
        check(preg_match('#' . $matches[1] . '#', $prefix . '/' . $file) === 1, 'Interpreter or hidden file escaped the guard: ' . $file);
    }
    foreach (['image.png', 'module.wasm', 'app.dll', 'bundle.js', 'index.html'] as $file) {
        check(preg_match('#' . $matches[1] . '#', $prefix . '/' . $file) === 0, 'A legitimate static download was blocked');
    }
    check(strpos($nginx, 'try_files') === false, 'Do not bypass Plesk static location authentication');
    check(strpos($apache, 'SetHandler default-handler') !== false, 'Apache must override interpreter handlers');
    check(strpos($apache, 'AllowOverride AuthConfig Limit') !== false, 'Keep authentication overrides while forbidding interpreter overrides');
    check(strpos($apache, '-FollowSymLinks -SymLinksIfOwnerMatch') !== false, 'Apache must reject link traversal');
    $target['documentRoot'] = "/srv/fixture\nInjectedDirective";
    $denied = Modules_Runway_WebConfig::apache($target);
    check(strpos($denied, 'InjectedDirective') === false, 'Invalid filesystem paths must not enter server configuration');
}
echo "Isolation authorization and static-file contracts passed.\n";
