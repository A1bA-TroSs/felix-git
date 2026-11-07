# Evidence-first repository portfolios

Use this path when the request concerns a portfolio, README or repository page. The result should help a reader understand the product, inspect it and judge the engineering. Start with an ordinary branch. History rewriting, attribution changes, branch deletion, settings changes and deployment each require their own scope in the user's request.

## Discover what a reader can actually try

Inspect the current README, manifests, routes, screenshots, tests and deployment links. Identify the intended reader and the problem the product solves. Try an available public demo when authorized, without submitting personal data or creating shared records. Record the route and the behavior observed. If a flow requires sign-in or a backend you cannot verify, keep that limit visible.

Treat source, tests and runtime observations as different evidence. A route in source proves an implementation exists; a passing test covers its exercised contract; an observed demo proves that particular flow and environment. None alone establishes hosted reliability, production capacity or user adoption.

## Keep a claim ledger

Before writing promotional copy, record each meaningful feature claim with:

| Field | What to record |
|---|---|
| Claim | The exact reader-facing statement |
| Status | Implemented, tested locally, observed in demo, verified hosted, or planned |
| Evidence | A repository path, test result, observed route or retained capture |
| Limit | Missing persistence, fixture data, refresh resets, unavailable delivery or another relevant boundary |

Use the existing `claims.json` format from `promotion.md` when running `check_readme.py`. Keep this richer status ledger alongside it in the review; the checker verifies file references, not the truth of prose or a live service.

For example, a scheduling preview might let sample participants propose a time and agree separately. Describe that observed interaction, then state that the preview uses sample data and resets on refresh. Do not turn it into a claim that hosted authentication, persistence, notifications or calendar integration work unless those flows were separately verified.

## Design a short path from promise to proof

1. Open with the product name, a concrete one-sentence promise and a working demo link when one exists.
2. Place a real product capture near the top. Use a static image when it explains the flow; use motion only when a state change is necessary to understand it. Generated artwork can decorate the page but cannot serve as product evidence.
3. Present a few meaningful capabilities, each supported by the ledger. Put decision-changing limits beside the relevant capability or demo link.
4. Explain one or two consequential engineering decisions and their tradeoffs. Link to deeper architecture and verification records rather than placing the entire implementation diary in the README.
5. Give a reproducible quick start, required configuration names without secret values, and checks that were actually run. Mark untested commands clearly.
6. End with the current roadmap, license and appropriate contribution information. Preserve genuine project and contributor attribution.

Prefer the project's existing identity, typography and color choices. Avoid a badge wall, unsupported performance numbers, placeholder screenshots and decorative sections that push the demo out of view. Do not invent testimonials, users, benchmarks or maturity labels.

## Verify the page and submit the exact change

Run `check_readme.py` against the selected README and evidence map, then inspect the rendered Markdown on wide and narrow surfaces. Check image paths, link destinations, dark/light readability, alternative text and the first screen's reading order. If GitHub rendering is unavailable, state which substitute was checked and leave that verification open.

Review the final diff and scan new text/assets before publication. Verify the exact repository, account, branch, base and head. An authorized PR request permits opening that PR; it does not permit merging it or rewriting the target's shared history. Report the PR URL, checked head commit, evidence and remaining limits.
