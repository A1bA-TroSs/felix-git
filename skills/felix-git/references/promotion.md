# Promotion pipeline

Goal: a stranger understands in ten seconds what this is, why it beats what they do today, and how to try it, and nothing on the page turns out false when they check. Developers tend to discount copy and trust things they can verify, so proof does the selling and adjectives do none.

## 1. Product inventory: what actually exists

Read the code, tests, docs, CI and any demo. Run it only if the user allowed that (see SKILL.md). Check existing claims against the code, since READMEs go stale: a test count or feature list may be wrong. Write `inventory.md` and later `buy-factors.md` in the working directory, outside the clone: each capability, the file or test proving it, and its state: works, partial, or planned. Planned features never appear as features. If the project can't be run here, say so.

## 2. Buy factors: why someone would choose it

If the project honestly loses to the obvious alternative, say so in the review and position it for who it does serve, such as people learning from the code.

A buy factor is the reason a specific person picks this over what they use now. Work through April Dunford's positioning order, because each answer depends on the last:

1. **Alternatives.** What would the reader do without this? Often it's the status quo (the mail app they use today, a spreadsheet, doing it by hand), not a rival; that needs no competitor source, only a plain description, and the README line names it. Search for real alternatives and how people talk about the problem: issues, forums, reviews. Keep each URL and date.
2. **Differentiating capabilities.** From the inventory, what can this do that those can't?
3. **Value.** What does that capability get the reader? "Runs on-device" is a capability; "your mail never leaves your Mac" is value.
4. **Who cares most.** The person for whom that value matters most. Name them plainly; don't say "everyone".
5. **Category.** The familiar frame that makes the rest obvious: "an open-source AirDrop alternative" explains LocalSend in five words.

Write `buy-factors.md`, keeping 3 at most. Each needs a capability with evidence, the alternative it beats, and a source for that alternative (a status quo needs none, as above). A claim about alternatives in the plural needs more than one source; with one, word it as that one example. Drop any that fails; a shorter page beats an unproven claim. If you find no real advantage over an alternative, tell the user rather than dressing it up.

## 3. Choose the page shape

Copy the shape of a page whose reader matches, not its look. Observed in well-known repositories, November 2026:

| Project kind | Example | What the top of the page does |
|---|---|---|
| Speed or measurable tool | uv | One line, then a benchmark chart with its setup stated, then Highlights linking to the proof |
| App with a UI | Immich, Excalidraw, LocalSend | Logo or cover, one line, a real product screenshot, links to demo and docs |
| Already famous | Ollama, shadcn/ui | Name, one line, install. Fame replaces the pitch, so don't copy this for an unknown project |
| Agent skill or plugin | gstack, Superpowers, VibeWise | One line, who it's for, quick start, a walkthrough of what using it feels like. Often no images at all |
| "Alternative to X" | LocalSend, RustDesk | Says so in the first sentence |

**Title banner.** AFFiNE, Excalidraw, Jan, Tauri, Supabase and Hoppscotch open with a wide banner instead of a plain heading. Put the image inside the `<h1>`, with the project name as its alt text, so the page still has a real title for screen readers and search, and the name isn't printed twice:

```html
<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/readme/banner-dark.png">
    <img alt="Project Name" src="docs/readme/banner-light.png" width="100%">
  </picture>
</h1>
```

A banner is 1280x320 at 2x: the existing logo or the name, one line of value, and a visual from the project itself. The one-line description and the link row go straight below it.

**Edges.** A filled rectangle shows its border against GitHub's background (#ffffff in light mode, #0d1117 in dark), and in one of the two themes it reads as a pasted box. Pick one treatment and say which in the review:
- *Floating*: leave the background transparent (`render.py --transparent`, nothing painted on `html` or `body`) and render a light and a dark variant, so the banner sits on the page itself. Biome, uv, Turborepo, Excalidraw and Hoppscotch do this with `<picture>` variants.
- *Matched*: paint each variant exactly #ffffff or #0d1117, so the edge disappears in its own theme. This works when the art needs a solid ground.
- *Framed on purpose*: a full-bleed artwork with rounded corners and margin around it, as AFFiNE and Jan do. Choose this only when the artwork carries the page.
- Fade art into the background with a mask or gradient instead of cropping it at a hard line. Check both variants composited on #ffffff and #0d1117 before using them.

**No house style.** Every repo this skill touches must not come out looking the same, or the result becomes one more template people learn to skip. Derive the banner from the project: its own logo, its app's real colours (read the stylesheet or theme tokens), its domain's imagery, its real screenshot. Vary the composition (left-aligned, centred, wordmark only, capture-led, illustration-led) and the type to fit it. Never reuse felix-git's own banner: three git lines merging, a dark navy ground, green and amber. If two candidates are possible, render both and let the owner pick at the review.

Default order for an unknown project: banner (or name), one-line category and value, a link row of in-page anchors when there is no website or docs, hero image, 3 buy factors with proof, quick start, how it works, status and limits, contributing, license. Lists and images are common in popular READMEs and studies link usage, install, license and image sections to more stars, but that is correlation, so use them for clarity, not as a formula. Badges only when they report something true and live, such as CI status or a release; a badge wall adds nothing.

## 4. Images: real product first, generated art only as decoration

Choose by what the reader needs to believe, in this order:

1. **Real screenshot or recording.** Reuse one in the repo if it's clean and shows the current product. If it's older, caption it with what it predates, or leave it out. Otherwise, if the user allowed running the app, capture one with whatever browser or simulator tool the session has. Use demo data, never the owner's real data, and check every frame for private content.
   - Many apps call a hardcoded local backend (look for `127.0.0.1:<port>` or `localhost` in the built bundle), and the owner's real backend may be running on that port with their real data. Before the first capture, route every request the page makes: send the app's API host to a demo stub (the repo's own fixture or stub server if it has one, else one you write with demo data) and abort every other host. In Playwright that is `context.route('**/*', ...)`. Checking that nothing listens on the port is not enough, because the owner can start it mid-run.
   - Motion sells an app better than a still: capture 10 to 20 seconds of entry, key action and result as frames with their times in `frames.json`, then `scripts/animate.py frames/ docs/readme/hero.webp`. GitHub plays an animated WebP or GIF inline, but not an mp4 committed to the repo. Keep it under 10 MB and also keep one still PNG for the social card.
2. **Chart from measured data.** Only numbers you measured or the repo already records, with the setup stated next to it.
3. **Real terminal or session output**, rendered. Text from an actual run, not typed from memory.
4. **Diagram of how it works**, from the actual architecture. Skills and CLIs often have nothing else to show.
5. **Banner, hero or social card**: name, one line, and one of the above. Type does the work.

**Generated artwork** is for decoration only: a banner background, an illustration of an idea, a texture or a mascot the user asked for. Pick the first tool the session actually has:

1. **Codex image generation**, when the session is linked to Codex: an MCP tool such as `codex_image`, or a CLI bridge to Codex's built-in image generation.
2. **Another connected image generation tool**, such as a design tool's MCP `generate_image`. A tool that charges per image needs the user's yes on the cost first.
3. **None**: compose the image in HTML and render it as below. That is always enough.

Generate artwork without any text, since image models garble letters, then put the name and line on top in HTML and render that, so the type stays sharp and spelled right. Keep each prompt and the tool's name in the working directory and list them in the review. Look at every generated image before using it. It never shows the product's screens, a real person, another company's logo or anything a reader could mistake for proof.

Write each as a self-contained HTML or SVG file with no scripts (the renderer turns them off, and sets `data-theme` on `<html>`) in `docs/readme/` (not a folder the app packager ships; check its config), then render with `scripts/render.py hero.html hero.png`. PNG is the published format because GitHub README SVGs can't load web fonts and render differently per machine. The script sets `data-theme` on the root element, so write colours under `[data-theme=dark]` rather than a media query, and keep the file self-contained because network is blocked. Render both themes, the second with `--dark`, and use `<picture>` when the image has a background:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/readme/hero-dark.png">
  <img alt="What the image shows, in words" src="docs/readme/hero.png">
</picture>
```

Hard lines, because a fake product image is the fastest way to lose a reader's trust:
- Never draw or generate an imitation of the product's UI and present it as the product. If the app can't be run here, use a diagram labelled as one, and tell the user a real screenshot would be stronger.
- No invented users, logos of companies, testimonials, star counts or metrics.
- Look at every rendered PNG before using it: clipped text and overlap are common. Keep files small; the social card must be under 1 MB at 1280x640, so render it with `--scale 1`.
- No generated logo unless the user asks; use the project's own logo, or a plain wordmark.

## 5. Write the README

- First line matches the GitHub description, under 120 characters, states category and value.
- Every line a stranger could check goes in `claims.json` with its evidence: `[{"claim": "...", "evidence": ["src/x.py", "https://...", "cmd: pytest"], "how": "what in that evidence shows the claim"}]`.
- Specific beats grand: "Finds 3 of 4 duplicate invoices in the sample set" over "powerful detection". Numbers appear only where a reader is checking something.
- Quick start comes from commands you ran from a clean checkout, or, if you couldn't or weren't allowed to, from the project's manifests and scripts and marked untested in the review.
- State limits and status plainly: platforms, what's unfinished, what it's not for. It makes the rest believable and costs little.
- Write as the project, not as an ad. No exclamation marks, no superlatives.
- Keep English as the page language unless the audience is clearly elsewhere; ask nothing, note the choice in the review.

Run `scripts/check_readme.py <repo> --claims claims.json` and fix every failure. Warnings need a reason in the review. The script checks structure only, so then reopen each piece of evidence and confirm it really shows its claim; cut any claim it doesn't.

## Sources behind this guide

- Title banners and edge treatments: https://github.com/biomejs/biome , https://github.com/astral-sh/uv , https://github.com/vercel/turborepo , https://github.com/excalidraw/excalidraw , https://github.com/toeverything/AFFiNE , https://github.com/janhq/jan , https://github.com/tauri-apps/tauri , https://github.com/supabase/supabase , https://github.com/hoppscotch/hoppscotch
- Page shapes: https://github.com/astral-sh/uv , https://github.com/immich-app/immich , https://github.com/excalidraw/excalidraw , https://github.com/localsend/localsend , https://github.com/ollama/ollama , https://github.com/shadcn-ui/ui , https://github.com/rustdesk/rustdesk , https://github.com/obra/superpowers
- Dunford's positioning order: https://businessofsoftware.org/events/bos-europe-2026/differentiated-value-the-hardest-and-most-important-problem-in-positioning
- README content and popularity (correlation): https://arxiv.org/abs/2206.10772 and https://enoei.github.io/papers/liu2022readme.pdf
- Section order: https://github.com/RichardLitt/standard-readme/blob/main/spec.md
- Social preview size: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/customizing-your-repositorys-social-media-preview
- Developer distrust of hype is mostly vendor-blog opinion, not research: https://instruqt.com/blog/why-developers-dont-trust-marketing-and-what-you-can-do-about-it
