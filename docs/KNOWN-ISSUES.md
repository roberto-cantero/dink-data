# Known issues

Bugs and design mistakes found in DinkData's code. Check this file before working in an area,
and add an entry when you find a new one. When an issue is fixed, set its status to Fixed and
link the PR. Don't delete entries.

The prototype's problems are summarised in ADR 0001.

| ID | Area | Problem | Severity | Status |
|---|---|---|---|---|
| K1 | CI | The gitleaks pre-commit hook scans only staged changes, so in CI it checks nothing | Medium | Open |

## K1 · Gitleaks doesn't scan in CI

- Where: `.pre-commit-config.yaml` and `.github/workflows/ci.yml`
- What: the gitleaks hook checks staged changes. CI runs pre-commit with `--all-files`, where
  nothing is staged, so secrets in a PR would only be caught on the author's machine.
- Fix: add a CI step that runs `gitleaks git` over the PR's commits.

## Entry format

```
## K1 · Short title

- Where: file and line
- What: what goes wrong, and when
- Fix: the fix, or the plan for it
```
