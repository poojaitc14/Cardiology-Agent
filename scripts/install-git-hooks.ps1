# Installs the repository-managed Git hooks after `git init` / `git clone`.
$ErrorActionPreference = 'Stop'

git rev-parse --is-inside-work-tree | Out-Null
git config core.hooksPath .githooks
Write-Host "Git pre-push test hook installed. A push will be blocked unless pytest exits with code 0."
