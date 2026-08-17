# Contribution and GitHub Quality Gate

This repository requires **six passing unit tests** before a change is pushed.

## Set up the local gate

After cloning the repository (or after `git init`), install dependencies and the hook:

```powershell
pip install -r requirements.txt
.\scripts\install-git-hooks.ps1
python -m pytest tests -q
```

The pre-push hook runs `python -m pytest tests -q`. Git only pushes when its exit status is `0`; a failing or unavailable test command blocks the push.

## GitHub gate

`.github/workflows/test.yml` runs the same test command for pull requests and pushes to `main`. After creating the GitHub repository, configure a branch-protection rule for `main` and require the **Python unit tests** status check before merging. GitHub cannot run tests *before* a developer sends commits to GitHub; the local pre-push hook provides that pre-push check, while branch protection prevents untested code from merging to `main`.

## Current six tests

1. Health endpoint succeeds.
2. Authorized synthetic review returns HTTP 200.
3. Review returns history, medication, allergy, and laboratory categories.
4. Recorded allergy is flagged for clinician verification.
5. Draft hospital policy is excluded from RAG results.
6. Unauthorized requester is denied with HTTP 403.

Never bypass this gate for clinical-facing changes. Do not use real patient data in tests.
