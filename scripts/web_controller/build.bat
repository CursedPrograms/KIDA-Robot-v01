@echo off
rem Builds builds\KIDA-01-Controller.exe. Needs Visual Studio 2022; fetches Microsoft's WebView2 SDK once.
setlocal
cd /d "%~dp0"
if not exist sdk\build\native\include\WebView2.h (
  mkdir sdk 2>nul
  curl -sL -o sdk\wv2.zip https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/1.0.4314.35
  tar -xf sdk\wv2.zip -C sdk
)
call "%ProgramFiles%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" >nul
mkdir ..\..\builds 2>nul
mkdir obj 2>nul
rc /nologo /fo obj\app.res app.rc
cl /nologo /EHsc /std:c++17 /O2 /MT /utf-8 /DUNICODE /D_UNICODE /Isdk\build\native\include /Foobj\ main.cpp obj\app.res ^
   /Fe:..\..\builds\KIDA-01-Controller.exe /link /SUBSYSTEM:WINDOWS sdk\build\native\x64\WebView2LoaderStatic.lib
