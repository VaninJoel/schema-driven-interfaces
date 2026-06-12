@echo off
REM Build the Schema-Driven Interfaces desktop installer for Windows using
REM conda-pack + a 7-Zip self-extracting archive (.exe).
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
call conda env list | findstr /b /c:"%SDI_ENV_NAME% " >nul
if %errorlevel%==0 (
    call conda env update -n "%SDI_ENV_NAME%" -f "%REPO%\environment.yml" --prune
) else (
    call conda env create -n "%SDI_ENV_NAME%" -f "%REPO%\environment.yml"
)

echo ^>^> [2/5] Reinstalling wrapper packages non-editable
set "TMPWHL=%TEMP%\sdi_wheels"
if exist "%TMPWHL%" rmdir /s /q "%TMPWHL%"
mkdir "%TMPWHL%"
call conda run -n "%SDI_ENV_NAME%" python -m pip wheel "%REPO%\vivarium-vcornea" "%REPO%\vivarium-angio" -w "%TMPWHL%" --no-deps
call conda run -n "%SDI_ENV_NAME%" python -m pip install --no-deps --force-reinstall "%TMPWHL%\*.whl"

echo ^>^> [3/5] Packing environment (conda-pack)
if exist "%STAGE%" rmdir /s /q "%STAGE%"
if exist "%DIST%" rmdir /s /q "%DIST%"
mkdir "%STAGE%\payload"
mkdir "%DIST%"
REM Use the conda-pack executable, not a `conda pack` subcommand.
call conda run -n base conda-pack -n "%SDI_ENV_NAME%" -o "%STAGE%\vc_env.tar.gz" --force

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
