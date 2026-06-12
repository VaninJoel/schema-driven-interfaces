@echo off
REM Build the Schema-Driven Interfaces desktop installer for Windows using
REM conda-pack + a .zip package.
REM
REM Like build.sh, this packs the EXACT environment from environment.yml rather
REM than re-solving (required for CompuCell3D 4.7.0 — see README.md).
REM
REM Requires: conda on PATH, plus conda-pack and 7-Zip
REM   (conda install -n base -c conda-forge conda-pack 7zip).
setlocal enabledelayedexpansion

set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "REPO=%HERE%\.."
if "%SDI_ENV_NAME%"=="" set "SDI_ENV_NAME=sdi-dist"
set "STAGE=%HERE%\stage"
set "DIST=%HERE%\dist"
set "INSTALLER=%DIST%\SchemaDrivenInterfaces-Windows-x86_64.zip"

echo ^>^> [1/5] Creating conda env %SDI_ENV_NAME% from environment.yml
REM The community 'compucell3d' anaconda.org channel is occasionally slow or
REM returns HTTP 503 / connection timeouts. Bump conda's own download retries
REM and timeouts so transient blips don't break the env build.
set "CONDA_REMOTE_MAX_RETRIES=5"
set "CONDA_REMOTE_CONNECT_TIMEOUT_SECS=30"
set "CONDA_REMOTE_READ_TIMEOUT_SECS=120"
call conda env list | findstr /b /c:"%SDI_ENV_NAME% " >nul
if %errorlevel%==0 (set "ENVCMD=update --prune") else (set "ENVCMD=create")
REM IMPORTANT: do NOT abort on a non-zero exit here. On Windows, `conda env
REM create` ALWAYS reports failure at its bundled pip step because the
REM vs2015_win-64 activation script errors ("registry key not found" / GOTO End)
REM — but the conda packages (cc3d, PyQt5, ...) install fine. We delete that
REM script just below and redo the pip installs in step 2, and the
REM import-verification guard there is what aborts the build if the env is
REM genuinely incomplete (e.g. a real anaconda.org outage left cc3d missing).
call conda env %ENVCMD% -n "%SDI_ENV_NAME%" -f "%REPO%\environment.yml"

REM The vs2015_win-64 conda package ships a broken activation script
REM (vs2015_compiler_vars.bat does `GOTO End` with no `:End` label), which makes
REM conda's pip step AND `conda run` fail on Windows — silently leaving the
REM pip-only packages (vivarium-core + the wrappers) UNINSTALLED. Remove it; we
REM don't need an MSVC compiler at runtime. We then (re)install those packages
REM explicitly in step 2.
for /f "delims=" %%i in ('conda info --base') do set "CONDA_BASE=%%i"
set "ENVDIR=%CONDA_BASE%\envs\%SDI_ENV_NAME%"
if exist "%ENVDIR%\etc\conda\activate.d\vs2015_compiler_vars.bat" (
    del /f /q "%ENVDIR%\etc\conda\activate.d\vs2015_compiler_vars.bat"
    echo    removed broken vs2015_compiler_vars.bat activation script
)

echo ^>^> [2/5] Installing pip packages (vivarium-core + wrappers, non-editable)
REM env-create's pip step fails on Windows (see above), so install explicitly.
call conda run -n "%SDI_ENV_NAME%" python -m pip install vivarium-core
set "TMPWHL=%TEMP%\sdi_wheels"
if exist "%TMPWHL%" rmdir /s /q "%TMPWHL%"
mkdir "%TMPWHL%"
call conda run -n "%SDI_ENV_NAME%" python -m pip wheel "%REPO%\vivarium-vcornea" "%REPO%\vivarium-angio" -w "%TMPWHL%" --no-deps
REM cmd.exe does NOT expand *.whl, so install by name via --find-links instead.
call conda run -n "%SDI_ENV_NAME%" python -m pip install --no-deps --force-reinstall --no-index --find-links "%TMPWHL%" vivarium-vcornea vivarium-angio

REM Fail loudly if the env is incomplete, so we never ship a broken installer.
call conda run -n "%SDI_ENV_NAME%" python -c "import cc3d, PyQt5, reportlab, vivarium, vivarium_vcornea, vivarium_angio; print('packaged env OK')"
if errorlevel 1 (
    echo ERROR: packaged env is missing required packages — aborting build.
    exit /b 1
)

echo ^>^> [3/5] Packing environment (conda-pack)
if exist "%STAGE%" rmdir /s /q "%STAGE%"
if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%STAGE%\payload"
mkdir "%DIST%"
REM Use the conda-pack executable, not a `conda pack` subcommand.
REM --ignore-missing-files: we deliberately deleted the broken vs2015 activation
REM script above, so conda-pack would otherwise abort on the "deleted/overwritten
REM conda-managed file" check. It's a no-op activation helper, safe to omit.
call conda run -n base conda-pack -n "%SDI_ENV_NAME%" -o "%STAGE%\vc_env.tar.gz" --ignore-missing-files --force
if errorlevel 1 (
    echo ERROR: conda-pack failed — aborting build instead of shipping an env-less zip.
    exit /b 1
)
if not exist "%STAGE%\vc_env.tar.gz" (
    echo ERROR: conda-pack produced no vc_env.tar.gz — aborting build.
    exit /b 1
)

echo ^>^> [4/5] Staging app code + model data
for %%I in (vcornea-gui angio-gui vivarium-vcornea vivarium-angio vcornea_paper) do (
    xcopy /e /i /q "%REPO%\%%I" "%STAGE%\payload\%%I" >nul
)
for %%F in (README.md INSTALL.md) do copy /y "%REPO%\%%F" "%STAGE%\payload\" >nul
for /d /r "%STAGE%\payload" %%D in (__pycache__ experiments) do if exist "%%D" rmdir /s /q "%%D"
copy /y "%HERE%\install.bat" "%STAGE%\install.bat" >nul

echo ^>^> [5/5] Packaging Windows installer (.zip)
REM A .zip (built with the 7z we already install) is robust and needs no SFX
REM module. The user extracts it and double-clicks install.bat, which does the
REM unpack + conda-unpack + shortcut creation. Drop a short readme alongside.
> "%STAGE%\README-INSTALL.txt" (
  echo Schema-Driven Interfaces - Windows install
  echo.
  echo 1. Extract this zip anywhere ^(e.g. your Downloads folder^).
  echo 2. Double-click install.bat.
  echo 3. Launch from the Start menu ^("V-Cornea Simulation" / "Angiogenesis Simulation"^).
  echo.
  echo Installs to %%LOCALAPPDATA%%\SchemaDrivenInterfaces ^(no admin rights needed^).
)
pushd "%STAGE%"
call conda run -n base 7z a -tzip -mx=5 "%INSTALLER%" * >nul
popd

echo ^>^> Done: %INSTALLER%
dir "%INSTALLER%"
endlocal
