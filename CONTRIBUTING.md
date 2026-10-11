# Contributing — branch model, PR gate and release flow

The repository runs a three-tier branch model. Every change reaches `main` through a reviewed pull request — never a direct push.

## Branches

| Branch | Role | What lands there |
| --- | --- | --- |
| `main` | **prod** — always releasable, tagged versions only | Promotion PRs from `test`, hotfix PRs. Branch protection requires the CI checks (`ci`, `python`, `docker`). |
| `test` | **test/QA** — integration & acceptance before prod | Promotion PRs from `develop`. |
| `develop` | **dev** — integration of ongoing work | Feature PRs. |

## The flow

1. **Feature work**: cut `feature/<slug>` from `develop`, open a PR **into `develop`**.
2. **Promotion**: `develop` → `test` → `main`, one PR per hop.
3. **Hotfix**: cut `hotfix/<slug>` from `main`, PR **into `main`**, then bring `main` back into `develop` and `test` via PRs as well.

Every merge is a pull request. Direct pushes to `main`/`test` are not part of the flow (main additionally enforces CI via branch protection).

## The PR gate

A PR is mergeable only when **both** hold:

1. **CI green** — the `ci`, `python` and `docker` checks pass on the PR.
2. **Agent approval** — the `pr-approver` agent (global agent, `~/.zcode/agents/pr-approver.md`) reviews the diff, re-runs the verification locally (typecheck, build, tests, backend pytest, project contracts such as `data-od-id` markers and EN/IT i18n parity) and posts an explicit **APPROVE** / **REQUEST_CHANGES** verdict as a PR review. Merging on REQUEST_CHANGES is not allowed; fix, push, re-review.

Squash-merge for feature PRs (one clean commit per feature); merge commits for promotion PRs (develop→test→main) to keep the group history.

## Releases

Releases are cut **only from `main`** by the `release-manager` agent (`~/.zcode/agents/release-manager.md`): semver by real user impact, version aligned to `package.json` **before** tagging (the release workflow gates tag ↔ version), tag push triggers the multi-platform build, detailed English release notes, installer assets verified. A release PR (version bump + notes prep) follows the same agent gate.

## Local verification before opening a PR

```sh
pnpm typecheck && pnpm build && pnpm test          # frontend + node tests
uv run --project backend pytest backend/tests -q   # backend
pnpm build && node scripts/check-od-ids.mjs        # UI contracts (when UI changed)
```
