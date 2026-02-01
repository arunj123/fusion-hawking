# Run Demos Script
Write-Host "Building Fusion Hawking..."
cargo build --examples
if ($LASTEXITCODE -ne 0) {
    Write-Error "Build Failed"
    exit 1
}

Write-Host "Starting Rust Service (Math Service)..."
$rustProcess = Start-Process -FilePath "cargo" -ArgumentList "run --bin rust_demo" -PassThru -NoNewWindow
Start-Sleep -Seconds 2

Write-Host "Starting Python Client/Service..."
# Assuming python is in PATH
$pythonProcess = Start-Process -FilePath "python" -ArgumentList "examples/python_app/main.py" -PassThru -NoNewWindow

Write-Host "Demos running. Press Enter to stop..."
Read-Host

Stop-Process -Id $rustProcess.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $pythonProcess.Id -Force -ErrorAction SilentlyContinue
Write-Host "Stopped."
