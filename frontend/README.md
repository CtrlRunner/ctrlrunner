# pyrunner frontend

React + Vite source for BOTH browser frontends, modeled behaviorally on
Playwright's html-reporter / UI Mode (own CSS tokens and icons -- no
Playwright code or assets are copied):

- the static HTML test report (`src/report/`)
- UI Mode (`src/ui/`)

Each builds to **one self-contained file** with all JS/CSS inlined:

    pyrunner/reporting/_static/report/index.html
    pyrunner/ui/_static/ui/ui.html

Both files are **committed to git** so the Python package and wheel need
no Node toolchain. `render_html()` (pyrunner/reporting/html_report.py)
replaces the report page's `<!--PYRUNNER_DATA-->` marker with the
`window.__PYRUNNER_REPORT__ = {...}` payload; `render_ui_html()`
(pyrunner/ui/ui_frontend.py) replaces the `__PYRUNNER_SESSION_TOKEN__`
placeholder in the UI page (which must appear there exactly once -- the
Python side replaces every occurrence).

## Workflow

```bash
cd frontend
npm install        # once
npm run dev        # report dev server with HMR (renders src/report/devFixture.ts)
npm run dev:ui     # UI Mode dev server; proxies /api to a running
                   #   `python -m pyrunner ui` (set PYRUNNER_UI_PORT, pass ?token=)
npm run build      # typecheck + lint + build both bundles
npm run lint       # biome check
npm run format     # biome check --write
```

**After changing anything under `src/`, run `npm run build` and commit
the regenerated bundles together with the source change** --
`tests/test_html_report.py::PrebuiltPageTests` guards the assets'
existence and single-file invariants, but cannot detect a stale build.

## Layout

- `src/shared/` -- theme, design tokens, icons, status icon, chip,
  types mirroring `_result_to_dict()`. Written to be reusable by a
  future React UI Mode frontend.
- `src/report/` -- the report app: hash router (`links.tsx`), filter
  query language (`filter.ts`: `s:`, `@tag`, `g:dim=value`, `case:`,
  `!negation`, quoted phrases), label pills (`labels.tsx`), header +
  stats nav, grouped test list + per-dimension summary table, test
  detail page, `testToMarkdown()` for the MD / Copy prompt buttons.

The report data contract is owned by the Python side
(`pyrunner/reporting/html_report.py::_result_to_dict`); keep
`src/shared/types.ts` in sync with it.
