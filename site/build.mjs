/**
 * Build the SHAWZIFY site: one hand-written landing page, plus the repository's
 * own Markdown docs rendered into the same shell.
 *
 * The docs are not copied or rewritten by hand -- they are read straight from
 * docs/ so the site cannot drift from the repository. Only links need fixing:
 * a relative `.md` link that works on GitHub has to become a `.html` link here.
 */
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import MarkdownIt from 'markdown-it';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const out = join(here, 'dist');

const REPO = 'omercsbn/shawzify';
const REPO_URL = `https://github.com/${REPO}`;

/** Pages rendered from Markdown, in sidebar order. */
const PAGES = [
  { file: 'README.md', slug: 'readme', title: 'Overview', group: 'Start here' },
  { file: 'docs/development.md', slug: 'development', title: 'Development', group: 'Start here' },
  {
    file: 'docs/troubleshooting.md',
    slug: 'troubleshooting',
    title: 'Troubleshooting',
    group: 'Start here',
  },
  { file: 'docs/architecture.md', slug: 'architecture', title: 'Architecture', group: 'How it works' },
  {
    file: 'docs/research/shawzin-format.md',
    slug: 'shawzin-format',
    title: 'The Shawzin song format',
    group: 'How it works',
  },
  {
    file: 'docs/research/music-sources.md',
    slug: 'music-sources',
    title: 'YouTube and Spotify',
    group: 'How it works',
  },
  {
    file: 'docs/research/existing-tools.md',
    slug: 'existing-tools',
    title: 'Other Shawzin tools',
    group: 'How it works',
  },
  { file: 'CONTRIBUTING.md', slug: 'contributing', title: 'Contributing', group: 'Project' },
  { file: 'SECURITY.md', slug: 'security', title: 'Security', group: 'Project' },
  {
    file: 'THIRD-PARTY-NOTICES.md',
    slug: 'third-party-notices',
    title: 'Third-party notices',
    group: 'Project',
  },
  { file: 'CHANGELOG.md', slug: 'changelog', title: 'Changelog', group: 'Project' },
];

const bySourceFile = new Map(PAGES.map((p) => [p.file, p]));

const md = new MarkdownIt({ html: true, linkify: true, breaks: false });

/** Turn a repo-relative Markdown link into a link that works on the site. */
function resolveLink(href, fromFile) {
  if (/^[a-z]+:/i.test(href) || href.startsWith('#') || href.startsWith('//')) return href;

  const [path, hash = ''] = href.split('#');
  if (!path) return href;

  const target = relative(root, resolve(dirname(join(root, fromFile)), path)).replace(/\\/g, '/');
  const page = bySourceFile.get(target);
  if (page) return `${page.slug}.html${hash ? '#' + hash : ''}`;

  // Anything else still lives in the repository: send the reader there.
  return `${REPO_URL}/blob/main/${target}${hash ? '#' + hash : ''}`;
}

function renderMarkdown(source, fromFile) {
  const tokens = md.parse(source, {});
  for (const token of tokens) {
    if (token.type !== 'inline' || !token.children) continue;
    for (const child of token.children) {
      if (child.type !== 'link_open') continue;
      const href = child.attrGet('href');
      if (!href) continue;
      const resolved = resolveLink(href, fromFile);
      child.attrSet('href', resolved);
      if (/^https?:/i.test(resolved)) {
        child.attrSet('target', '_blank');
        child.attrSet('rel', 'noopener');
      }
    }
  }
  return md.renderer.render(tokens, md.options, {});
}

function sidebar(activeSlug) {
  const groups = [];
  for (const page of PAGES) {
    let group = groups.find((g) => g.name === page.group);
    if (!group) groups.push((group = { name: page.group, pages: [] }));
    group.pages.push(page);
  }
  return groups
    .map(
      (group) => `      <section>
        <h4>${group.name}</h4>
        <ul>
${group.pages
  .map(
    (page) =>
      `          <li><a href="${page.slug}.html"${
        page.slug === activeSlug ? ' aria-current="page"' : ''
      }>${page.title}</a></li>`,
  )
  .join('\n')}
        </ul>
      </section>`,
    )
    .join('\n');
}

const MARK = `<svg class="mark" viewBox="0 0 48 48" aria-hidden="true"><path d="M24 13c5 0 9 3.2 9 7.4 0 5.4-5.2 11.6-9 14.6-3.8-3-9-9.2-9-14.6C15 16.2 19 13 24 13z" fill="#E8A84C"/></svg>`;

function shell({ title, description, body, bodyClass, depth, activeSlug }) {
  const base = depth === 0 ? '' : '../';
  const home = depth === 0 ? 'index.html' : '../index.html';
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<meta name="description" content="${description}">
<meta property="og:title" content="${title}">
<meta property="og:description" content="${description}">
<meta property="og:type" content="website">
<link rel="icon" href="${base}favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="${base}styles.css">
</head>
<body class="${bodyClass}">
<header class="topbar">
  <a class="brand" href="${home}">${MARK}<span>SHAWZIFY</span></a>
  <nav>
    <a href="${depth === 0 ? 'docs/readme.html' : 'readme.html'}">Docs</a>
    <a href="${REPO_URL}/releases/latest" target="_blank" rel="noopener">Download</a>
    <a href="${REPO_URL}" target="_blank" rel="noopener">GitHub</a>
  </nav>
</header>
${
  activeSlug
    ? `<div class="layout">
  <aside class="sidebar">
${sidebar(activeSlug)}
  </aside>
  <main class="doc">
${body}
  </main>
</div>`
    : body
}
<footer class="footer">
  <p>
    <a href="${REPO_URL}/blob/main/LICENSE" target="_blank" rel="noopener">MIT licensed</a> ·
    <a href="${depth === 0 ? 'docs/third-party-notices.html' : 'third-party-notices.html'}">Third-party notices</a> ·
    <a href="${depth === 0 ? 'docs/security.html' : 'security.html'}">Security</a>
  </p>
  <p class="disclaimer">
    SHAWZIFY is an independent fan project. It is not affiliated with, endorsed by, or
    connected to Digital Extremes. WARFRAME and the Shawzin are trademarks of Digital
    Extremes Ltd. No game assets are distributed here.
  </p>
</footer>
</body>
</html>
`;
}

// -- build ----------------------------------------------------------------

rmSync(out, { recursive: true, force: true });
mkdirSync(join(out, 'docs'), { recursive: true });

const landing = readFileSync(join(here, 'src', 'landing.html'), 'utf-8');
writeFileSync(
  join(out, 'index.html'),
  shell({
    title: 'SHAWZIFY — turn any song into a Warframe Shawzin performance',
    description:
      'A Windows desktop app that converts audio and MIDI into playable Warframe Shawzin song codes, entirely on your own machine.',
    body: landing,
    bodyClass: 'landing',
    depth: 0,
    activeSlug: null,
  }),
);

let rendered = 0;
for (const page of PAGES) {
  const source = join(root, page.file);
  if (!existsSync(source)) {
    console.warn(`  skipped ${page.file} (missing)`);
    continue;
  }
  const html = renderMarkdown(readFileSync(source, 'utf-8'), page.file);
  writeFileSync(
    join(out, 'docs', `${page.slug}.html`),
    shell({
      title: `${page.title} — SHAWZIFY`,
      description: `${page.title}: SHAWZIFY documentation.`,
      body: html,
      bodyClass: 'docs',
      depth: 1,
      activeSlug: page.slug,
    }),
  );
  rendered += 1;
}

cpSync(join(here, 'src', 'styles.css'), join(out, 'styles.css'));
cpSync(join(here, 'src', 'favicon.svg'), join(out, 'favicon.svg'));
if (existsSync(join(here, 'public'))) cpSync(join(here, 'public'), out, { recursive: true });
writeFileSync(join(out, '.nojekyll'), '');

console.log(`Built the landing page and ${rendered} documentation pages into site/dist.`);
