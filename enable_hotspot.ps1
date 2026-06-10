# enable_hotspot.ps1 - best effort start Windows Mobile Hotspot
#
# Uses WinRT NetworkOperatorTetheringManager. If the active internet profile
# can be tethered, StartTetheringAsync() turns the hotspot on (gateway
# 192.168.137.1). Any failure prints a manual instruction and exits 0 so the
# launcher is never interrupted by a hotspot problem.

$ErrorActionPreference = "Stop"

function Wait-WinRtAsync {
    param($asyncOp, [Type]$resultType)
    # Bridge WinRT IAsyncOperation<T> to a .NET Task and block for the result.
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -like "IAsyncOperation``1*"
        } | Select-Object -First 1
    $generic = $asTask.MakeGenericMethod($resultType)
    $task = $generic.Invoke($null, @($asyncOp))
    return $task.GetAwaiter().GetResult()
}

function Print-Manual {
    Write-Host ""
    Write-Host "[hotspot] Could not start the Mobile Hotspot automatically."
    Write-Host "[hotspot] Open Settings > Network & Internet > Mobile hotspot,"
    Write-Host "[hotspot] turn it on, then connect your phone to it."
    Write-Host "[hotspot] The phone game traffic must pass through this PC for capture."
}

try {
    [void][Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager, Windows.Networking.NetworkOperators, ContentType = WindowsRuntime]
    [void][Windows.Networking.Connectivity.NetworkInformation, Windows.Networking.Connectivity, ContentType = WindowsRuntime]

    $profile = [Windows.Networking.Connectivity.NetworkInformation]::GetInternetConnectionProfile()
    if ($null -eq $profile) {
        Write-Host "[hotspot] No active internet connection profile found."
        Print-Manual
        exit 0
    }

    $mgr = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager]::CreateFromConnectionProfile($profile)

    if ($mgr.TetheringOperationalState -eq [Windows.Networking.NetworkOperators.TetheringOperationalState]::On) {
        Write-Host "[hotspot] Hotspot already on."
        exit 0
    }

    Write-Host "[hotspot] Starting Mobile Hotspot..."
    $op = $mgr.StartTetheringAsync()
    $result = Wait-WinRtAsync $op ([Windows.Networking.NetworkOperators.NetworkOperatorTetheringOperationResult])

    if ($result.Status -eq [Windows.Networking.NetworkOperators.TetheringOperationStatus]::Success) {
        Write-Host "[hotspot] Mobile Hotspot started."
        exit 0
    }
    else {
        Write-Host ("[hotspot] StartTetheringAsync returned status: " + $result.Status)
        Print-Manual
        exit 0
    }
}
catch {
    Write-Host ("[hotspot] Exception: " + $_.Exception.Message)
    Print-Manual
    exit 0
}
