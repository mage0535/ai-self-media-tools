$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$validator = Join-Path $PSScriptRoot "validate_channel_rulebook.py"

$python = $null
foreach ($candidate in @("python3", "python", "py")) {
  $command = Get-Command $candidate -ErrorAction SilentlyContinue
  if ($command) {
    $python = $command.Source
    break
  }
}
if (-not $python) {
  throw "Python is required to run the canonical channel rulebook validator"
}

Push-Location $root
try {
  & $python $validator
  if ($LASTEXITCODE -ne 0) {
    throw "canonical channel rulebook validation failed with exit code $LASTEXITCODE"
  }
}
finally {
  Pop-Location
}
