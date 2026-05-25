"""Visual gallery generator for the v1.4 e2e suite.

The conftest's ``pytest_sessionfinish`` hook calls :func:`generate_index`
against the run-level report dir (``docs/e2e-reports/<UTC-ts>/``). The
result is a self-contained ``index.html`` linking each spec's
checkpoint screenshots, trace zip, and recorded video — no JS deps,
no asset CDN, opens in any browser.

Layout:

::

    docs/e2e-reports/20260525T173800Z/
    ├── index.html             ← what this module writes
    ├── signup-golden-path-smoke/
    │   ├── 01-authenticated.png
    │   ├── 02-signup-form-filled.png
    │   ├── 03-confirmation.png
    │   ├── 04-dashboard.png
    │   ├── trace.zip
    │   └── video.webm
    ├── public-promo-applied-at-signup/
    │   └── ...
    ...

The generator is intentionally template-free (small inline HTML +
inline CSS) so a future operator reading this file doesn't have to
chase a separate Jinja template.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from pathlib import Path


_CSS = """
:root {
  color-scheme: light dark;
  --bg: #fafafa;
  --fg: #1a1a1a;
  --muted: #6a6a6a;
  --border: #e4e4e4;
  --accent: #2563eb;
  --code-bg: #f0f0f0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0e0e10;
    --fg: #e8e8e8;
    --muted: #9a9a9a;
    --border: #2a2a2a;
    --accent: #60a5fa;
    --code-bg: #1c1c1f;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px;
  background: var(--bg); color: var(--fg);
  max-width: 1400px; margin: 0 auto;
}
h1 { font-size: 24px; margin: 0 0 4px 0; }
.run-meta { color: var(--muted); font-size: 14px; margin-bottom: 32px; }
.run-meta code { background: var(--code-bg); padding: 2px 6px; border-radius: 3px; font-size: 13px; }
.spec {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 24px;
  background: var(--bg);
}
.spec h2 { font-size: 18px; margin: 0 0 4px 0; color: var(--accent); }
.spec h2 a { color: inherit; text-decoration: none; }
.spec h2 a:hover { text-decoration: underline; }
.spec-artefacts {
  display: flex; gap: 12px; flex-wrap: wrap;
  margin: 12px 0; font-size: 13px; color: var(--muted);
}
.spec-artefacts a {
  color: var(--accent);
  text-decoration: none;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
}
.spec-artefacts a:hover { background: var(--code-bg); }
.screenshots {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 12px;
  margin-top: 12px;
}
figure {
  margin: 0;
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
  background: var(--code-bg);
}
figure img {
  display: block;
  width: 100%;
  height: auto;
  cursor: zoom-in;
}
figcaption {
  padding: 6px 10px;
  font-size: 12px;
  color: var(--muted);
  font-family: monospace;
  border-top: 1px solid var(--border);
}
video {
  display: block;
  max-width: 720px;
  width: 100%;
  margin: 12px 0;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: black;
}
details summary { cursor: pointer; padding: 8px 0; color: var(--muted); font-size: 13px; }
details summary:hover { color: var(--fg); }
.empty { color: var(--muted); font-style: italic; }
"""


def _humanise_slug(slug: str) -> str:
    """``signup-golden-path-smoke`` → ``signup golden path smoke``."""
    return slug.replace("-", " ").replace("_", " ")


def _spec_section(spec_dir: Path) -> str:
    """Render a single spec's HTML block."""
    name = spec_dir.name
    human = _humanise_slug(name)
    screenshots = sorted(spec_dir.glob("*.png"))
    has_trace = (spec_dir / "trace.zip").is_file()
    has_video = (spec_dir / "video.webm").is_file()

    parts: list[str] = []
    parts.append('<section class="spec">')
    parts.append(
        f'<h2><a href="#{html.escape(name)}" id="{html.escape(name)}">'
        f'{html.escape(human)}</a></h2>'
    )

    parts.append('<div class="spec-artefacts">')
    parts.append(f"<span>{len(screenshots)} screenshots</span>")
    if has_trace:
        parts.append(
            f'<a href="{html.escape(name)}/trace.zip" download>'
            "trace.zip (open with: <code>playwright show-trace</code>)</a>"
        )
    if has_video:
        parts.append(
            f'<a href="{html.escape(name)}/video.webm" download>video.webm</a>'
        )
    parts.append("</div>")

    if has_video:
        parts.append(
            "<details><summary>Watch the run (video)</summary>"
            f'<video controls preload="none" src="{html.escape(name)}/video.webm"></video>'
            "</details>"
        )

    if not screenshots:
        parts.append('<p class="empty">No screenshots captured for this spec.</p>')
    else:
        parts.append('<div class="screenshots">')
        for shot in screenshots:
            rel = f"{name}/{shot.name}"
            caption = shot.stem  # e.g. "01-authenticated"
            parts.append(
                f'<figure><a href="{html.escape(rel)}" target="_blank">'
                f'<img src="{html.escape(rel)}" alt="{html.escape(caption)}" loading="lazy">'
                f"</a>"
                f"<figcaption>{html.escape(caption)}</figcaption></figure>"
            )
        parts.append("</div>")

    parts.append("</section>")
    return "\n".join(parts)


def generate_index(run_dir: Path) -> Path:
    """Walk ``run_dir`` looking for per-spec subdirs and write
    ``run_dir/index.html``. Returns the path written.

    Each subdir under ``run_dir`` that contains at least one ``.png`` is
    treated as a spec section. Subdirs without screenshots still show up
    (so a fully-failing spec with no checkpoints isn't silently hidden).
    """
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run dir not found: {run_dir}")

    spec_dirs = sorted(p for p in run_dir.iterdir() if p.is_dir())

    sections = "\n".join(_spec_section(d) for d in spec_dirs)
    # Artefact metadata only — never a state machine input. Wall-clock
    # via stdlib is correct here; bss_clock is for domain logic.
    when = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")  # noqa: bss-clock
    total_screenshots = sum(len(list(d.glob("*.png"))) for d in spec_dirs)

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>bss-cli e2e run — {html.escape(run_dir.name)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>bss-cli e2e run</h1>
<p class="run-meta">
  Run id: <code>{html.escape(run_dir.name)}</code> ·
  Generated: {html.escape(when)} ·
  Specs: {len(spec_dirs)} ·
  Screenshots: {total_screenshots}
</p>
{sections if sections else '<p class="empty">No specs found in this run directory.</p>'}
</body>
</html>
"""
    out = run_dir / "index.html"
    out.write_text(body, encoding="utf-8")
    return out
