@echo off
set VC71=C:\Program Files (x86)\Microsoft Visual C++ Toolkit 2003
set SDK=C:\Program Files\Microsoft Platform SDK for Windows Server 2003 R2\

set PATH=%VC71%\bin;%SDK%\Bin;%PATH%
set INCLUDE=%VC71%\include;%SDK%\Include
set LIB=%VC71%\lib;%SDK%\Lib

echo =====================================
echo VC71 + Platform SDK environment ready
echo =====================================
cmd