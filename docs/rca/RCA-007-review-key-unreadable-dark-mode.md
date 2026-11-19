# RCA-007: Proposed Answer Unreadable in Dark Mode

- **Severity:** major (the tutor cannot check the answer key)
- **Detected:** 2026-11-18, T071 Gate C tutor acceptance, production
  `v2026.11.18-1`
- **Status:** fixed in M5

## Symptoms

In the tutor's question review, with the browser in dark mode, the
proposed correct option ("✓ Respuesta propuesta") showed near-white text
on a pale green background and could not be read. The other options and
light mode were fine. The defect affected the individual review and the
expanded bulk review.

## 5 Whys

1. Why unreadable? The text was the dark theme's `--text` (`#e8ecf1`) on
   a fixed `#e9f7ee` background, about 1.1:1 contrast.
2. Why a fixed background? The T068 rule `.review-options li.review-key`
   set literal colours instead of the theme tokens the rest of
   `styles.css` uses.
3. Why no text colour? The rule was written and checked in light mode
   only, where the inherited dark text happens to read well.
4. Why was it not caught? T068 to T071 screenshots and browser tests ran
   in the default (light) scheme; no test checks contrast in dark mode.
5. Why does that matter now? The tutor works in dark mode, so it surfaced
   during the first real production review session.

## Fix

- `.review-options li.review-key` uses `var(--accent)`,
  `var(--accent-soft)` and `var(--text)` only, with a thicker accent
  border, a 6px side bar and bold text for emphasis.
- The base `.review-options li` border uses `var(--border)`.
- Contrast for the proposed answer is about 14:1 in light mode and about
  12:1 in dark mode (WCAG AA needs 4.5:1).

## Prevention

- Tests in `tests/app/test_review_key_contrast.py`:
  - the rule uses theme tokens and has no literal colours;
  - its text meets 4.5:1 in both schemes;
  - its border meets 3:1 against the surface in both schemes.
- Guard RCA-007 in `docs/rca/regression-guards.yaml`.
- Lesson: a highlight that sets a background must take its colours from
  the theme tokens and be checked in both colour schemes.
