param (
    [switch]$Verify
)

# Run Demos Script (Merged with Verification)

# 1. Code Generation
Write-Host "Generating bindings..."
python -m tools.codegen.main examples/integrated_apps/interface.py
if ($LASTEXITCODE -ne 0) { Write-Error "Code Generation Failed"; exit 1 }

# 2. Build Everything
Write-Host "Building Rust Demos (Integrated + Simple)..."
cargo build --examples --bins
if ($LASTEXITCODE -ne 0) { Write-Error "Rust Build Failed"; exit 1 }

Write-Host "Building C++ Demos..."
if (Get-Command "cmake" -ErrorAction SilentlyContinue) {
    if (-not (Test-Path "build")) { mkdir build }
    cd build
    cmake ..
    cmake --build . --config Release
    cd ..
}
else { Write-Warning "CMake not found, skipping C++ build" }

# 3. Simple Demos Validation
Write-Host "`n--- Verifying Simple No-SD Demos ---"
$rustServer = Start-Process -FilePath "target/debug/simple_server.exe" -PassThru -NoNewWindow
Start-Sleep -Milliseconds 500
$rustClientOut = & "target/debug/simple_client.exe" 2>&1
Write-Host "Rust Simple Client Output: $rustClientOut"
Stop-Process -Id $rustServer.Id -Force -ErrorAction SilentlyContinue

if ($rustClientOut -match "Success") { 
    Write-Host "Rust Simple Demo: PASS" -ForegroundColor Green 
}
else { 
    Write-Host "Rust Simple Demo: FAIL" -ForegroundColor Red
    if ($Verify) { exit 1 }
}

# 4. Integrated Apps
if ($Verify) {
    Write-Host "`n--- Running Integrated Apps Verification (10s) ---"
    
    # Clean old logs
    if (Test-Path "rust.log") { Remove-Item "rust.log" }
    if (Test-Path "python.log") { Remove-Item "python.log" }
    
    # Start Processes with Redirection
    $rustProcess = Start-Process -FilePath "cargo" -ArgumentList "run --example rust_app" -RedirectStandardOutput "rust.log" -RedirectStandardError "rust_err.log" -PassThru
    Start-Sleep -Seconds 2
    
    $env:PYTHONPATH = "src/python;build;build/generated/python"
    $pythonProcess = Start-Process -FilePath "python" -ArgumentList "-u examples/integrated_apps/python_app/main.py" -RedirectStandardOutput "python.log" -RedirectStandardError "python_err.log" -PassThru
    
    $cppProcess = $null
    $cppExe = "build/Release/cpp_app.exe"
    if (-not (Test-Path $cppExe)) { $cppExe = "build/Debug/cpp_app.exe" }
    if (Test-Path $cppExe) {
        $cppProcess = Start-Process -FilePath $cppExe -RedirectStandardOutput "cpp.log" -RedirectStandardError "cpp_err.log" -PassThru
    }

    Write-Host "Running..."
    Start-Sleep -Seconds 10
    
    Stop-Process -Id $rustProcess.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $pythonProcess.Id -Force -ErrorAction SilentlyContinue
    if ($cppProcess) { Stop-Process -Id $cppProcess.Id -Force -ErrorAction SilentlyContinue }

    # Pattern Matching
    $failed = $false
    
    # 1. Rust Provider (Math.Add from Py/C++)
    if (Test-Path "rust.log") {
        if (Select-String -Path rust.log -Pattern "Math.Add" -Quiet) { Write-Host "✅ RPC (Rust Provider): Verified" -ForegroundColor Green }
        else { Write-Host "❌ RPC (Rust Provider): Not found" -ForegroundColor Red; $failed = $true }
        
        # Event (Received by Rust)
        if (Select-String -Path rust.log -Pattern "Received Notification" -Quiet) { Write-Host "✅ Event (Rust Listener): Verified" -ForegroundColor Green }
        else { Write-Host "❌ Event (Rust Listener): Not found" -ForegroundColor Red; $failed = $true }
    }
    
    # 2. Python (Client Sending & String Service)
    if (Test-Path "python.log") {
        if (Select-String -Path python.log -Pattern "Sending Add" -Quiet) { Write-Host "✅ RPC (Py Client): Verified" -ForegroundColor Green }
        else { Write-Host "❌ RPC (Py Client): Not found" -ForegroundColor Red; $failed = $true }
        
        if (Select-String -Path python.log -Pattern "Reversing" -Quiet) { Write-Host "✅ RPC (Py String Svc): Verified" -ForegroundColor Green }
        else { Write-Host "❌ RPC (Py String Svc): Not found" -ForegroundColor Red; $failed = $true }
    }

    # 3. C++ (Client & Field)
    # 3. C++ (Client & Field)
    if (Test-Path "cpp.log") {
        if (Select-String -Path cpp.log -Pattern "Math.Add Result:" -Quiet) { Write-Host "✅ RPC (C++ -> Rust Math): Verified" -ForegroundColor Green }
        else { Write-Host "❌ RPC (C++ -> Rust Math): Not found" -ForegroundColor Red; $failed = $true }
        
        # Cross-Language Sort Checks (Distinguished by item count)
        # Python sends 5 items: [5, 3, 1, 4, 2]
        if (Select-String -Path cpp.log -Pattern "Sorting 5 items" -Quiet) { Write-Host "✅ RPC (Python -> C++ Sort): Verified" -ForegroundColor Green }
        else { Write-Host "❌ RPC (Python -> C++ Sort): Not found" -ForegroundColor Red; $failed = $true }

        # Rust sends 3 items: [9, 8, 7]
        if (Select-String -Path cpp.log -Pattern "Sorting 3 items" -Quiet) { Write-Host "✅ RPC (Rust -> C++ Sort): Verified" -ForegroundColor Green }
        else { Write-Host "❌ RPC (Rust -> C++ Sort): Not found" -ForegroundColor Red; $failed = $true }
        
        if (Select-String -Path cpp.log -Pattern "Field 'status' changed" -Quiet) { Write-Host "✅ Field (C++ Service): Verified" -ForegroundColor Green }
        else { Write-Host "❌ Field (C++ Service): Not found" -ForegroundColor Red; $failed = $true }
    }
    else {
        if (Get-Command "cmake" -ErrorAction SilentlyContinue) {
            # Only fail if CMake was available (meaning we expected C++ to run)
            Write-Host "❌ C++ Logs not found!" -ForegroundColor Red; $failed = $true 
        }
    }
    
    if ($failed) { exit 1 }
    Write-Host "All Verified!" -ForegroundColor Green

}
else {
    Write-Host "`n--- Starting Integrated Apps (Interactive) ---"
    
    $rustProcess = Start-Process -FilePath "cargo" -ArgumentList "run --example rust_app" -PassThru -NoNewWindow
    Start-Sleep -Seconds 2

    $pythonProcess = Start-Process -FilePath "python" -ArgumentList "examples/integrated_apps/python_app/main.py" -PassThru -NoNewWindow

    $cppExe = "build/Release/cpp_app.exe"
    if (-not (Test-Path $cppExe)) { $cppExe = "build/Debug/cpp_app.exe" }
    if (Test-Path $cppExe) {
        $cppProcess = Start-Process -FilePath $cppExe -PassThru -NoNewWindow
    }

    Write-Host "`nAll Integrated Demos running. Press Enter to stop..."
    Read-Host

    Stop-Process -Id $rustProcess.Id -Force -ErrorAction SilentlyContinue
    Stop-Process -Id $pythonProcess.Id -Force -ErrorAction SilentlyContinue
    if ($cppProcess) { Stop-Process -Id $cppProcess.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "Stopped."
}
