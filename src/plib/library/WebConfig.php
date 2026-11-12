<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Renders the reverse proxy snippets injected into the domain's web server
 * configuration and triggers regeneration of that configuration.
 */
class Modules_Runway_WebConfig
{
    /** Root-owned include files of switchable tcp applications (must match WEB_DIR of the helper). */
    const WEB_DIR = '/etc/runway/web';

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
     * Zero-downtime deployments (docs/DESIGN.md section 12.6): a switchable application carries
     * the marker line and proxies through the helper's pointer: unix to the root link
     * /run/runway/<id>.sock, tcp to $runway_upstream from the root-owned include file (a fail-closed
     * fallback when the file is missing: a path nobody but root can create, 502).
     *
     * @param array $target ['port' => int] or ['socket' => '/run/runway/<id>/app.sock'], plus
     *                      'mode' (web|path), 'mountPath', 'staticPaths', 'switchable', 'domainId'
     *                      (see App::proxyTarget())
     * @return string Empty when the target is not usable
     */
    public static function nginx(array $target)
    {
        $template = <<<'NGINX'
# Runway: reverse proxy {SCOPE} to the application on {TARGET}
{MARKER}location ~ {REGEX} {
{PROXY}
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
        $id = self::switchableId($target);
        $marker = $id !== null ? self::marker($id) . "\n" : '';
        if (isset($target['socket'])) {
            $socket = self::socket($target['socket'], $id);
            $label = 'unix:' . $socket;
            $proxy = '    proxy_pass http://unix:' . $socket . ':;';
        } elseif ($id !== null) {
            self::port($target);
            $label = '127.0.0.1 (port from ' . self::WEB_DIR . '/' . $id . '.nginx.conf)';
            $proxy = implode("\n", [
                '    set $runway_upstream "unix:/run/runway/' . $id . '.none:";',
                '    include ' . self::WEB_DIR . '/' . $id . '.nginx[.]conf;',
                '    proxy_pass http://$runway_upstream;',
                '    proxy_redirect http://$runway_upstream/ /;',
            ]);
        } else {
            $label = '127.0.0.1:' . self::port($target);
            $proxy = '    proxy_pass http://' . $label . ';';
        }
        return str_replace(['{SCOPE}', '{TARGET}', '{MARKER}', '{REGEX}', '{PROXY}'], [$scope, $label, $marker, $regex, $proxy], $template);
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
     * Zero-downtime deployments: the marker line, disablereuse=On (mod_proxy would reuse pooled
     * connections to the old version) and the pointer: the root link (unix), or the URL that the
     * root-owned include defines (tcp, with the same fail-closed fallback as nginx).
     *
     * @param array $target Same as for nginx()
     * @return string Empty when the target is not usable
     */
    public static function apache(array $target)
    {
        $template = <<<'APACHE'
# Runway: reverse proxy {SCOPE} to the application on {TARGET}
{MARKER}<IfModule mod_proxy.c>
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
        $id = self::switchableId($target);
        $marker = '';
        if (isset($target['socket'])) {
            $socket = self::socket($target['socket'], $id);
            $label = 'unix:' . $socket;
            $upstream = '"unix:' . $socket . '|http://localhost' . $suffix . '"';
            $reverse = 'http://localhost' . $suffix;
            if ($id !== null) {
                $marker = self::marker($id) . "\n";
            }
        } elseif ($id !== null) {
            self::port($target);
            $label = '127.0.0.1 (port from ' . self::WEB_DIR . '/' . $id . '.apache.conf)';
            $upstream = '${RUNWAY_UPSTREAM_' . $id . '}' . $suffix;
            $reverse = 'http://127.0.0.1:${RUNWAY_PORT_' . $id . '}' . $suffix;
            $marker = implode("\n", [
                self::marker($id),
                'IncludeOptional ' . self::WEB_DIR . '/' . $id . '.apache[.]conf',
                '<IfDefine !RUNWAY_UPSTREAM_' . $id . '>',
                '    Define RUNWAY_UPSTREAM_' . $id . ' unix:/run/runway/' . $id . '.none|http://localhost',
                '</IfDefine>',
                '<IfDefine !RUNWAY_PORT_' . $id . '>',
                '    Define RUNWAY_PORT_' . $id . ' 1',
                '</IfDefine>',
            ]) . "\n";
        } else {
            $label = '127.0.0.1:' . self::port($target);
            $upstream = 'http://' . $label . $suffix;
            $reverse = $upstream;
        }
        if ($id !== null) {
            // Pooled backend connections would keep reaching the old version after a switch.
            $template = str_replace(' retry=0', ' retry=0 disablereuse=On', $template);
        }
        return str_replace(
            ['{SCOPE}', '{TARGET}', '{MARKER}', '{EXCLUSIONS}', '{PREFIX}', '{UPSTREAM}', '{REVERSE}'],
            [$scope, $label, $marker, implode("\n", $lines), $prefix, $upstream, $reverse],
            $template
        );
    }

    /**
     * @param array $target
     * @return int|null The domain id when the target is switchable (zero-downtime), else null
     */
    private static function switchableId(array $target)
    {
        if (empty($target['switchable'])) {
            return null;
        }
        $id = isset($target['domainId']) ? (int)$target['domainId'] : 0;
        if ($id < 1) {
            throw new InvalidArgumentException('Invalid domain id');
        }
        return $id;
    }

    /**
     * The marker the deploy job looks for in the generated configuration (docs/DESIGN.md 12.6).
     *
     * @param int $id
     * @return string
     */
    private static function marker($id)
    {
        return '# Runway: zero-downtime #' . (int)$id;
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
     * @param int|null $id Domain id of a switchable application: its path is the root link
     * @return string
     */
    private static function socket($path, $id = null)
    {
        $pattern = $id !== null ? '#^/run/runway/' . (int)$id . '\.sock$#' : '#^/run/runway/\d{1,10}/app\.sock$#';
        if (!preg_match($pattern, (string)$path)) {
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
