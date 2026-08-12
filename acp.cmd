@echo off
REM Checkout-local shim. Prefer: install.ps1 so `acp` is on PATH.
REM Do not recurse into this file — always launch the Python module.
python -m ascendc_pilot %*
exit /b %ERRORLEVEL%
