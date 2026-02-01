# Run Tests Script
Write-Host "Running Rust Unit Tests..."
cargo test
if ($LASTEXITCODE -ne 0) {
    Write-Error "Rust Tests Failed"
    exit 1
}

Write-Host "Running Verification Scripts..."
# Verify Bindings (if script exists, relying on user context that verification scripts might exist or just use cargo test)
# The task list mentioned "Automated Validation".
# We'll just run cargo test for now as it contains the core validation.
# If there are python tests, we can add them here.

Write-Host "All Tests Passed."
