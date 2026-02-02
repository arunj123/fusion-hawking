# Verify Events Script

Write-Host "Starting C++ App..."
$cppExe = "build/Release/cpp_app.exe"
if (-not (Test-Path $cppExe)) { $cppExe = "build/Debug/cpp_app.exe" }
$cppProcess = Start-Process -FilePath $cppExe -RedirectStandardOutput "cpp.log" -RedirectStandardError "cpp_err.log" -PassThru
Start-Sleep -Seconds 2

Write-Host "Starting Rust App..."
$rustProcess = Start-Process -FilePath "cargo" -ArgumentList "run --example rust_app" -RedirectStandardOutput "rust.log" -RedirectStandardError "rust_err.log" -PassThru
Start-Sleep -Seconds 5

Write-Host "Starting Python App..."
$env:PYTHONPATH = "src/python;build;build/generated/python"
$pythonProcess = Start-Process -FilePath "python" -ArgumentList "-u examples/python_app/main.py" -RedirectStandardOutput "python.log" -RedirectStandardError "python_err.log" -PassThru
Start-Sleep -Seconds 5

Write-Host "Stopping demo processes..."
# Terminate processes and wait for them to exit
Stop-Process -Id $cppProcess.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $pythonProcess.Id -Force -ErrorAction SilentlyContinue
Stop-Process -Id $rustProcess.Id -Force -ErrorAction SilentlyContinue

# Wait for all processes to fully exit (timeout 5 seconds each)
$cppProcess | Wait-Process -Timeout 5 -ErrorAction SilentlyContinue
$pythonProcess | Wait-Process -Timeout 5 -ErrorAction SilentlyContinue
$rustProcess | Wait-Process -Timeout 5 -ErrorAction SilentlyContinue

# Kill any remaining cargo/rust child processes
Get-Process -Name "rust_app" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
# Kill any remaining python processes running the demo
Get-CimInstance Win32_Process -Filter "Name = 'python.exe' AND CommandLine LIKE '%main.py%'" | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host "All demo processes stopped."

# Check Logs for Features
Write-Host "`n--- Verification Results ---"
$failed = $false

# 1. Methods (RPC)
# Rust -> MathService (Python/Rust) -> Math.Add
$rpc_rust_math = Select-String -Path rust.log -Pattern "Math.Add" -Quiet
if ($rpc_rust_math) { Write-Host "✅ RPC (Rust -> Math): Verified" -ForegroundColor Green }
else { Write-Host "❌ RPC (Rust -> Math): Failed" -ForegroundColor Red; $failed = $true }

# Rust -> StringService (Python) -> Reversing
# Check Python logs for StringService processing Rust's request
$rpc_rust_str = Select-String -Path python.log -Pattern "Reversing" -Quiet
if ($rpc_rust_str) { Write-Host "✅ RPC (Rust -> Python String): Verified" -ForegroundColor Green }
else { Write-Host "❌ RPC (Rust -> Python String): Failed" -ForegroundColor Red; $failed = $true }

# Python -> MathService (Rust) -> Math.Add
# Check Python logs for client sending Add request
$rpc_py_math = Select-String -Path python.log -Pattern "Sending Add" -Quiet
if ($rpc_py_math) { Write-Host "✅ RPC (Python -> Math): Verified" -ForegroundColor Green }
else { Write-Host "❌ RPC (Python -> Math): Not found in logs" -ForegroundColor Red; $failed = $true }

# C++ -> MathService -> Add
$rpc_cpp_math = Select-String -Path cpp.log -Pattern "Sending Add" -Quiet
if ($rpc_cpp_math) { Write-Host "✅ RPC (C++ -> Math): Verified" -ForegroundColor Green }
else { Write-Host "❌ RPC (C++ -> Math): Failed" -ForegroundColor Red; $failed = $true }


# 2. Events & Fields
# C++ SortService: Fires Event & Updates Field
# Check Field Log in C++
$field_cpp = Select-String -Path cpp.log -Pattern "Field 'status' changed" -Quiet
if ($field_cpp) { Write-Host "✅ Field (C++ SortStatus): Verified" -ForegroundColor Green }
else { Write-Host "❌ Field (C++ SortStatus): Failed" -ForegroundColor Red; $failed = $true }

# Check Event Notification in Rust
# Rust logs "Received Notification from 0x..."
$event_rust = Select-String -Path rust.log -Pattern "Received Notification" -Quiet
if ($event_rust) { Write-Host "✅ Event (Rust Consuming): Verified" -ForegroundColor Green }
else { Write-Host "❌ Event (Rust Consuming): Failed" -ForegroundColor Red; $failed = $true }

if ($failed) {
    Write-Error "One or more verification steps failed. Check logs."
    exit 1
} else {
    Write-Host "`n🎉 All Demos Verified Successfully!" -ForegroundColor Cyan
}
exit 0
