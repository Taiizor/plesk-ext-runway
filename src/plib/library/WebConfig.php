<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Renders the reverse proxy snippets injected into the domain's web server
 * configuration and triggers regeneration of that configuration.
 */
class Modules_Runway_WebConfig
{
    /** Plesk paths excluded from the proxy in "web" mode (nginx regex alternatives). */
    const NGINX_RESERVED = '(plesk-stat|webstat|webstat-ssl|ftpstat|anon_ftpstat|awstats-icon)(/|$)|\.well-known/acme-challenge/';

    /**
     * nginx snippet placed inside the domain's server {} blocks.
     *
     * A regex location is used on purpose (the same technique as Plesk's
     * Docker proxy rules): in proxy mode Plesk already defines "location /",
     * and a second prefix location with the same path is a fatal "duplicate
     * location" error. Extension snippets are placed before Plesk's own
     * locations, so this regex wins over Plesk's regex locations (static
     * files, PHP), while "^~" prefix locations such as Let's Encrypt's
     * /.well-known/acme-challenge/ keep working. Plesk's web statistics paths
     * and ACME challenges are excluded explicitly, so they stay reachable even
     * when no SSL extension defines its own location.
     *
     * Modes (docs/DESIGN.md section 5.3):
     *  - web:  every path except the Plesk paths and the static paths;
     *  - path: only the mount path and below ("^/api(/|$)"), except static paths below it.
     * Static paths are left to Plesk's own locations, which serve them from the document
     * root (or pass them to Apache, whose snippet excludes them as well).
     *
     * Timeouts and client_max_body_size are inherited from the domain's
     * server block (Plesk hosting settings).
     *
     * @param array $target ['port' => int] or ['socket' => '/run/runway/<id>/app.sock'], plus
     *                      'mode' (web|path), 'mountPath', 'staticPaths' (see App::proxyTarget())
     * @return string Empty when the target is not usable
     */
    public static function nginx(array $target)
    {
        $template = <<<'NGINX'
# Runway: reverse proxy {SCOPE} to the application on {TARGET}
location ~ {REGEX} {
    proxy_pass {UPSTREAM};
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header X-Forwarded-Port $server_port;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection $http_connection;
    proxy_connect_timeout 10s;
}
NGINX;
        list($mode, $mount, $static) = self::scope($target);
        if ($mode === null) {
            return '';
        }
        $alternatives = implode('|', array_map([__CLASS__, 'regexQuote'], $static));
        if ($mode === Modules_Runway_App::MODE_PATH) {
            // Static paths are relative to the mount path here: "^/api(?!/(docs)(/|$))(/|$)".
            $regex = '^' . self::regexQuote($mount) . ($static ? '(?!/(' . $alternatives . ')(/|$))' : '') . '(/|$)';
            $scope = 'of ' . $mount;
        } else {
            $regex = '^/(?!' . self::NGINX_RESERVED . ($static ? '|(' . $alternatives . ')(/|$)' : '') . ')';
            $scope = 'of the site';
        }
        if (isset($target['socket'])) {
            $socket = self::socket($target['socket']);
            $upstream = 'http://unix:' . $socket . ':';
            $label = 'unix:' . $socket;
        } else {
            $label = '127.0.0.1:' . self::port($target);
            $upstream = 'http://' . $label;
        }
        return str_replace(['{SCOPE}', '{TARGET}', '{REGEX}', '{UPSTREAM}'], [$scope, $label, $regex, $upstream], $template);
    }

    /**
     * Apache snippet placed inside the domain's <VirtualHost>. Only effective
     * when nginx does not handle the request itself (no nginx installed, or
     * the paths excluded from the nginx snippet, which nginx passes on to
     * Apache in proxy mode - hence the same exclusions here: Plesk paths and
     * static paths get "ProxyPass <path> !" before the proxied prefix, because
     * the first matching ProxyPass wins). ProxyPass matches whole path
     * segments, so "/api" covers /api and /api/... but not /apix.
     * Everything is wrapped in IfModule so a missing module can never break
     * the Apache configuration of the whole server. The forwarding headers are
     * overwritten (not appended) like in the nginx snippet, so clients cannot
     * spoof them. WebSockets: Apache 2.4.47+ tunnels the Upgrade handshake with the ProxyPass
     * parameter upgrade=websocket; older versions reject unknown ProxyPass parameters (a fatal
     * configuration error), so the parameter is only emitted inside <IfVersion >= 2.4.47>.
     *
     * @param array $target Same as for nginx()
     * @return string Empty when the target is not usable
     */
    public static function apache(array $target)
    {
        $template = <<<'APACHE'
# Runway: reverse proxy {SCOPE} to the application on {TARGET}
<IfModule mod_proxy.c>
<IfModule mod_proxy_http.c>
    ProxyPreserveHost On
{EXCLUSIONS}
    <IfModule mod_version.c>
        <IfVersion >= 2.4.47>
            ProxyPass {PREFIX} {UPSTREAM} retry=0 upgrade=websocket
        </IfVersion>
        <IfVersion < 2.4.47>
            ProxyPass {PREFIX} {UPSTREAM} retry=0
        </IfVersion>
    </IfModule>
    <IfModule !mod_version.c>
        ProxyPass {PREFIX} {UPSTREAM} retry=0
    </IfModule>
    ProxyPassReverse {PREFIX} {REVERSE}
    <IfModule mod_headers.c>
        RequestHeader set X-Forwarded-Proto "https" env=HTTPS
        RequestHeader set X-Forwarded-Proto "http" env=!HTTPS
        RequestHeader set X-Real-IP "expr=%{REMOTE_ADDR}"
        RequestHeader set X-Forwarded-Port "expr=%{SERVER_PORT}"
        RequestHeader unset X-Forwarded-Host
    </IfModule>
</IfModule>
</IfModule>
APACHE;
        list($mode, $mount, $static) = self::scope($target);
        if ($mode === null) {
            return '';
        }
        if ($mode === Modules_Runway_App::MODE_PATH) {
            $prefix = $mount;
            $scope = 'of ' . $mount;
            $excluded = [];
        } else {
            $prefix = '/';
            $scope = 'of the site';
            $excluded = ['/.well-known/acme-challenge/', '/plesk-stat', '/webstat', '/webstat-ssl', '/ftpstat',
                '/anon_ftpstat', '/awstats-icon'];
        }
        foreach ($static as $path) {
            $excluded[] = $mount . '/' . $path;
        }
        $lines = [];
        foreach ($excluded as $path) {
            $lines[] = '    ProxyPass ' . $path . ' !';
        }
        // The backend URL keeps the prefix: the application sees the original path.
        $suffix = $mode === Modules_Runway_App::MODE_PATH ? $mount : '/';
        if (isset($target['socket'])) {
            $socket = self::socket($target['socket']);
            $label = 'unix:' . $socket;
            $upstream = '"unix:' . $socket . '|http://localhost' . $suffix . '"';
            $reverse = 'http://localhost' . $suffix;
        } else {
            $label = '127.0.0.1:' . self::port($target);
            $upstream = 'http://' . $label . $suffix;
            $reverse = $upstream;
        }
        return str_replace(
            ['{SCOPE}', '{TARGET}', '{EXCLUSIONS}', '{PREFIX}', '{UPSTREAM}', '{REVERSE}'],
            [$scope, $label, implode("\n", $lines), $prefix, $upstream, $reverse],
            $template
        );
    }

    /**
     * Validated mode, mount path and static paths of a proxy target. The values come from the
     * domain settings (validated on save) and are checked again because they end up in the
     * web server configuration of the whole server.
     *
     * @param array $target
     * @return array [mode|null, mount path ('' in web mode), static paths without the leading
     *               "/" (relative to the mount path in path mode)]; mode null = do not proxy
     */
    private static function scope(array $target)
    {
        $mode = isset($target['mode']) && $target['mode'] === Modules_Runway_App::MODE_PATH
            ? Modules_Runway_App::MODE_PATH
            : Modules_Runway_App::MODE_WEB;
        $mount = '';
        if ($mode === Modules_Runway_App::MODE_PATH) {
            $mount = isset($target['mountPath']) ? (string)$target['mountPath'] : '';
            if (!Modules_Runway_App::isValidUrlPrefix($mount) || Modules_Runway_App::isReservedPath($mount)) {
                return [null, '', []];
            }
        }
        $static = [];
        $paths = isset($target['staticPaths']) && is_array($target['staticPaths']) ? $target['staticPaths'] : [];
        foreach (array_slice($paths, 0, Modules_Runway_App::MAX_STATIC_PATHS) as $path) {
            $path = is_string($path) ? $path : '';
            if (!Modules_Runway_App::isValidUrlPrefix($path)) {
                continue;
            }
            if ($mode === Modules_Runway_App::MODE_PATH) {
                // Only paths below the mount path matter; the rest is not proxied anyway.
                if (strpos($path, $mount . '/') !== 0) {
                    continue;
                }
                $path = substr($path, strlen($mount));
            }
            $static[] = substr($path, 1);
        }
        return [$mode, $mount, array_values(array_unique($static))];
    }

    /**
     * Escapes a URL path (letters, digits and "._~-/" only) for an nginx regex.
     *
     * @param string $path
     * @return string
     */
    private static function regexQuote($path)
    {
        return str_replace('.', '\.', (string)$path);
    }

    /**
     * @param array $target
     * @return int
     */
    private static function port(array $target)
    {
        $port = isset($target['port']) ? (int)$target['port'] : 0;
        if ($port < 1024 || $port > 65535) {
            throw new InvalidArgumentException('Invalid port');
        }
        return $port;
    }

    /**
     * @param string $path
     * @return string
     */
    private static function socket($path)
    {
        if (!preg_match('#^/run/runway/\d{1,10}/app\.sock$#', (string)$path)) {
            throw new InvalidArgumentException('Invalid socket path');
        }
        return $path;
    }

    /**
     * Regenerates the web server configuration of a domain.
     *
     * @param pm_Domain $domain
     * @throws Modules_Runway_Exception
     */
    public static function reconfigure(pm_Domain $domain)
    {
        try {
            $webServer = new pm_WebServer();
            $webServer->updateDomainConfiguration($domain);
            return;
        } catch (Exception $e) {
            Modules_Runway_Log::warn('updateDomainConfiguration failed for ' . $domain->getName() . ': ' . $e->getMessage()
                . '; falling back to httpdmng');
        }
        Modules_Runway_Helper::call('web-reconfigure', ['domains' => [(string)$domain->getName()]]);
    }
}
