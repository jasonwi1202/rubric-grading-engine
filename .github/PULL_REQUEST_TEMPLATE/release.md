## Milestone Release: <!-- e.g. M1 — Foundation -->

Closes milestone: <!-- link to the GitHub Milestone -->

---

## What's in this release

<!-- One-sentence summary of what this milestone delivers. -->

## Issues included

<!-- List every issue merged into this release branch. -->

| Issue | Title | PR |
|---|---|---|
| # | | # |
| # | | # |

## Verification

- [ ] All feature PRs merged into `release/<milestone>`
- [ ] CI passes green on `release/<milestone>` — all jobs, not just lint
- [ ] No unresolved review comments on any constituent PR
- [ ] `docs/roadmap.md` milestone marked complete
- [ ] Release notes file added at `docs/release-notes/milestone-N.md`
- [ ] No student PII in any file added or modified in this release

## Breaking changes

<!-- List any breaking API changes, required migration steps, or config variable changes. If none, write "None." -->

None.

## Rollback plan

1. Revert the merge commit on `main`: `git revert -m 1 <merge-commit-sha>`
2. Alembic downgrade if migrations were included: `docker run rubric-grading-backend alembic downgrade -1`
3. Redeploy previous image tag

## Post-merge checklist

- [ ] GitHub Release created automatically by `.github/workflows/milestone-release.yml`
- [ ] Release tag visible on GitHub (format: `v0.N.0` — see workflow for derivation)
- [ ] `docs/release-notes/milestone-N.md` present and accurate
- [ ] Release notes categories match labels defined in `.github/release.yml`
