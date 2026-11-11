$ErrorActionPreference = "Stop"

$repoUrl = "https://github.com/dharshan020205/AeroSense-AI.git"
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is not installed. Install Git for Windows, then run this script again."
}

function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    & git @GitArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($GitArgs -join ' ')"
    }
}

if (-not (Test-Path (Join-Path $PSScriptRoot ".git"))) {
    Invoke-Git init
}
Invoke-Git branch -M main
Invoke-Git add -A

$status = & git status --porcelain
if ($LASTEXITCODE -ne 0) { throw "Could not read Git status." }
if ($status) {
    Invoke-Git commit -m "Publish AeroSense AI application"
} else {
    Write-Host "No uncommitted changes to add."
}

$remote = & git remote get-url origin 2>$null
if ($LASTEXITCODE -eq 0 -and $remote) {
    Invoke-Git remote set-url origin $repoUrl
} else {
    Invoke-Git remote add origin $repoUrl
}

Write-Host "Pushing AeroSense AI to $repoUrl ..."
Invoke-Git push -u origin main
Write-Host "Push completed. You can now deploy the repository on Render."
