# PR Lab 1

Run these commands from the `Lab1` directory.

## Build and prepare data

```powershell
dotnet build .\Labs.sln -c Release
dotnet run -c Release -- hardware
dotnet run -c Release -- generate
dotnet run -c Release -- split
```

## Task 1a

```powershell
dotnet run -c Release -- 1a --threads 1
dotnet run -c Release -- 1a --threads 2
dotnet run -c Release -- 1a --threads 4
dotnet run -c Release -- 1a --threads 8
dotnet run -c Release -- 1a --threads 16
dotnet run -c Release -- 1a --threads 32
dotnet run -c Release -- 1a --threads 64
```

## Task 1b

```powershell
dotnet run -c Release -- 1b
```

## Task 1c

```powershell
dotnet run -c Release -- 1c --workers 1
dotnet run -c Release -- 1c --workers 2
dotnet run -c Release -- 1c --workers 4
dotnet run -c Release -- 1c --workers 8
dotnet run -c Release -- 1c --workers 16
dotnet run -c Release -- 1c --workers 32
dotnet run -c Release -- 1c --workers 64
```

## Copy files to USB

```powershell
New-Item -ItemType Directory -Force "F:\Lab1Parts"
robocopy ".\data\parts" "F:\Lab1Parts" part_*.txt /J /R:2 /W:2
```

## Verify USB files

```powershell
1..8 | ForEach-Object {
    $local = Get-FileHash ".\data\parts\part_$_.txt" -Algorithm SHA256
    $usb = Get-FileHash "F:\Lab1Parts\part_$_.txt" -Algorithm SHA256
    [PSCustomObject]@{
        File = "part_$_.txt"
        Same = $local.Hash -eq $usb.Hash
    }
}
```

## Task 2

```powershell
dotnet run -c Release -- 2 --threads 1 --dir "F:\Lab1Parts"
dotnet run -c Release -- 2 --threads 2 --dir "F:\Lab1Parts"
dotnet run -c Release -- 2 --threads 4 --dir "F:\Lab1Parts"
dotnet run -c Release -- 2 --threads 8 --dir "F:\Lab1Parts"
dotnet run -c Release -- 2 --threads 16 --dir "F:\Lab1Parts"
dotnet run -c Release -- 2 --threads 32 --dir "F:\Lab1Parts"
dotnet run -c Release -- 2 --threads 64 --dir "F:\Lab1Parts"
```
