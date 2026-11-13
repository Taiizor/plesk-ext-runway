<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Buttons: "Runway" in the left navigation, a per-domain "Runway" button in Websites & Domains
 * (Dev Tools) and Runway's mark among the icons of a domain row whose application is enabled.
 * They open the React pages of the extension (routes of extension.config.js).
 *
 * Navigation: Plesk draws a different navigation per view, each with its own place:
 *  - PLACE_ADMIN_NAVIGATION: the administrator's Service Provider view (Server Management);
 *  - PLACE_HOSTING_PANEL_NAVIGATION: the administrator's Power User view (Plesk 18.0.82 renders
 *    it nowhere else);
 *  - PLACE_HOSTING_PANEL_TABS: the customer panel's navigation (customers with the Runway
 *    permission). Plesk also renders this place as a tab of every subscription page that an
 *    administrator or reseller opens; that tab would lead to the server-wide overview and lose
 *    the subscription, so it is shown to customers only.
 * Each view thus shows the entry once. The visibility callbacks run on every panel request: they
 * read the session and the database, never the root helper.
 */
class Modules_Runway_CustomButtons extends pm_Hook_CustomButtons
{
    public function getButtons()
    {
        // logo.png: the mark on its navy tile (light backgrounds). nav.png: the mark in white,
        // because Plesk draws navigation icons as they are on its dark sidebar. header.svg: the
        // mark in mid grey without a tile, next to the grey 16 px icons of a domain row; images
        // keep their colours in the dark theme, where grey stays readable (scripts/render-assets.ts).
        $icon = pm_Context::getBaseUrl() . 'images/logo.png';
        $navigation = [
            'title' => pm_Locale::lmsg('buttonAdminTitle'),
            'description' => pm_Locale::lmsg('buttonAdminDescription'),
            'icon' => pm_Context::getBaseUrl() . 'images/nav.png',
            'link' => pm_Context::getBaseUrl() . 'index.php/overview',
        ];
        $domainButton = [
            'title' => pm_Locale::lmsg('buttonDomainTitle'),
            'description' => pm_Locale::lmsg('buttonDomainDescription'),
            'icon' => $icon,
            // contextParams appends ?site_id=<id>&dom_id=<subscription id>
            'link' => pm_Context::getBaseUrl() . 'index.php/domain',
            'contextParams' => true,
            'visibility' => [$this, 'isDomainButtonVisible'],
        ];

        $buttons = [
            array_merge($navigation, [
                'place' => self::PLACE_ADMIN_NAVIGATION,
                'section' => self::SECTION_NAV_SERVER_MANAGEMENT,
            ]),
            array_merge($navigation, [
                'place' => self::PLACE_HOSTING_PANEL_NAVIGATION,
                'visibility' => [$this, 'isNavigationVisible'],
            ]),
            array_merge($navigation, [
                'place' => self::PLACE_HOSTING_PANEL_TABS,
                'visibility' => [$this, 'isCustomerNavigationVisible'],
            ]),
            array_merge($domainButton, ['place' => self::PLACE_DOMAIN_PROPERTIES]),
        ];

        if (defined('pm_Hook_CustomButtons::PLACE_DOMAIN_PROPERTIES_DYNAMIC')) {
            $buttons[] = array_merge($domainButton, [
                'place' => self::PLACE_DOMAIN_PROPERTIES_DYNAMIC,
                'section' => self::SECTION_DOMAIN_PROPS_DYNAMIC_DEV_TOOLS,
            ]);
        }
        // Plesk 18.0.41+: the icons of a row in Websites & Domains (and the administrator's domain
        // list). The title is the hover text; Plesk 18.0.82 shows it for every row alike (a
        // per-row "tooltip" reaches the list data but is not shown), so it stays "Runway".
        if (defined('pm_Hook_CustomButtons::PLACE_DOMAIN_HEADER_DYNAMIC')) {
            $buttons[] = array_merge($domainButton, [
                'place' => self::PLACE_DOMAIN_HEADER_DYNAMIC,
                'icon' => pm_Context::getBaseUrl() . 'images/header.svg',
                'visibility' => [$this, 'isHeaderButtonVisible'],
            ]);
        }

        return $buttons;
    }

    /**
     * Navigation entry of the Power User view (PLACE_HOSTING_PANEL_NAVIGATION): administrators.
     *
     * @param array $params Context parameters (empty for navigation buttons)
     * @return bool
     */
    public function isNavigationVisible(array $params = [])
    {
        try {
            return (bool)pm_Session::getClient()->isAdmin();
        } catch (Exception $e) {
            Modules_Runway_Log::debug('Navigation visibility check failed: ' . $e->getMessage());
            return false;
        }
    }

    /**
     * Navigation entry of the customer panel (PLACE_HOSTING_PANEL_TABS): customers with the
     * Runway permission on one of their subscriptions (the overview lists only the domains they
     * may manage), also when an administrator logged in as the customer. Never administrators or
     * resellers, for whom Plesk renders this place as a tab of a subscription's page.
     *
     * @param array $params Context parameters (empty for navigation buttons)
     * @return bool
     */
    public function isCustomerNavigationVisible(array $params = [])
    {
        try {
            $client = pm_Session::getClient();
            if (!$client->isClient()) {
                return false;
            }
            foreach (pm_Session::getCurrentDomains(true) as $domain) {
                try {
                    if ($client->hasPermission(Modules_Runway_Access::PERMISSION, $domain)) {
                        return true;
                    }
                } catch (Exception $e) {
                    continue;
                }
            }
        } catch (Exception $e) {
            Modules_Runway_Log::debug('Navigation visibility check failed: ' . $e->getMessage());
        }
        return false;
    }

    /**
     * @param array $params Context parameters (site_id, alias_id, ...)
     * @return bool
     */
    public function isDomainButtonVisible(array $params)
    {
        return self::manageableDomain($params) !== null;
    }

    /**
     * Runway's mark in a domain row: the domain has an enabled Runway application, i.e. Runway
     * serves it (like the Node.js icon of a domain with Node.js on). Called for every row of the
     * list: it reads the stored configuration only, never the root helper. The parameters
     * include the FTP password of the subscription in plain text: never log them.
     *
     * @param array $params Context parameters (site_id, alias_id, ...)
     * @return bool
     */
    public function isHeaderButtonVisible(array $params)
    {
        $domain = self::manageableDomain($params);
        if ($domain === null) {
            return false;
        }
        $config = Modules_Runway_App::storedConfig($domain);
        return $config !== null && !empty($config['enabled']);
    }

    /**
     * @param array $params Context parameters of a domain button
     * @return pm_Domain|null The domain (not an alias) when it has hosting and the user may manage it
     */
    private static function manageableDomain(array $params)
    {
        if (!empty($params['alias_id']) || empty($params['site_id'])) {
            return null;
        }
        try {
            $domain = pm_Domain::getByDomainId((int)$params['site_id']);
            return $domain->hasHosting() && Modules_Runway_Access::canManage($domain) ? $domain : null;
        } catch (Exception $e) {
            return null;
        }
    }
}
