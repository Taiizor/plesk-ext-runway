// Renders the brand assets from the SVG masters in assets/: the extension catalog icons
// (src/_meta/icons), the Dev Tools icon (src/htdocs/images/logo.png), the navigation icon
// (src/htdocs/images/nav.png), the icon of a domain row in Websites & Domains
// (src/htdocs/images/header.svg) and the GitHub social preview (docs/social-preview.png). Run it
// after changing a master:
//
//   bun run assets
//
// The PNGs are committed, so build.py and the Plesk package never need this script. Text of the
// social preview uses the first installed font of its font-family list.
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { Resvg } from "@resvg/resvg-js";

const ROOT = resolve(import.meta.dir, "..");
const read = (rel: string) => Bun.file(resolve(ROOT, rel)).text();
const write = async (rel: string, png: Uint8Array) => {
    const path = resolve(ROOT, rel);
    mkdirSync(resolve(path, ".."), { recursive: true });
    await Bun.write(path, png);
    console.log(`${rel} (${png.length} bytes)`);
};
const render = (svg: string, width: number) =>
    new Resvg(svg, { fitTo: { mode: "width", value: width }, font: { loadSystemFonts: true } }).render().asPng();
const inner = (svg: string) => {
    // Content of the root <svg> element, nested into the social preview.
    const match = svg.match(/<svg[^>]*>([\s\S]*)<\/svg>\s*$/i);
    if (!match || !/viewBox="0 0 128 128"/.test(svg)) throw new Error("the masters must be <svg viewBox=\"0 0 128 128\">");
    return match[1];
};

const glyph = await read("assets/logo.svg");
const tile = await read("assets/logo-tile.svg");

// Plesk draws navigation icons as they are, at reduced opacity on its dark sidebar, so the
// navigation gets the mark in white (and on the navy social card the navy would vanish too).
const lightMark = inner(glyph).replaceAll("#162238", "#ffffff");
const lightGlyph = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">${lightMark}</svg>`;

for (const size of [32, 64, 128]) await write(`src/_meta/icons/${size}x${size}.png`, render(tile, size));
await write("src/htdocs/images/logo.png", render(tile, 64)); // Dev Tools button, API context
await write("src/htdocs/images/nav.png", render(lightGlyph, 64)); // navigation (dark sidebar)
// Icon of a domain row (16 px, next to the grey line icons of the row): the mark in one mid grey.
// Plesk's dark theme inverts the whole page (html { filter: invert(0.9) hue-rotate(180deg) }) and
// inverts images back, so an image keeps its colours: #7a7a7a has a contrast of at least 3:1 on
// the white and light grey rows of the light theme and on the dark rows of the dark theme, where a
// black mark would vanish. An SVG, so it stays sharp at any pixel density.
const rowMark = inner(glyph)
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/ fill="#[0-9a-f]{6}"/gi, "")
    .replace(/>\s+</g, "><")
    .trim();
const rowIcon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" fill="#7a7a7a"><title>Runway</title>${rowMark}</svg>\n`;
await Bun.write(resolve(ROOT, "src/htdocs/images/header.svg"), rowIcon);
console.log(`src/htdocs/images/header.svg (${rowIcon.length} bytes)`);
const FONT = "Segoe UI, Inter, Roboto, Helvetica Neue, Arial, sans-serif";
const runtimes = ["Go", "Rust", "Bun", "Java", ".NET", "Python", "Ruby", "PHP"]
    .map((name) => `<tspan>${name}</tspan>`)
    .join('<tspan fill="#ffbe28"> · </tspan>');
const card = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#162238"/><stop offset="1" stop-color="#0e1626"/>
    </linearGradient>
  </defs>
  <rect width="1280" height="640" fill="url(#bg)"/>
  <svg x="80" y="172" width="256" height="256" viewBox="0 0 128 128">${lightMark}</svg>
  <g font-family="${FONT}" fill="#f4f7fc">
    <text x="400" y="222" font-size="108" font-weight="600">Runway</text>
    <text x="404" y="294" font-size="46" font-weight="300" fill="#aab8ce">for Plesk</text>
    <text x="404" y="368" font-size="33" font-weight="600">${runtimes}</text>
    <text x="404" y="428" font-size="29">Applications per domain on a Plesk server, without Docker</text>
    <text x="404" y="470" font-size="24" fill="#aab8ce">Toolchains installed from the panel · hardened systemd services</text>
    <text x="404" y="504" font-size="24" fill="#aab8ce">nginx / Apache proxy with WebSockets · Git deploy triggers</text>
    <text x="404" y="580" font-size="24" fill="#aab8ce">github.com/Taiizor/plesk-ext-runway</text>
    <text x="1200" y="580" font-size="24" fill="#aab8ce" text-anchor="end">MIT License</text>
  </g>
  <rect x="0" y="632" width="1280" height="8" fill="#ffbe28"/>
</svg>`;
await write("docs/social-preview.png", render(card, 1280));
