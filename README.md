# Game Launcher

Windows game launcher for Steam/Epic libraries.

## Download (for users)
- Go to the **Releases** page of this repo.
- Download `GameLauncher-portable-windows.zip`.
- Extract it anywhere.
- Run `GameLauncher.exe`.

## Build portable locally (for you)
From the project root:

```powershell
.\build_portable.ps1
```

The output zip is:
- `release/GameLauncher-portable-windows.zip`

## Auto-build on GitHub
This repo includes a GitHub Actions workflow that builds a portable Windows ZIP.

To publish a new downloadable version:

```powershell
& ''C:\Program Files\Git\cmd\git.exe'' add .
& ''C:\Program Files\Git\cmd\git.exe'' commit -m "Release v1.0.0"
& ''C:\Program Files\Git\cmd\git.exe'' tag v1.0.0
& ''C:\Program Files\Git\cmd\git.exe'' push origin main --tags
```

When the `v*` tag is pushed, GitHub Actions builds and attaches
`GameLauncher-portable-windows.zip` to that release tag.
