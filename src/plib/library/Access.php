<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Access control helpers.
 */
class Modules_Runway_Access
{
    /** Permission name declared by the Permissions hook (service plan / subscription level). */
    const PERMISSION = 'manage_runway_apps';

    /**
     * @return bool
     */
    public static function isAdmin()
    {
        return pm_Session::getClient()->isAdmin();
    }

    /**
     * @throws pm_Exception
     */
    public static function requireAdmin()
    {
        if (!self::isAdmin()) {
            throw new pm_Exception(pm_Locale::lmsg('errorAccessDenied'));
        }
    }

    /**
     * Whether the current user may manage the application of the given domain.
     *
     * @param pm_Domain $domain
     * @return bool
     */
    public static function canManage(pm_Domain $domain)
    {
        $client = pm_Session::getClient();
        if ($client->isAdmin()) {
            return true;
        }
        if (!$client->hasAccessToDomain($domain->getId())) {
            return false;
        }
        try {
            return (bool)$client->hasPermission(self::PERMISSION, $domain);
        } catch (Exception $e) {
            Modules_Runway_Log::debug('Permission check failed: ' . $e->getMessage());
            return false;
        }
    }

    /**
     * Resolves the domain of a request and enforces access. The id is taken from the JSON
     * body (site_id) when given, otherwise from the query string (site_id, id, dom_id).
     *
     * @param Zend_Controller_Request_Abstract $request
     * @param array $body Decoded JSON body of a POST request
     * @return pm_Domain
     * @throws pm_Exception
     */
    public static function domainFromRequest($request, array $body = [])
    {
        $id = 0;
        $candidates = [isset($body['site_id']) && is_scalar($body['site_id']) ? $body['site_id'] : null];
        // contextParams: site_id = the domain, dom_id = its subscription (main domain).
        foreach (['site_id', 'id', 'dom_id'] as $param) {
            $candidates[] = $request->getParam($param);
        }
        foreach ($candidates as $value) {
            if ($value !== null && ctype_digit((string)$value) && (int)$value > 0) {
                $id = (int)$value;
                break;
            }
        }
        if ($id <= 0) {
            throw new pm_Exception(pm_Locale::lmsg('errorNoDomain'));
        }
        try {
            $domain = pm_Domain::getByDomainId($id);
        } catch (Exception $e) {
            throw new pm_Exception(pm_Locale::lmsg('errorNoDomain'));
        }
        if (!self::canManage($domain)) {
            throw new pm_Exception(pm_Locale::lmsg('errorAccessDenied'));
        }
        if (!$domain->hasHosting()) {
            throw new pm_Exception(pm_Locale::lmsg('errorNoHosting'));
        }
        return $domain;
    }
}
