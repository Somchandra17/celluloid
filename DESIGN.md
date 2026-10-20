# Celluloid — Som's terminal / darkroom

This studio adapts Som Chandra's portfolio reference and its July 2026 addendum.
The addendum takes precedence over older loader/gating descriptions. The product
is a working video tool, so it keeps the source/settings/preview layout and
applies the portfolio's visual language without copying portfolio-only sections.

## Foundation

`dist/tokens.css` owns the ink ramp, terminal green, sakura pink, paper, typography,
grain, motion timing and Canvas chrome colors. UI styles and JavaScript reference
those tokens. Video/demo palette colors and authored SVG assets are content,
not interface tokens. `dist/theme.js` reads the Canvas tokens and manages the
visual world. The theme never modifies exported footage colors.

- Ink ground: `ink-900`; raised surfaces: `ink-850` / `ink-800`.
- Primary/secondary text: `ink-100` / `ink-200` / `ink-300`.
- Space Grotesk is the human voice; Geist Mono is the machine voice.
- Both fonts are self-hosted variable WOFF2 under their included OFL licenses.
- Sharp corners throughout; 1px rules; hard paper-offset hover shadows.
- Static SVG grain and a low-strength vignette are pointer-transparent.

## The two worlds

**Terminal / nerdy:** green at rest, compact rhythm, mono metadata, quiet static
scanlines on the document titlebar, a status strip and command-oriented details.

**Darkroom / creative:** sakura pink, stronger grain, larger type, wider gutters,
an angled print/export motif and a restrained develop-in transition.

The world switch is independent of file/webcam source and affects presentation
only. Preference storage is optional; if storage fails, the site remains usable.
The pre-paint preference script changes theme only. It never hides static content
or blocks the studio behind a loader.

## Motion

The actual cell animation is the focal movement. Hover movement uses transform
and a hard shadow. Darkroom's develop transition animates opacity/transform;
there are no moving blend layers, blur animations, neon borders or parallax.
The grain itself is static. Reduced motion disables decorative transitions and
animations and starts the sample paused. There is no intro gate or artificial
loading delay. Real conversion has a progress indicator and cancellation.

## Layout and mobile

Desktop: header/world switch → one display heading → source/settings column +
spreadsheet workspace → export and terminal access → author/source footer.
At tablet widths the studio stacks. Source controls remain above the preview;
the playback timeline can shrink without forcing horizontal overflow. Narrow
headers wrap and dialogs fit within 92vw. Camera and export controls stay text
labeled. Keyboard focus uses the active accent; theme controls expose pressed
state. The sample and source content are present in initial HTML.

## Deliberate omissions

The cosmic scene, portfolio galleries, Spotify, two-click navigation and long
intro belong to the portfolio's home page, not this task-focused tool. The
signature is the ink/paper/terminal/sketchbook material language and restrained
human copy. The footer links back to [somm.tf](https://somm.tf).
