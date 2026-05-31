# LeanReel-rs dev launcher
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
pushd "$PSScriptRoot\src-tauri"

Get-Process -Name "leanreel-rs" -ErrorAction SilentlyContinue | Stop-Process -Force

cargo tauri dev

popd
