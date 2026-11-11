<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Injects the reverse proxy configuration into the web server config of
 * domains that have an enabled application. Must be fast and must never
 * throw: it runs while Plesk generates web server configuration.
 *
 * Plesk calls getDomainNginxProxyConfig() when nginx proxies to Apache
 * (the default "proxy mode") and getDomainNginxConfig() when nginx is the
 * only web server, so both return the same snippet.
 */
class Modules_Runway_WebServer extends pm_Hook_WebServer
{
    public function getDomainNginxConfig(pm_Domain $domain)
    {
        return $this->nginx($domain);
    }

    public function getDomainNginxProxyConfig(pm_Domain $domain)
    {
        return $this->nginx($domain);
    }

    public function getDomainApacheConfig(pm_Domain $domain)
    {
        try {
            $target = Modules_Runway_App::proxyTarget($domain);
            return $target ? Modules_Runway_WebConfig::apache($target) : '';
        } catch (Throwable $e) {
            return '';
        }
    }

    private function nginx(pm_Domain $domain)
    {
        try {
            $target = Modules_Runway_App::proxyTarget($domain);
            return $target ? Modules_Runway_WebConfig::nginx($target) : '';
        } catch (Throwable $e) {
            return '';
        }
    }
}
