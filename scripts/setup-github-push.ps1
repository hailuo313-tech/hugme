# One-time GitHub push setup (SSH + optional gh CLI)
# Run:  .\scripts\setup-github-push.ps1
$ErrorActionPreference = "Stop"
$sshDir = Join-Path $env:USERPROFILE ".ssh"
$key = Join-Path $sshDir "id_ed25519_github"
$config = Join-Path $sshDir "config"

if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory -Path $sshDir | Out-Null }

if (-not (Test-Path $key)) {
    Write-Host "Generating GitHub SSH key: $key"
    ssh-keygen -t ed25519 -f $key -N '""' -C "eris-github-push"
}

$block = @"

Host github.com
  HostName github.com
  User git
  IdentityFile $key
  IdentitiesOnly yes
"@

if (-not (Test-Path $config) -or ((Get-Content $config -Raw) -notmatch "Host github\.com")) {
    Add-Content -Path $config -Value $block
    Write-Host "Updated $config"
}

Write-Host ""
Write-Host "Add this deploy key or user key at https://github.com/settings/keys :" -ForegroundColor Cyan
Write-Host ""
Get-Content "$key.pub"
Write-Host ""
Write-Host "Then:  cd E:\eris" -ForegroundColor Yellow
Write-Host "       git push -u origin HEAD" -ForegroundColor Yellow
Write-Host ""
Write-Host "Or use HTTPS + gh:  gh auth login" -ForegroundColor Yellow
Write-Host "       git remote set-url origin https://github.com/hailuo313-tech/hugme.git" -ForegroundColor Yellow
