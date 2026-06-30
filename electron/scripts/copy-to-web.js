#!/usr/bin/env node
/* Copy the installers electron-builder produced in dist/ into the website's
 * download folder (app/static/downloads), giving each one a stable, version-less
 * filename so index.html can link to it without changing on every release.
 *
 * Only the artifacts that actually exist are copied, so this works whether you
 * built just the macOS target or cross-built Windows/Linux as well. Run via
 * `npm run dist` (which calls it automatically) or `npm run copy:web`.
 */
const fs = require("fs");
const path = require("path");

const DIST = path.join(__dirname, "..", "dist");
const WEB = path.join(__dirname, "..", "..", "app", "static", "downloads");

// First match wins, so list the more specific patterns before the looser ones.
const RULES = [
  { match: (f) => f.endsWith(".dmg"), dest: "Meerato-mac.dmg" },
  { match: (f) => f.endsWith("-mac.zip"), dest: "Meerato-mac.zip" },
  { match: (f) => f.endsWith(".exe"), dest: "Meerato-windows.exe" },
  { match: (f) => f.endsWith(".AppImage"), dest: "Meerato-linux.AppImage" },
  { match: (f) => f.endsWith(".deb"), dest: "Meerato-linux.deb" },
];

if (!fs.existsSync(DIST)) {
  console.error(`[copy-to-web] no dist/ folder yet — run a build first.`);
  process.exit(0);
}

fs.mkdirSync(WEB, { recursive: true });

const files = fs.readdirSync(DIST);
let copied = 0;
const claimed = new Set();

for (const rule of RULES) {
  const src = files.find((f) => rule.match(f) && !claimed.has(f));
  if (!src) continue;
  claimed.add(src);
  fs.copyFileSync(path.join(DIST, src), path.join(WEB, rule.dest));
  console.log(`[copy-to-web] ${src} -> downloads/${rule.dest}`);
  copied++;
}

if (copied === 0) {
  console.warn(`[copy-to-web] no installers found in dist/ to copy.`);
} else {
  console.log(`[copy-to-web] copied ${copied} artifact(s) into ${WEB}`);
}
