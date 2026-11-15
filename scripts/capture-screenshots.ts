// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Automates capturing clean, production-ready screenshots of Runway in Plesk.
 * Captures both documentation screenshots (docs/screenshots/) and
 * extension catalog screenshots (src/_meta/screenshots/).
 *
 * Usage:
 *   bun scripts/capture-screenshots.ts
 *   or:
 *   CONTAINER=grt-plesk PANEL_PORT=18880 bun scripts/capture-screenshots.ts
 */

import { execSync } from 'node:child_process';
import { existsSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import puppeteer, { type Page, type Browser } from 'puppeteer-core';

const ROOT = resolve(import.meta.dir, '..');
const CONTAINER = process.env.CONTAINER || 'grt-plesk';
const PANEL_PORT = process.env.PANEL_PORT || '18880';
const BASE_URL = `http://localhost:${PANEL_PORT}`;

const CHROME_PATHS = [
    process.env.PUPPETEER_EXECUTABLE_PATH,
    'C:/Program Files/Google/Chrome/Application/chrome.exe',
    'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
].filter(Boolean) as string[];

const executablePath = CHROME_PATHS.find(p => existsSync(p));
if (!executablePath) {
    console.error('Chrome executable not found. Set PUPPETEER_EXECUTABLE_PATH.');
    process.exit(1);
}

const getLoginUrl = (user = 'admin'): string => {
    try {
        const userArg = user === 'admin' ? '' : `-user ${user}`;
        const cmd = `docker exec ${CONTAINER} plesk bin admin --get-login-link -relative-url ${userArg}`;
        const rel = execSync(cmd).toString().trim();
        return `${BASE_URL}${rel}`;
    } catch (err) {
        throw new Error(`Failed to get login link for ${user} from container ${CONTAINER}: ${err}`);
    }
};

const hideTrialAndNoise = async (page: Page) => {
    await page.evaluate(() => {
        // Hide trial status and license banners
        const style = document.createElement('style');
        style.textContent = `
            .pul-layout__header-addon,
            .license-status,
            [data-type="license-status"],
            .license-status-alert {
                display: none !important;
            }
        `;
        document.head.appendChild(style);
    });
};

const setDarkMode = async (page: Page, enable: boolean) => {
    await page.evaluate((enableDark) => {
        const switcher = document.querySelector('.theme-switcher') as HTMLElement | null;
        if (!switcher) return;
        const isDark = switcher.getAttribute('data-type') === 'dark-mode-on' || document.documentElement.classList.contains('dark');
        if ((enableDark && !isDark) || (!enableDark && isDark)) {
            switcher.click();
        }
    }, enable);
    await new Promise(r => setTimeout(r, 600));
    await hideTrialAndNoise(page);
};

const capture = async (
    page: Page,
    destRelPath: string,
    width = 1440,
    height = 900,
) => {
    const dest = resolve(ROOT, destRelPath);
    mkdirSync(resolve(dest, '..'), { recursive: true });

    await page.setViewport({ width, height, deviceScaleFactor: 1 });
    await hideTrialAndNoise(page);
    await new Promise(r => setTimeout(r, 500));

    await page.screenshot({ path: dest, fullPage: false });
    console.log(`Saved ${destRelPath} (${width}x${height})`);
};

async function main() {
    console.log(`Using Chrome: ${executablePath}`);
    console.log(`Connecting to Plesk on ${BASE_URL} (Container: ${CONTAINER})...`);

    const browser: Browser = await puppeteer.launch({
        executablePath,
        headless: true,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--hide-scrollbars',
        ],
    });

    try {
        const page = await browser.newPage();

        // 1. Log in as admin
        console.log('Logging in as Administrator...');
        const adminLoginUrl = getLoginUrl('admin');
        await page.goto(adminLoginUrl, { waitUntil: 'networkidle2' });

        // --- ADMIN OVERVIEW ---
        console.log('Capturing Overview...');
        await page.goto(`${BASE_URL}/modules/runway/index.php/overview`, { waitUntil: 'networkidle2' });
        await new Promise(r => setTimeout(r, 1200));

        await setDarkMode(page, false);
        await capture(page, 'docs/screenshots/admin-overview.png', 1440, 900);
        await capture(page, 'src/_meta/screenshots/3.png', 1024, 768);

        await setDarkMode(page, true);
        await capture(page, 'docs/screenshots/admin-overview-dark.png', 1440, 900);
        await setDarkMode(page, false);

        // --- ADMIN DOMAIN (gotest.local / site_id=1) ---
        console.log('Capturing Domain page...');
        await page.goto(`${BASE_URL}/modules/runway/index.php/domain?site_id=1`, { waitUntil: 'networkidle2' });
        await new Promise(r => setTimeout(r, 1500));

        await setDarkMode(page, false);
        await capture(page, 'docs/screenshots/admin-domain.png', 1440, 900);
        await capture(page, 'src/_meta/screenshots/1.png', 1024, 768);

        await setDarkMode(page, true);
        await capture(page, 'docs/screenshots/admin-domain-dark.png', 1440, 900);
        await setDarkMode(page, false);

        // Domain Settings Tab
        await page.evaluate(() => {
            const tabs = Array.from(document.querySelectorAll('.pul-tabs__tab, [role="tab"]')) as HTMLElement[];
            const settingsTab = tabs.find(t => t.innerText && t.innerText.includes('Settings'));
            settingsTab?.click();
        });
        await new Promise(r => setTimeout(r, 800));
        await capture(page, 'docs/screenshots/admin-domain-advanced.png', 1440, 900);

        // --- ADMIN TOOLCHAINS ---
        console.log('Capturing Toolchains...');
        await page.goto(`${BASE_URL}/modules/runway/index.php/toolchains`, { waitUntil: 'networkidle2' });
        await new Promise(r => setTimeout(r, 1200));

        await setDarkMode(page, false);
        await capture(page, 'docs/screenshots/admin-toolchains.png', 1440, 900);
        await capture(page, 'src/_meta/screenshots/2.png', 1024, 768);

        await setDarkMode(page, true);
        await capture(page, 'docs/screenshots/admin-toolchains-dark.png', 1440, 900);
        await setDarkMode(page, false);

        // Toolchains PHP & Ruby tabs if available
        await page.evaluate(() => {
            const tabs = Array.from(document.querySelectorAll('.pul-tabs__tab, [role="tab"], button')) as HTMLElement[];
            const phpTab = tabs.find(t => t.innerText && t.innerText.trim().toLowerCase() === 'php');
            phpTab?.click();
        });
        await new Promise(r => setTimeout(r, 500));
        await capture(page, 'docs/screenshots/admin-toolchains-php.png', 1440, 900);

        await page.evaluate(() => {
            const tabs = Array.from(document.querySelectorAll('.pul-tabs__tab, [role="tab"], button')) as HTMLElement[];
            const rubyTab = tabs.find(t => t.innerText && t.innerText.trim().toLowerCase() === 'ruby');
            rubyTab?.click();
        });
        await new Promise(r => setTimeout(r, 500));
        await capture(page, 'docs/screenshots/admin-toolchains-ruby.png', 1440, 900);

        // --- ADMIN SETTINGS ---
        console.log('Capturing Runway Settings...');
        await page.goto(`${BASE_URL}/modules/runway/index.php/settings`, { waitUntil: 'networkidle2' });
        await new Promise(r => setTimeout(r, 1000));

        await setDarkMode(page, false);
        await capture(page, 'docs/screenshots/admin-settings.png', 1440, 900);

        await setDarkMode(page, true);
        await capture(page, 'docs/screenshots/admin-settings-dark.png', 1440, 900);
        await setDarkMode(page, false);

        // --- CUSTOMER VIEWS (if cust1 exists) ---
        let hasCust1 = false;
        try {
            getLoginUrl('cust1');
            hasCust1 = true;
        } catch {
            hasCust1 = false;
        }

        if (hasCust1) {
            console.log('Logging in as Customer (cust1)...');
            const custLoginUrl = getLoginUrl('cust1');
            await page.goto(custLoginUrl, { waitUntil: 'networkidle2' });

            console.log('Capturing Customer Overview & Domain...');
            await page.goto(`${BASE_URL}/modules/runway/index.php/overview`, { waitUntil: 'networkidle2' });
            await new Promise(r => setTimeout(r, 1000));
            await capture(page, 'docs/screenshots/customer-overview.png', 1440, 900);

            await page.goto(`${BASE_URL}/modules/runway/index.php/domain?site_id=1`, { waitUntil: 'networkidle2' });
            await new Promise(r => setTimeout(r, 1200));
            await capture(page, 'docs/screenshots/customer-domain.png', 1440, 900);

            // Customer settings tab
            await page.evaluate(() => {
                const tabs = Array.from(document.querySelectorAll('.pul-tabs__tab, [role="tab"]')) as HTMLElement[];
                const settingsTab = tabs.find(t => t.innerText && t.innerText.includes('Settings'));
                settingsTab?.click();
            });
            await new Promise(r => setTimeout(r, 500));
            await capture(page, 'docs/screenshots/customer-domain-advanced.png', 1440, 900);
        }

        console.log('\nAll screenshots captured successfully!');
    } finally {
        await browser.close();
    }
}

main().catch(err => {
    console.error('Screenshot capture failed:', err);
    process.exit(1);
});
