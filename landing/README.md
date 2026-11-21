# SCOP landing page v0.1

An original SCOP composition built around the supplied astronaut contemplating Earth reference, a graphite background, silver highlights, deep navy supporting surfaces and an open geometric wordmark. The page distinguishes the current public-PR review MVP from the planned ecosystem. Source copy and the hero follow the user brief. The supplied README is visual guidance, with the user's request controlling scope.

## Preview and real signup storage

From the repository root on Linux or Windows with WSL and Python 3.12:

```sh
python3.12 -B -m server.scop_landing
# Open http://127.0.0.1:8780
```

Without a signup directory the page loads with collection disabled. To test persistence, create a dedicated directory outside all Git worktrees. Use synthetic information during development.

```sh
mkdir -m 700 "$HOME/scop-signups"
python3.12 -B -m server.scop_landing --signup-dir "$HOME/scop-signups"
```

A successful POST writes a UUID-named `.signup.json` file, mode 0600, containing email, coding tool, challenge, explicit consent, consent version and server UTC timestamp. HTTP 201 and the success message follow the completed write. There is no confirmation email. Repeated submissions create separate records, so a retry after a lost response can duplicate a signup. Storage failures and unavailable collection show errors. Capacity is 10,000 files. The operator can inspect or remove records directly in the private directory. Keep it separate from measurement records and never add it to Git, screenshots, issue bodies or PR descriptions.

The runtime uses Python's standard library. It reuses the existing private-directory and atomic-write helpers while leaving the v0.9 modules and contracts unchanged. Store ownership, mode, symlink and Git-worktree checks still apply. The HTTP adapter has its own loopback port, fixed assets, strict Host/Origin/session checks, CSP, no CORS, bounded 8 KiB JSON, socket inactivity timeout and redacted errors. Single-process handling serializes writes. No subprocesses, remote integrations or user-controlled file paths are exposed. Input text is never injected into HTML. Email syntax validation does not establish ownership or deliverability.

## Image and visual implementation

`assets/hero.webp` is a faithful image-tool adaptation of the astronaut inline reference (1672 × 941), encoded as WebP. The inline attachment was visible but had no downloadable original path, so the adapted asset should be visually reviewed against the supplied image. Its aspect ratio is preserved with CSS, and positioning adapts to the viewport. The desktop gradient creates text space to the left while keeping Earth and the astronaut visible. On mobile a 360px image region sits above the text to avoid overlap. No external fonts, analytics, stock claims, partner logos or ClearPath branding are included. Confirm rights to the supplied image before public publication.

The hero image is preloaded and served locally. On desktop, requestAnimationFrame applies bounded scroll transforms to the artwork, ambient light and content. The artwork keeps the astronaut, Earth and stars together, with a separate ambient lighting plane providing the additional depth. There is no extracted character mesh. Desktop mouse movement adds at most three horizontal and two vertical pixels of microparallax. A metallic sheen moves across focused or hovered primary buttons. Scroll transforms and the sheen are disabled for reduced motion and widths below 1001 px. The UI includes a skip link, visible keyboard focus, field labels, inline errors, consent and live submission feedback.

## Publication plan

This PR supplies a public-facing page with a functional local persistence adapter. Publication requires a separate authorized hosting step.

1. Choose the production domain and hosting provider. Serve the landing assets over HTTPS with a same-origin signup API. Static hosting alone leaves this form unconfigured and disabled.
2. Adapt the preview's strict origin/token boundary to the selected HTTPS origin and production server. Keep the Workspace local. Python's preview HTTP server is intended for local testing.
3. Configure private durable signup storage outside the source tree, least-privilege service access, backup/deletion handling, request rate limits and abuse protection. The preview has a file cap and request limits but no distributed abuse protection or email ownership verification.
4. Supply the operator's contact, deletion request channel and retention period, then update the privacy text before collecting public signups. Decide separately whether confirmation emails are wanted. Keep credentials in the hosting secret store.
5. Verify end-to-end persistence, rejection paths, HTTPS headers and availability using synthetic data on the selected host, then request publication approval.

No hosting account, domain, mail provider or retention policy was assumed. No public deployment was performed.

## Automated validation

```sh
python -m pytest -q
npm ci --ignore-scripts --prefix tests/ui
tests/ui/node_modules/.bin/playwright install --with-deps chromium
node --test tests/ui/*.test.cjs
```

For an existing browser use `SCOP_CHROMIUM=/usr/bin/chromium`; set `PYTHON` to your pytest-equipped interpreter for browser fixtures. Browser tests use disposable private stores and synthetic contact data. They exercise real writes, consent, validation, errors, disabled collection, keyboard focus and horizontal layout at 1440, 1024, 768 and 390 px. Screenshots are written to `/tmp/scop-landing-{desktop,tablet,mobile}.png`. Existing Workspace browser tests remain included. Required CI runs both suites.
