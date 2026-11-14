param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*$')]
    [string]$Name
)
$ErrorActionPreference = 'Stop'
$source = (git rev-parse --show-toplevel).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Not in a git repository' }
$target = Join-Path 'D:\cake-wt' $Name
if (Test-Path -LiteralPath $target) { throw "Target already exists: $target" }
git worktree add -b "feat/$Name" $target main
if ($LASTEXITCODE -ne 0) { throw 'Could not create worktree' }
foreach ($dir in @('samples', 'models')) {
    New-Item -ItemType Junction -Path (Join-Path $target $dir) -Target (Join-Path $source $dir) | Out-Null
}
foreach ($entry in @(@('luts', '*.cube'), @('tools/results/golden', '*.npz'))) {
    $dest = Join-Path $target $entry[0]
    New-Item -ItemType Directory -Force -Path $dest | Out-Null
    Get-ChildItem -LiteralPath (Join-Path $source $entry[0]) -Filter $entry[1] -File | Copy-Item -Destination $dest
}
