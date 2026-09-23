@echo off
cd /d %~dp0\..
set PYTHONPATH=%CD%\src;%PYTHONPATH%
if "%CONTEXTMESH_HOST%"=="" set CONTEXTMESH_HOST=127.0.0.1
if "%CONTEXTMESH_PORT%"=="" set CONTEXTMESH_PORT=8765
python -m contextmesh.cli serve --host %CONTEXTMESH_HOST% --port %CONTEXTMESH_PORT%
