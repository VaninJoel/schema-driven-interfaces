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
set "INSTALLER=%DIST%\SchemaDrivenInterfaces-Windows-x86_64.exe"

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
call conda pack -n "%SDI_ENV_NAME%" -o "%STAGE%\vc_env.tar.gz" --force

echo ^>^> [4/5] Staging app code + model data
for %%I in (vcornea-gui angio-gui vivarium-vcornea vivarium-angio vcornea_paper) do (
    xcopy /e /i /q "%REPO%\%%I" "%STAGE%\payload\%%I" >nul
)
for %%F in (README.md INSTALL.md) do copy /y "%REPO%\%%F" "%STAGE%\payload\" >nul
for /d /r "%STAGE%\payload" %%D in (__pycache__ experiments) do if exist "%%D" rmdir /s /q "%%D"
copy /y "%HERE%\install.bat" "%STAGE%\install.bat" >nul

echo ^>^> [5/5] Building self-extracting .exe with 7-Zip
REM Build a 7z SFX: config specifies that install.bat runs after extraction.
> "%STAGE%\__sfx_config.txt" (
  echo ;!@Install@!UTF-8!
  echo Title="Schema-Driven Interfaces"
  echo RunProgram="cmd /c install.bat"
  echo ;!@InstallEnd@!
)
pushd "%STAGE%"
7z a -t7z -mx=5 "%TEMP%\sdi_payload.7z" * -x^^!__sfx_config.txt >nul
popd
REM Concatenate the 7z SFX module + config + archive into a single .exe
for /f "delims=" %%P in ('where 7z.sfx 2^>nul') do set "SFXMOD=%%P"
if "%SFXMOD%"=="" for /f "delims=" %%P in ('conda run -n base python -c "import os,sys; p=os.path.dirname(sys.executable); print(os.path.join(p,'Library','bin','7z.sfx'))"') do set "SFXMOD=%%P"
copy /b "%SFXMOD%" + "%STAGE%\__sfx_config.txt" + "%TEMP%\sdi_payload.7z" "%INSTALLER%" >nul

echo ^>^> Done: %INSTALLER%
dir "%INSTALLER%"
endlocal
