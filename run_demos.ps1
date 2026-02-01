# Run Demos Script
Write-Host "Building Fusion Hawking..."
cargo build --examples
if ($LASTEXITCODE -ne 0) {
    Write-Error "Build Failed"
    exit 1
}

Write-Host "Starting Rust Service (Math Service)..."
$rustProcess = Start-Process -FilePath "cargo" -ArgumentList "run --example rust_app" -PassThru -NoNewWindow
Start-Sleep -Seconds 2

Write-Host "Starting Python Client/Service..."
# Assuming python is in PATH
$pythonProcess = Start-Process -FilePath "python" -ArgumentList "examples/python_app/main.py" -PassThru -NoNewWindow

Write-Host "Building & Starting C++ App..."
if (Get-Command "cmake" -ErrorAction SilentlyContinue) {
    if (-not (Test-Path "build")) { mkdir build }
    cd build
    cmake ..
    cmake --build . --config Release
    cd ..
    
    $cppExe = "build/Release/cpp_app.exe"
    if (-not (Test-Path $cppExe)) { $cppExe = "build/Debug/cpp_app.exe" }
    if (-not (Test-Path $cppExe)) { $cppExe = "build/cpp_app.exe" }
    
    if (Test-Path $cppExe) {
        $cppProcess = Start-Process -FilePath $cppExe -PassThru -NoNewWindow
    } else {
        Write-Warning "C++ Executable not found."
    }
}

Write-Host "Demos running. Press Enter to stop..."
Read-Host

StopProcess -Id $rustProcess.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $pythonProcess.Id -Force -ErrorAction SilentlyContinue
if ($cppProcess) { Stop-Process -Id $cppProcess.Id -Force -ErrorAction SilentlyContinue }
Write-Host "Stopped."
