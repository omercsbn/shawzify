# Releasing

For maintainers. Everything here is scripted or one command; the point of the
list is that nothing is remembered wrong at the moment it matters.

## Going public the first time

The repository starts private. When it is ready to be seen:

```powershell
gh repo edit omercsbn/shawzify --visibility public --accept-visibility-change-consequences

# Turn the site on. It is deliberately off while the repository is private,
# because a Pages site is public even when its repository is not.
gh api repos/omercsbn/shawzify/pages -X POST -f build_type=workflow
gh workflow enable Pages
gh workflow run Pages
```

Then check <https://omercsbn.github.io/shawzify/> and enable Discussions in the
repository settings — the issue template config links to it.

## Cutting a release

1. **Decide the version.** Semantic versioning: a change that alters an
   arrangement for identical input is at least a minor bump, and the relevant
   algorithm version in `engine/shawzify_engine/version.py` must move with it.

2. **Bump it in all four places** — they are checked against each other by
   `scripts/version.ps1`:

   ```powershell
   scripts\version.ps1 0.2.0
   ```

   That writes `engine/pyproject.toml`, `apps/desktop/package.json`,
   `apps/desktop/src-tauri/tauri.conf.json` and
   `apps/desktop/src-tauri/Cargo.toml`, and tells you what it changed.

3. **Write the changelog.** Move everything from `## [Unreleased]` into a new
   version section in `CHANGELOG.md`, and add the comparison links at the
   bottom. Write it for someone deciding whether to update.

4. **Verify locally**, because the workflow will run the same suites and a
   failure there wastes ten minutes:

   ```powershell
   scripts\test.ps1
   scripts\build.ps1 -SkipTests     # confirms the installer actually bundles
   ```

5. **Commit, tag, push.**

   ```powershell
   git commit -am "Release 0.2.0"
   git tag -a v0.2.0 -m "SHAWZIFY 0.2.0"
   git push && git push --tags
   ```

   The `Release` workflow takes it from there: it runs every suite, builds the
   NSIS installer, computes its SHA-256, and publishes a GitHub release with
   the notes from `.github/release-notes.md.tpl`.

6. **Check the result.** Download the artefact from the release page, verify
   the hash it published, and install it once on a machine that has never run
   SHAWZIFY — that is the only way to catch "works on the build machine".

## If the release workflow fails

* **Tests failed.** Fix, tag again with a new patch version. Do not delete and
  re-push a tag that people may already have.
* **No installer was produced.** Almost always the frontend build: `npm run
  tauri:build` needs `apps/desktop/dist`, which `beforeBuildCommand` creates.
* **You need to re-run against the same tag.** `gh workflow run Release -f
  tag=v0.2.0` — it uploads with `--clobber` and rewrites the notes.

## What the installer does and does not contain

It contains the desktop shell and the built interface. It does **not** contain
the Python engine: with PyTorch, Demucs and Basic Pitch that would be several
gigabytes, and the model weights are downloaded on first use anyway. Users run
`scripts\setup.ps1` once, and the shell finds `engine/.venv` on its own.

`scripts\build.ps1 -BundlePython` produces a PyInstaller build of the engine for
experimenting with a self-contained bundle. The shell does not look for it yet —
wiring that up is tracked as future work.
