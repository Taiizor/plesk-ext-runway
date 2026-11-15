// Copyright 2026 Taiizor. Licensed under the MIT License.

/**
 * Automates capturing clean, comprehensive, production-ready screenshots of Runway in Plesk.
 * Captures both documentation screenshots (docs/screenshots/) and
 * extension catalog screenshots (src/_meta/screenshots/).
 *
 * Usage:
 *   bun run screenshots
 *   or:
 *   CONTAINER=grt-plesk PANEL_PORT=18880 bun run screenshots
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
        const styleId = 'runway-shot-cleaner';
        let style = document.getElementById(styleId);
        if (!style) {
            style = document.createElement('style');
            style.id = styleId;
            document.head.appendChild(style);
        }
        style.textContent = `
            .pul-layout__header-addon,
            .license-status,
            [data-type="license-status"],
            .license-status-alert,
            [class*="trial-banner"],
            .cookie-policy-info,
            [class*="cookie-policy"],
            .cookie-banner {
                display: none !important;
            }
        `;
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
    explicitHeight?: number,
) => {
    const dest = resolve(ROOT, destRelPath);
    mkdirSync(resolve(dest, '..'), { recursive: true });

    await hideTrialAndNoise(page);

    let height = explicitHeight;
    if (!height) {
        // Reset viewport to small height first so content shrinks and scrollHeight is strictly measured
        await page.setViewport({ width, height: 600, deviceScaleFactor: 1 });
        await new Promise(r => setTimeout(r, 200));

        const scrollH = await page.evaluate(() => {
            const content = document.querySelector('.pul-layout__content') as HTMLElement | null;
            return content ? content.scrollHeight : document.body.scrollHeight;
        });
        height = Math.max(900, scrollH + 320);
    }

    await page.setViewport({ width, height, deviceScaleFactor: 1 });
    await hideTrialAndNoise(page);
    await new Promise(r => setTimeout(r, 500));

    await page.screenshot({ path: dest, fullPage: false });
    console.log(`Saved ${destRelPath} (${width}x${height})`);
};

const clickTabByText = async (page: Page, text: string): Promise<boolean> => {
    const found = await page.evaluate((targetText) => {
        const links = Array.from(document.querySelectorAll('a.pul-tabs__link')) as HTMLElement[];
        const match = links.find(a => a.innerText && a.innerText.toLowerCase().includes(targetText.toLowerCase()));
        if (match) {
            match.click();
            return true;
        }
        return false;
    }, text);
    if (found) {
        await new Promise(r => setTimeout(r, 900));
        await hideTrialAndNoise(page);
    }
    return found;
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

        // 1. Log in as administrator
        console.log('\n--- Administrator Session ---');
        console.log('Logging in as Administrator...');
        const adminLoginUrl = getLoginUrl('admin');
        await page.goto(adminLoginUrl, { waitUntil: 'networkidle2' });

        // ==========================================
        // 1. OVERVIEW
        // ==========================================
        console.log('\n[1/4] Capturing Overview views...');
        await page.goto(`${BASE_URL}/modules/runway/index.php/overview`, { waitUntil: 'networkidle2' });
        await new Promise(r => setTimeout(r, 1200));

        await setDarkMode(page, false);
        await capture(page, 'docs/screenshots/admin-overview.png', 1440);
        await capture(page, 'src/_meta/screenshots/3.png', 1024, 768);

        await setDarkMode(page, true);
        await capture(page, 'docs/screenshots/admin-overview-dark.png', 1440);
        await setDarkMode(page, false);

        // ==========================================
        // 2. DOMAIN PAGE (gotest.local / site_id=1)
        // ==========================================
        console.log('\n[2/4] Capturing Domain views (gotest.local)...');
        await page.goto(`${BASE_URL}/modules/runway/index.php/domain?site_id=1`, { waitUntil: 'networkidle2' });
        await new Promise(r => setTimeout(r, 1500));

        // Tab 1: Status & Metrics (Comprehensive height covers HeroHeader, 4 metric charts, full Status Panel)
        await setDarkMode(page, false);
        await capture(page, 'docs/screenshots/admin-domain.png', 1440);
        await capture(page, 'src/_meta/screenshots/1.png', 1024, 768);

        await setDarkMode(page, true);
        await capture(page, 'docs/screenshots/admin-domain-dark.png', 1440);
        await setDarkMode(page, false);

        // Tab 2: Settings (Expand collapsible Advanced section to show full form, commands, limits, triggers, and visual EnvEditor)
        console.log('Switching to Settings tab...');
        await clickTabByText(page, 'Settings');
        await page.evaluate(() => {
            const collapsedBtn = document.querySelector('.pul-section--collapsed .pul-section__control-button') as HTMLElement | null;
            if (collapsedBtn) collapsedBtn.click();
        });
        await new Promise(r => setTimeout(r, 800));
        await capture(page, 'docs/screenshots/admin-domain-advanced.png', 1440);

        // Tab 3: Project & Files
        console.log('Switching to Project tab...');
        await clickTabByText(page, 'Project');
        await capture(page, 'docs/screenshots/admin-domain-project.png', 1440);

        // Drawer 1: Create sample app
        console.log('Opening sample app drawer...');
        const sampleOpened = await page.evaluate(() => {
            const btns = Array.from(document.querySelectorAll('button')) as HTMLElement[];
            const btn = btns.find(b => b.innerText && b.innerText.includes('Create sample app'));
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        });
        if (sampleOpened) {
            await new Promise(r => setTimeout(r, 800));
            await hideTrialAndNoise(page);
            await capture(page, 'docs/screenshots/admin-domain-sample.png', 1440, 950);
            await page.keyboard.press('Escape');
            await new Promise(r => setTimeout(r, 600));
        }

        // Drawer 2: Fetch binary from URL
        console.log('Opening fetch binary drawer...');
        const fetchOpened = await page.evaluate(() => {
            const btns = Array.from(document.querySelectorAll('button')) as HTMLElement[];
            const btn = btns.find(b => b.innerText && b.innerText.includes('Fetch binary from URL'));
            if (btn) {
                btn.click();
                return true;
            }
            return false;
        });
        if (fetchOpened) {
            await new Promise(r => setTimeout(r, 800));
            await hideTrialAndNoise(page);
            await capture(page, 'docs/screenshots/admin-domain-fetch.png', 1440, 950);
            await page.keyboard.press('Escape');
            await new Promise(r => setTimeout(r, 600));
        }

        // Tab 4: Optional operations
        console.log('Switching to Optional operations tab...');
        await clickTabByText(page, 'operations');
        await capture(page, 'docs/screenshots/admin-domain-operations.png', 1440);

        // Tab 5: Logs
        console.log('Switching to Logs tab...');
        await clickTabByText(page, 'Logs');
        await capture(page, 'docs/screenshots/admin-domain-logs.png', 1440);

        // Tab 6: Help
        console.log('Switching to Help tab...');
        await clickTabByText(page, 'Help');
        await capture(page, 'docs/screenshots/admin-domain-help.png', 1440);

        // ==========================================
        // 3. TOOLCHAINS
        // ==========================================
        console.log('\n[3/4] Capturing Toolchains views...');
        await page.goto(`${BASE_URL}/modules/runway/index.php/toolchains`, { waitUntil: 'networkidle2' });
        await new Promise(r => setTimeout(r, 1200));

        // Go Tab
        await setDarkMode(page, false);
        await capture(page, 'docs/screenshots/admin-toolchains.png', 1440);
        await capture(page, 'src/_meta/screenshots/2.png', 1024, 768);

        await setDarkMode(page, true);
        await capture(page, 'docs/screenshots/admin-toolchains-dark.png', 1440);
        await setDarkMode(page, false);

        // PHP Tab (FrankenPHP)
        console.log('Switching to Toolchains PHP tab...');
        await clickTabByText(page, 'PHP');
        await capture(page, 'docs/screenshots/admin-toolchains-php.png', 1440);

        // Ruby Tab
        console.log('Switching to Toolchains Ruby tab...');
        await clickTabByText(page, 'Ruby');
        await capture(page, 'docs/screenshots/admin-toolchains-ruby.png', 1440);

        // .NET Tab
        console.log('Switching to Toolchains .NET tab...');
        await clickTabByText(page, '.NET');
        await capture(page, 'docs/screenshots/admin-toolchains-dotnet.png', 1440);

        // Rust Tab
        console.log('Switching to Toolchains Rust tab...');
        await clickTabByText(page, 'Rust');
        await capture(page, 'docs/screenshots/admin-toolchains-rust.png', 1440);

        // Bun Tab
        console.log('Switching to Toolchains Bun tab...');
        await clickTabByText(page, 'Bun');
        await capture(page, 'docs/screenshots/admin-toolchains-bun.png', 1440);

        // Java Tab
        console.log('Switching to Toolchains Java tab...');
        await clickTabByText(page, 'Java');
        await capture(page, 'docs/screenshots/admin-toolchains-java.png', 1440);

        // Python Tab
        console.log('Switching to Toolchains Python tab...');
        await clickTabByText(page, 'Python');
        await capture(page, 'docs/screenshots/admin-toolchains-python.png', 1440);

        // ==========================================
        // 4. RUNWAY SETTINGS
        // ==========================================
        console.log('\n[4/4] Capturing Settings views...');
        await page.goto(`${BASE_URL}/modules/runway/index.php/settings`, { waitUntil: 'networkidle2' });
        await new Promise(r => setTimeout(r, 1000));

        await setDarkMode(page, false);
        await capture(page, 'docs/screenshots/admin-settings.png', 1440);

        await setDarkMode(page, true);
        await capture(page, 'docs/screenshots/admin-settings-dark.png', 1440);
        await setDarkMode(page, false);

        // ==========================================
        // 5. CUSTOMER VIEWS
        // ==========================================
        let hasCust1 = false;
        try {
            getLoginUrl('cust1');
            hasCust1 = true;
        } catch {
            hasCust1 = false;
        }

        if (hasCust1) {
            console.log('\n--- Customer Session (cust1) ---');
            console.log('Logging in as Customer (cust1)...');
            const custLoginUrl = getLoginUrl('cust1');
            await page.goto(custLoginUrl, { waitUntil: 'networkidle2' });

            // Customer Overview
            console.log('Capturing Customer Overview...');
            await page.goto(`${BASE_URL}/modules/runway/index.php/overview`, { waitUntil: 'networkidle2' });
            await new Promise(r => setTimeout(r, 1000));
            await capture(page, 'docs/screenshots/customer-overview.png', 1440);

            // Customer Domain Status & Metrics
            console.log('Capturing Customer Domain Status...');
            await page.goto(`${BASE_URL}/modules/runway/index.php/domain?site_id=1`, { waitUntil: 'networkidle2' });
            await new Promise(r => setTimeout(r, 1200));
            await capture(page, 'docs/screenshots/customer-domain.png', 1440);

            // Customer Domain Settings (Expand Advanced)
            console.log('Capturing Customer Domain Settings...');
            await clickTabByText(page, 'Settings');
            await page.evaluate(() => {
                const collapsedBtn = document.querySelector('.pul-section--collapsed .pul-section__control-button') as HTMLElement | null;
                if (collapsedBtn) collapsedBtn.click();
            });
            await new Promise(r => setTimeout(r, 800));
            await capture(page, 'docs/screenshots/customer-domain-advanced.png', 1440);

            // Customer Access Denied (visiting settings directly)
            console.log('Capturing Customer Access Denied...');
            await page.goto(`${BASE_URL}/modules/runway/index.php/settings`, { waitUntil: 'networkidle2' });
            await new Promise(r => setTimeout(r, 800));
            await capture(page, 'docs/screenshots/customer-domain-denied.png', 1440, 900);
        }

        console.log('\nAll comprehensive screenshots captured successfully!');
    } finally {
        await browser.close();
    }
}

main().catch(err => {
    console.error('Screenshot capture failed:', err);
    process.exit(1);
});
