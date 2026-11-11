<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Buttons: "Runway" in the administrator's navigation (server management)
 * and a per-domain "Runway" button in Websites & Domains (Dev Tools).
 * Both open the React pages of the extension (routes of extension.config.js).
 */
class Modules_Runway_CustomButtons extends pm_Hook_CustomButtons
{
    public function getButtons()
    {
        $icon = pm_Context::getBaseUrl() . 'images/logo.png';
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
            [
                'place' => self::PLACE_ADMIN_NAVIGATION,
                'section' => self::SECTION_NAV_SERVER_MANAGEMENT,
                'title' => pm_Locale::lmsg('buttonAdminTitle'),
                'description' => pm_Locale::lmsg('buttonAdminDescription'),
                'icon' => $icon,
                'link' => pm_Context::getBaseUrl() . 'index.php/overview',
            ],
            array_merge($domainButton, ['place' => self::PLACE_DOMAIN_PROPERTIES]),
        ];

        if (defined('pm_Hook_CustomButtons::PLACE_DOMAIN_PROPERTIES_DYNAMIC')) {
            $buttons[] = array_merge($domainButton, [
                'place' => self::PLACE_DOMAIN_PROPERTIES_DYNAMIC,
                'section' => self::SECTION_DOMAIN_PROPS_DYNAMIC_DEV_TOOLS,
            ]);
        }

        return $buttons;
    }

    /**
     * @param array $params Context parameters (site_id, alias_id, ...)
     * @return bool
     */
    public function isDomainButtonVisible(array $params)
    {
        if (!empty($params['alias_id']) || empty($params['site_id'])) {
            return false;
        }
        try {
            $domain = pm_Domain::getByDomainId((int)$params['site_id']);
            return $domain->hasHosting() && Modules_Runway_Access::canManage($domain);
        } catch (Exception $e) {
            return false;
        }
    }
}
