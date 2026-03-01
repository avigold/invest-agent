# PRD 5.6 — Dashboard Country Card Watermarks

**Product**: investagent.app
**Version**: 5.6 (incremental, builds on PRD 5.5)
**Date**: 2026-03-01
**Status**: Shelved
**Milestone**: 5

---

## 1. What this PRD covers

Add accurate SVG outlines of each country's land mass as decorative watermarks on the "Top Countries" cards on the dashboard, giving instant visual identity to each card.

## 2. Problem statement

The top countries cards on the dashboard are plain text — rank, name, and score. There is no visual differentiation between countries. Users must read the name to identify which country a card represents.

## 3. Solution

Use the `world-map-country-shapes` npm package (MIT license, 211 countries, SVG path data keyed by ISO2 code) to render accurate country outlines as stroke-only line drawings at low opacity, positioned as watermarks on the right side of each top countries card.

### 3.1 Data source

`world-map-country-shapes` provides an array of `{ id, shape }` objects where `id` is the ISO2 country code and `shape` is an SVG path `d` attribute using Robinson Projection coordinates.

### 3.2 Rendering

- Stroke-only (no fill) for a line-drawing look
- Low opacity (~6-8%) so watermarks sit behind text
- Each path gets a computed viewBox from its bounding box for proper sizing and centering
- Positioned `absolute` to the right of each card, vertically centered
- `pointer-events-none` to not interfere with card clicks

### 3.3 Card layout

Each card uses `relative overflow-hidden` to contain the watermark within card bounds.

## 4. Files changed

| File | Action |
|---|---|
| `web/package.json` | Modify — add `world-map-country-shapes` |
| `web/src/components/CountryOutline.tsx` | Rewrite — use package data, stroke-only rendering |
| `web/src/pages/Dashboard.tsx` | Modify — render watermark on top countries cards |

## 5. Acceptance criteria

- [x] Accurate country outlines from `world-map-country-shapes` package
- [x] Stroke-only rendering (line drawing, not filled)
- [x] Top countries cards show recognizable outlines as watermarks
- [x] Watermarks are subtle, positioned right, vertically centered
- [x] Watermarks don't interfere with text readability or card click behavior
- [x] Watermarks clip to card bounds (no overflow)
- [x] TypeScript clean, build succeeds
