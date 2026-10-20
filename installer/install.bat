@echo off
REM On-target installer (Windows). Shipped inside the release .zip built by
REM build.bat; the user extracts the zip and double-clicks this script, so the
REM working directory is the extracted folder (vc_env.tar.gz + payload\ + this script).
REM
REM Relocates the conda-pack'd environment, repairs prefixes (conda-unpack),
REM installs the app code, and creates launchers + Start-menu/Desktop shortcuts.
setlocal enabledelayedexpansion

set "PREFIX=%SDI_PREFIX%"
if "%PREFIX%"=="" set "PREFIX=%LOCALAPPDATA%\SchemaDrivenInterfaces"

echo Installing Schema-Driven Interfaces to: %PREFIX%
if not exist "%PREFIX%" mkdir "%PREFIX%"

echo   - unpacking environment (this is the large step)...
REM tar ships with Windows 10+; python fallback if absent.
tar -xzf vc_env.tar.gz -C "%PREFIX%" || ^
  python -c "import tarfile,sys; tarfile.open(sys.argv[1]).extractall(sys.argv[2])" vc_env.tar.gz "%PREFIX%"

echo   - finalizing environment (conda-unpack)...
call "%PREFIX%\Scripts\conda-unpack.exe"
if errorlevel 1 (
    echo ERROR: conda-unpack failed — the environment may not run correctly.
    echo Press any key to close.
    pause >nul
    exit /b 1
)

echo   - verifying environment integrity...
REM conda-unpack can corrupt .py files containing backslash escapes on Windows
REM (conda-pack #154, e.g. _pytest\pathlib.py). Detect and restore them from the
REM pristine packed env so imports don't crash with SyntaxError.
call "%PREFIX%\python.exe" "%~dp0repair_env.py" "%PREFIX%" "vc_env.tar.gz"

echo   - installing application files...
set "SDI=%PREFIX%\share\sdi"
if not exist "%SDI%" mkdir "%SDI%"
REM Reinstall replaces the app files, but never a user's runs or settings: an
REM earlier version saved runs to payload\<app>\experiments by default.
for %%A in (angio-gui vcornea-gui) do (
    if exist "%SDI%\payload\%%A\experiments" (
        if not exist "%SDI%\keep\%%A" mkdir "%SDI%\keep\%%A"
        move "%SDI%\payload\%%A\experiments" "%SDI%\keep\%%A\" >nul
    )
    if exist "%SDI%\payload\%%A\.gui_settings.json" (
        if not exist "%SDI%\keep\%%A" mkdir "%SDI%\keep\%%A"
        move "%SDI%\payload\%%A\.gui_settings.json" "%SDI%\keep\%%A\" >nul
    )
)
REM A folder still in place means the move failed (e.g. open in Explorer):
REM stop here rather than let rmdir below delete it.
for %%A in (angio-gui vcornea-gui) do if exist "%SDI%\payload\%%A\experiments" (
    echo ERROR: could not move your saved runs out of "%SDI%\payload\%%A\experiments".
    echo Close any window or program using that folder and run install.bat again.
    echo Nothing was deleted. Press any key to close.
    pause >nul
    exit /b 1
)
if exist "%SDI%\payload" rmdir /s /q "%SDI%\payload"
xcopy /e /i /q payload "%SDI%\payload" >nul
for %%A in (angio-gui vcornea-gui) do (
    if exist "%SDI%\keep\%%A\experiments" move "%SDI%\keep\%%A\experiments" "%SDI%\payload\%%A\" >nul
    if exist "%SDI%\keep\%%A\.gui_settings.json" move "%SDI%\keep\%%A\.gui_settings.json" "%SDI%\payload\%%A\" >nul
)
REM Non-recursive: only removes them if empty, so nothing kept is ever lost.
for %%A in (angio-gui vcornea-gui) do if exist "%SDI%\keep\%%A" rmdir "%SDI%\keep\%%A" 2>nul
if exist "%SDI%\keep" rmdir "%SDI%\keep" 2>nul
set "APPS=%SDI%\payload"

REM --- Launchers (pythonw => no console window) ---
if not exist "%PREFIX%\Scripts" mkdir "%PREFIX%\Scripts"
> "%PREFIX%\Scripts\vcornea-gui.bat" echo @start "" "%PREFIX%\pythonw.exe" "%APPS%\vcornea-gui\run_gui.py" %%*
> "%PREFIX%\Scripts\angio-gui.bat"   echo @start "" "%PREFIX%\pythonw.exe" "%APPS%\angio-gui\run_gui.py" %%*

REM --- Desktop + Start-menu shortcuts ---
set "SMDIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Schema-Driven Interfaces"
if not exist "%SMDIR%" mkdir "%SMDIR%"
call :mkshortcut "V-Cornea Simulation"     "%APPS%\vcornea-gui\run_gui.py"
call :mkshortcut "Angiogenesis Simulation" "%APPS%\angio-gui\run_gui.py"

echo.
echo Schema-Driven Interfaces installed successfully.
echo   Launch from the Start menu ("V-Cornea Simulation" / "Angiogenesis Simulation"),
echo   or run these from a terminal:
echo       "%PREFIX%\Scripts\vcornea-gui.bat"
echo       "%PREFIX%\Scripts\angio-gui.bat"
echo.
REM Keep the window open so the user can read the result (double-click closes it
REM instantly otherwise).
echo Press any key to close this window.
pause >nul
endlocal
exit /b 0

:mkshortcut
set "TITLE=%~1"
set "TARGETPY=%~2"
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "foreach ($dir in @([Environment]::GetFolderPath('Desktop'), $env:SMDIR)) {" ^
  "  $lnk = $ws.CreateShortcut((Join-Path $dir ('%TITLE%' + '.lnk')));" ^
  "  $lnk.TargetPath = '%PREFIX%\pythonw.exe';" ^
  "  $lnk.Arguments = '\"%TARGETPY%\"';" ^
  "  $lnk.WorkingDirectory = (Split-Path '%TARGETPY%');" ^
  "  $lnk.Save() }"
exit /b 0
