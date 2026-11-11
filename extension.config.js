// Copyright 2026 Taiizor. Licensed under the MIT License.
//
// Configuration of @plesk/plesk-ext-sdk (see "Extension SDK features" in the SDK documentation,
// https://github.com/plesk/plesk-ext-sdk, and docs/FOUNDATION-NOTES.md section 2).
// Every route is rendered by the generated src/htdocs/index.php (IndexController::viewAction)
// and maps to a component in src/frontend. The first route is the default page.
// Page titles come from the locale key "<component>.title" of the 'app' section
// (src/plib/resources/locales/app/*.php); "title" below is only the fallback.
// "parent" adds the parent page to the Plesk breadcrumbs (SDK Page component).

module.exports = {
    routes: [
        { path: 'overview', component: 'Overview', title: 'Runway' },
        { path: 'toolchains', component: 'Toolchains', title: 'Toolchains', parent: '/overview' },
        { path: 'settings', component: 'Settings', title: 'Runway Settings', parent: '/overview' },
        // The Dev Tools button of a domain (plib/hooks/CustomButtons.php, contextParams) opens
        // index.php/domain?dom_id=<subscription>&site_id=<domain>; Domain reads site_id.
        { path: 'domain', component: 'Domain', title: 'Runway' },
    ],
    webpack: (config, { isDev }) => ({
        ...config,
        // No source maps in the package: they would double its size.
        devtool: isDev ? 'cheap-module-source-map' : false,
    }),
};
