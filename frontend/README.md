# Nchito frontend

React 19 + Vite + TypeScript (strict), Tailwind v4, shadcn/ui (owned source), TanStack Router and Query,
react-hook-form + zod, dnd-kit, cmdk, Motion, Sonner, Lucide, Fontsource. Spec: `../docs/DESIGN.md`
(section 10). Visual reference: `../design/ui-preview.html`.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on :5173, `/api` proxied to `http://localhost:8000` |
| `npm run dev:mock` | Dev server with the built-in MSW mock backend (no backend needed). Sign in as `owner@example.com` / `demo-password`. Add `?mock=fresh` (first-run setup), `?mock=signed-out` or `?mock=signed-in` to any URL to reset the mock |
| `npm run build` | Type-check and build to `dist/` (PWA service worker included) |
| `npm run typecheck` | `tsc` only |
| `npm run lint` | ESLint, then the no-literal-colour check |
| `npm run check:themes` | Contrast check over the theme JSON (4.5:1 text, 7:1 for High contrast) |
| `npm test` | Vitest + Testing Library (jsdom, MSW in node) |
| `npm run format` | Prettier |
| `npm run icons` | Re-render the PWA PNG icons from `public/icon*.svg` |
| `npm run shots` | Screenshots of key screens against a running `dev:mock` server |

## Structure

```
src/
  app/            providers, router, route guard, shell (sidebar, top bar, palette, Add job, Autopilot switch)
  routes/         the route tree (code-based TanStack Router) - one place to see every URL
  features/<area> screens: today, matches, applications, jobs, studio, autopilot, kit, campaigns,
                  sources, insights, settings, onboarding, auth, dev (component gallery)
  components/     shared components (ScoreRing, Chip/FilterChip, StagePill, SeverityItem, KanbanBoard, ...)
  components/ui/  shadcn/ui source (restyled to the mockup; edit freely, it is ours)
  themes/         theme engine, provider, ThemeScope, built-in theme JSON, fonts, accents
  lib/api/        typed API layer (client, endpoints, hand-written schema = the swap seam)
  mocks/          MSW handlers, in-memory db, fictional fixtures
  test/           Vitest setup, MSW server, render helpers
scripts/          check-colours, check-themes, make-icons, screenshots
```

## Adding a screen (feature agents)

1. Write the page in `src/features/<area>/<name>-page.tsx`. Wrap content in `<View>` (or `<View flush>` for
   full-height layouts such as `SplitView`). Use the shared components and theme utilities only.
2. Add a route in `src/routes/index.tsx` under `shellRoute` with `staticData: { title }` (the top bar and
   the document title read it), and add it to `routeTree`.
3. If it belongs in navigation, add it to `src/app/shell/nav.ts`; the sidebar, phone tabs and command
   palette all read that file. Paths are type-checked against the router.
4. API calls: add the endpoint's types to `src/lib/api/schema.ts`, a function and query options to
   `src/lib/api/endpoints.ts`, and a mock handler to `src/mocks/handlers.ts` so `dev:mock` and tests work.
5. Test what you changed (`npx vitest run src/features/<area>`).

**Generated types:** when the backend's OpenAPI exists, run
`npx openapi-typescript http://localhost:8000/openapi.json -o src/lib/api/schema.gen.ts` and change the
`paths` re-export in `src/lib/api/types.ts`. Endpoints marked PENDING CONTRACT (`/api/jobs/capture`,
`/api/autopilot`) are mocked only; the UI shows a toast when the real backend returns 404.

## No literal colours

Components use tokens only (DESIGN 10.4). `npm run lint` fails on hex, `rgb()/hsl()/oklch()`-style
functions and Tailwind palette classes (`bg-red-500`, `text-white`) anywhere in `src/` outside
`src/themes/`. Use:

- shadcn names: `bg-background`, `text-foreground`, `bg-primary`, `text-muted-foreground`, `border-border`
- extended tokens: `bg-sunken`, `bg-surface`, `bg-surface-2`, `border-border-strong`, `text-faint`,
  `bg-primary-soft`, `text-primary-ink`, `bg-highlight` / `text-highlight-ink` / `bg-highlight-soft`
  (the theme's accent; shadcn's `accent` is the quiet hover fill), `good|warn|danger|info` and their
  `-soft`, `score-low|mid|high`, `bg-overlay`, `bg-paper` / `text-paper-ink` (documents, always white)
- utilities: `eyebrow` (label style), `num` (figures), `heading`, `elev` (the one raised surface),
  `panel`, `pop-surface`, `row-pad` (density-aware row padding), `field-focus`
- arbitrary values may reference tokens: `shadow-[0_0_0_2px_var(--t-ring)]`

A line that genuinely is not a colour (e.g. an attribute selector matching a library default) can opt
out with a comment `colour-lint-ignore: <reason>` on that line or the one above.

## Themes

A theme is JSON (`src/themes/builtin/*.json`, schema in `src/themes/schema.ts`):
`{id, name, builtin, description?, fonts:{display, body, mono}, radius, density, light, dark, chart, score}`.
`light`/`dark` map token names (the mockup's CSS variables without `--`) to values; colour tokens are
required, character tokens (`data-font`, `label-font`, `label-case`, `space-k`, `shadow-pop`,
`panel-border`, `elev-top`, `elev-top-color`, `score-*`, `chart-1..5`) are optional with defaults.
Top-level `chart` and `score` are the light-mode values and the fallback when a mode omits them.

The engine (`themes/engine.ts`) writes every token to the root as `--t-<name>`; `index.css` maps them
onto shadcn's variables and Tailwind utilities. `ThemeProvider` applies the active theme plus the
owner's appearance (mode, accent, density, radius, text size, reduced motion), persists to
`/api/settings/appearance`, and caches to localStorage; an inline script in `index.html` repaints from
that cache before any JS loads, so there is no flash. `<ThemeScope theme mode>` renders any subtree in
another theme (gallery previews). Fonts load lazily from Fontsource when a theme is applied or previewed.

**Add a built-in theme:** copy a JSON file in `src/themes/builtin/`, change the values, add it to
`BUILTIN_THEMES` in `src/themes/index.ts`, make sure its font families are in `src/themes/fonts.ts`, and
run `npm run check:themes`. Custom themes created by the owner arrive from `/api/themes` and need no code.

Dev-only component gallery: `/dev/components` (every shared component in every theme).
