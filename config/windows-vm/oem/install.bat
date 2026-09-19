@echo off
rem winbox - first-boot setup for the Windows virtual machine.
rem
rem The image copies this directory into the machine and runs this file once,
rem at the end of the unattended Windows installation, with administrator
rem rights. Everything an agent needs to reach the machine is set up here.
rem
rem NEVER put a secret in this file. It is tracked in Git. The only key
rem material that reaches the machine is the PUBLIC half, which bin/winbox
rem stages next to this file as "authorized_keys".
rem
rem Every step writes to C:\winbox-install.log, because a first boot has no
rem human watching it. Read the log with:  winbox exec type C:\winbox-install.log

setlocal
set "LOG=%SystemDrive%\winbox-install.log"
echo [winbox] setup started %DATE% %TIME%>>"%LOG%"

rem --- the OpenSSH server -----------------------------------------------------
rem Windows Server 2025 carries the server already. An edition that does not
rem installs it here, which needs the network and adds several minutes.
sc query sshd >nul 2>&1
if errorlevel 1 (
    echo [winbox] installing the OpenSSH server>>"%LOG%"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0">>"%LOG%" 2>&1
)

rem --- cmd.exe is the shell an SSH command lands in ---------------------------
rem Without these two values sshd starts PowerShell, which prints a banner,
rem parses the command line by its own rules, and reports its own exit code.
rem An agent needs one command, one output and one exit code.
reg add "HKLM\SOFTWARE\OpenSSH" /v DefaultShell /t REG_SZ /d "%SystemRoot%\System32\cmd.exe" /f>>"%LOG%" 2>&1
reg add "HKLM\SOFTWARE\OpenSSH" /v DefaultShellCommandOption /t REG_SZ /d "/c" /f>>"%LOG%" 2>&1

rem --- the public key the host staged -----------------------------------------
rem The account is an administrator, and sshd reads an administrator key from
rem one shared file. sshd IGNORES that file, with no error, when anyone but
rem SYSTEM and the administrators group can write it, so the permissions are
rem set here instead of being left at the default. The two accounts are named
rem by SID, because their names are translated on a localised Windows.
if not exist "%ProgramData%\ssh" mkdir "%ProgramData%\ssh"
if exist "%~dp0authorized_keys" (
    copy /y "%~dp0authorized_keys" "%ProgramData%\ssh\administrators_authorized_keys">>"%LOG%" 2>&1
    icacls "%ProgramData%\ssh\administrators_authorized_keys" /inheritance:r>>"%LOG%" 2>&1
    icacls "%ProgramData%\ssh\administrators_authorized_keys" /grant "*S-1-5-18:(F)">>"%LOG%" 2>&1
    icacls "%ProgramData%\ssh\administrators_authorized_keys" /grant "*S-1-5-32-544:(F)">>"%LOG%" 2>&1
) else (
    echo [winbox] WARNING: no authorized_keys was staged; only the password works>>"%LOG%"
)

rem --- start it, and start it at every boot -----------------------------------
sc config sshd start= auto>>"%LOG%" 2>&1
sc config ssh-agent start= auto>>"%LOG%" 2>&1
net start sshd>>"%LOG%" 2>&1

rem --- let it through the firewall --------------------------------------------
netsh advfirewall firewall show rule name="winbox OpenSSH Server" >nul 2>&1
if errorlevel 1 netsh advfirewall firewall add rule name="winbox OpenSSH Server" dir=in action=allow protocol=TCP localport=22>>"%LOG%" 2>&1

rem --- the marker "winbox status" reads ---------------------------------------
echo winbox-ready>"%SystemDrive%\winbox-ready.txt"
echo [winbox] setup finished %DATE% %TIME%>>"%LOG%"
endlocal
