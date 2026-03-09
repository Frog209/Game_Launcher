# Game Launcher

A portable Windows launcher for Steam and Epic games with cover art, collections, filters, and quick launch.

## Features
- Detects Steam and Epic game libraries
- Grid view with cover art and hover details
- Manual and dynamic collections
- Sort and filter options (including Installed Only)
- Optional Steam API integration for richer metadata
- Portable build with no installer required

## Download (Windows)
1. Open the repo **Releases** page.
2. Download `GameLauncher-portable-windows.zip` from the latest version.
3. Extract the zip anywhere you want.
4. Run `GameLauncher.exe`.

## First-Time Setup
- On first launch, the app can ask whether to create a desktop shortcut.
- Steam API credentials are optional. You can add them from **Integrations** in the app if you want richer Steam metadata.
- The app creates its local data files on first run.

## Build Portable Locally
From the project root:

```powershell
.\build_portable.ps1
```

Output:
- `release/GameLauncher-portable-windows.zip`

## Release Workflow (Maintainer)
A GitHub Actions workflow builds the Windows portable zip when a version tag is pushed.

Example:

```powershell
& 'C:\Program Files\Git\cmd\git.exe' add .
& 'C:\Program Files\Git\cmd\git.exe' commit -m "Release v1.0.3"
& 'C:\Program Files\Git\cmd\git.exe' tag v1.0.3
& 'C:\Program Files\Git\cmd\git.exe' push origin main
& 'C:\Program Files\Git\cmd\git.exe' push origin v1.0.3
```
