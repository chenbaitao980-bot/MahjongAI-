param(
    [string]$HostIp = "192.168.137.1",
    [string]$EcsHost = "root@8.136.37.136",
    [string]$EcsIp = "8.136.37.136",
    [string]$BumpVersion = "9.9.9.103",
    [string]$PythonExe = "python",
    [switch]$NoDivert
)

$ErrorActionPreference = "Stop"

# Prompt for SSH password via Windows Forms (masked input)
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

function Get-SshPassword {
    $form = New-Object System.Windows.Forms.Form
    $form.Text = "SSH Authentication"
    $form.Size = New-Object System.Drawing.Size(380, 160)
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false

    $label = New-Object System.Windows.Forms.Label
    $label.Text = "Enter password for $EcsHost`:"
    $label.Location = New-Object System.Drawing.Point(10, 15)
    $label.Size = New-Object System.Drawing.Size(350, 20)
    $form.Controls.Add($label)

    $textBox = New-Object System.Windows.Forms.TextBox
    $textBox.Location = New-Object System.Drawing.Point(10, 40)
    $textBox.Size = New-Object System.Drawing.Size(340, 20)
    $textBox.UseSystemPasswordChar = $true
    $form.Controls.Add($textBox)

    $okButton = New-Object System.Windows.Forms.Button
    $okButton.Text = "OK"
    $okButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $okButton.Location = New-Object System.Drawing.Point(200, 75)
    $form.Controls.Add($okButton)
    $form.AcceptButton = $okButton

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = "Cancel"
    $cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $cancelButton.Location = New-Object System.Drawing.Point(275, 75)
    $form.Controls.Add($cancelButton)
    $form.CancelButton = $cancelButton

    $result = $form.ShowDialog()
    if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
        throw "SSH password input cancelled by user."
    }
    return $textBox.Text
}

$SshPassword = Get-SshPassword

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LogsDir = Join-Path $RepoRoot "logs"
$TarPath = Join-Path $RepoRoot "hijack-update.tar"
$PidPath = Join-Path $LogsDir "hotspot_mitm.pid"
$OutLog = Join-Path $LogsDir "hotspot_mitm_bg.out.log"
$ErrLog = Join-Path $LogsDir "hotspot_mitm_bg.err.log"

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Invoke-Checked {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory = $RepoRoot,
        [string]$StdinInput = $null
    )
    if ($StdinInput) {
        $StdinInput | & $FilePath @Arguments
    } else {
        & $FilePath @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $FilePath $($Arguments -join ' ')"
    }
}

function Stop-LocalMitm {
    $patterns = @(
        "remote/noconfig/hijack/run_hijack.py",
        "remote\noconfig\hijack\run_hijack.py",
        "remote/noconfig/hijack/setup_mitm.py",
        "remote\noconfig\hijack\setup_mitm.py"
    )
    $procs = Get-CimInstance Win32_Process | Where-Object {
        $cmd = $_.CommandLine
        ($_.Name -match '^python(\.exe)?$|^py(\.exe)?$') -and
        $cmd -and
        (($patterns | Where-Object { $cmd -like "*$_*" }).Count -gt 0)
    }
    foreach ($proc in $procs) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
        } catch {
        }
    }
    if (Test-Path $PidPath) {
        Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
    }
}

function Assert-HotspotIp {
    $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
        Where-Object { $_.IPAddress -eq $HostIp }
    if (-not $ip) {
        throw "Hotspot IP $HostIp is not present. Open the Windows hotspot first."
    }
}

function Deploy-Remote {
    Invoke-Checked tar @(
        "-cf", $TarPath,
        "remote/noconfig",
        "remote/relay",
        "apk/game_base.apk"
    )

    # Use sshpass for password-based SCP and SSH
    $sshpass = & where.exe sshpass 2>$null
    if (-not $sshpass) {
        throw "sshpass is not installed. Please install sshpass (e.g., via Chocolatey: choco install sshpass) or set up SSH key authentication."
    }

    Invoke-Checked sshpass @("-p", $SshPassword, "scp", "-o", "StrictHostKeyChecking=no", $TarPath, "$EcsHost`:/tmp/hijack-update.tar")

    $remoteScript = @"
set -e
rm -rf /tmp/hijack-update
mkdir -p /tmp/hijack-update
cd /tmp/hijack-update
tar -xf /tmp/hijack-update.tar
cp -r remote/noconfig/* /opt/mahjong-remote/remote/noconfig/
cp -r remote/relay/* /opt/mahjong-remote/remote/relay/
mkdir -p /opt/mahjong-remote/apk
cp apk/game_base.apk /opt/mahjong-remote/apk/game_base.apk
systemctl restart mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig
sleep 2
systemctl is-active mahjong-mitm-hotupdate mahjong-tcp-proxy mahjong-relay-noconfig
python3 - <<'PY'
import json, urllib.request, ssl, hashlib
from urllib.parse import urlsplit
ctx = ssl._create_unverified_context()
req = urllib.request.Request(
    'https://127.0.0.1/hotfix_update?env=1&appid=1073&engine_ver=3.13&channel=10001116_astc&version=1.0.0.59',
    headers={'Host': 'gxb-api.hzxuanming.com'},
)
vm = json.loads(urllib.request.urlopen(req, context=ctx, timeout=10).read().decode())
assert vm['version'] == '$BumpVersion', vm
parts = urlsplit(vm['manifest_url'][0])
local_url = 'https://127.0.0.1' + parts.path + (('?' + parts.query) if parts.query else '')
req = urllib.request.Request(local_url, headers={'Host': parts.hostname})
pm = json.loads(urllib.request.urlopen(req, context=ctx, timeout=10).read().decode())
fl = pm['file_list']
assert sorted(fl.keys()) == sorted([
    'src/app/config/NetConf.luac',
    'src/app/hotupdate/lobby/ResEnsure.luac',
    'src/app/hotupdate/lobby/ResChecker.luac',
]) or sorted(fl.keys()) == sorted([
    'src/app/Config/NetConf.luac',
    'src/app/hotupdate/lobby/ResEnsure.luac',
    'src/app/hotupdate/lobby/ResChecker.luac',
]), fl.keys()
rc = fl['src/app/hotupdate/lobby/ResChecker.luac']
req = urllib.request.Request(
    'https://127.0.0.1/yj/files/' + rc['name'],
    headers={'Host': 'gxb-oss.hzxuanming.com'},
)
body = urllib.request.urlopen(req, context=ctx, timeout=10).read()
assert hashlib.md5(body).hexdigest() == rc['md5'], rc
print('REMOTE_OK', vm['version'], rc['md5'], len(body), local_url)
PY
"@

    Invoke-Checked sshpass @("-p", $SshPassword, "ssh", "-o", "StrictHostKeyChecking=no", $EcsHost, $remoteScript)
}

function Start-LocalMitm {
    Stop-LocalMitm
    if (Test-Path $OutLog) { Remove-Item $OutLog -Force }
    if (Test-Path $ErrLog) { Remove-Item $ErrLog -Force }

    $args = @(
        "remote/noconfig/hijack/run_hijack.py",
        "--host-ip", $HostIp,
        "--ecs-ip", $EcsIp,
        "--bump-version", $BumpVersion
    )
    if ($NoDivert) {
        $args += "--no-divert"
    }

    $proc = Start-Process -FilePath $PythonExe `
        -ArgumentList $args `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -PassThru

    Set-Content -Path $PidPath -Value $proc.Id

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 700
        if ($proc.HasExited) {
            $stderr = if (Test-Path $ErrLog) { Get-Content $ErrLog -Raw } else { "" }
            throw "Local MITM exited early. $stderr"
        }
        if ((Test-Path $OutLog) -and (Get-Content $OutLog -Raw) -match "MITM") {
            break
        }
    }

$verify = @"
import json, ssl, urllib.request
from urllib.parse import urlsplit
ctx = ssl._create_unverified_context()
req = urllib.request.Request(
    'https://127.0.0.1/hotfix_update?env=1&appid=1073&engine_ver=3.13&channel=10001116_astc&version=1.0.0.59',
    headers={'Host': 'gxb-api.hzxuanming.com'},
)
vm = json.loads(urllib.request.urlopen(req, context=ctx, timeout=10).read().decode())
assert vm['version'] == '$BumpVersion', vm
parts = urlsplit(vm['manifest_url'][0])
local_url = 'https://127.0.0.1' + parts.path + (('?' + parts.query) if parts.query else '')
req = urllib.request.Request(local_url, headers={'Host': parts.hostname})
pm = json.loads(urllib.request.urlopen(req, context=ctx, timeout=10).read().decode())
keys = sorted(pm['file_list'].keys())
assert keys in (
    ['src/app/Config/NetConf.luac', 'src/app/hotupdate/lobby/ResChecker.luac', 'src/app/hotupdate/lobby/ResEnsure.luac'],
    ['src/app/config/NetConf.luac', 'src/app/hotupdate/lobby/ResChecker.luac', 'src/app/hotupdate/lobby/ResEnsure.luac'],
), keys
print('LOCAL_OK', vm['version'], local_url, len(keys))
"@
    $verify | & $PythonExe -
    if ($LASTEXITCODE -ne 0) {
        throw "Local MITM verification failed."
    }
}

Push-Location $RepoRoot
try {
    Assert-HotspotIp
    Deploy-Remote
    Start-LocalMitm
    Write-Host "READY Local hotspot MITM is running in background." -ForegroundColor Green
    Write-Host "  Local log:  $OutLog"
    Write-Host "  Local err:  $ErrLog"
    Write-Host "  Local pid:  $PidPath"
    Write-Host "  Remote host: $EcsHost"
    Write-Host "  Version:    $BumpVersion"
} finally {
    Pop-Location
}
