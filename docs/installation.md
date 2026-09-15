# Installing Loom on macOS, Linux, and Windows

This guide installs the Loom command as an isolated user-level tool and stages
the browser extension for Chrome's **Load unpacked** workflow. It does not
install the Loom API, PostgreSQL, or Redis; normal users connect to the hosted
API.

## Requirements

- Git
- Python 3.11 or newer
- Google Chrome or another Chromium browser that supports unpacked extensions
- A supported terminal: Bash on macOS/Linux or PowerShell on Windows

On Windows, select **Add python.exe to PATH** in the Python installer. The
Python launcher (`py`) is also detected automatically.

## 1. Clone one reviewed revision

```bash
git clone https://github.com/rj-Anurag/Loom.git
cd Loom
```

For a controlled deployment, check out a release tag instead of a moving
branch:

```bash
git fetch --tags
git checkout tags/vX.Y.Z
```

Only install revisions obtained from a trusted repository or release. The
installers intentionally avoid `sudo`, elevation, and machine-wide Python
changes.

## 2. Install the Loom CLI

### macOS or Linux

```bash
./install.sh
```

If the executable bit was removed while transferring the repository, use:

```bash
bash install.sh
```

### Windows PowerShell

```powershell
.\install.ps1
```

The scripts install `pipx` for the current user when it is missing, install the
current Loom checkout into an isolated environment, and update the user PATH
through `pipx ensurepath`. Close and reopen the terminal after the first
installation, then verify the exact installed version:

```bash
loom --version
loom --help
```

The install source may be explicitly selected when automating a deployment:

```bash
./install.sh --source /absolute/path/to/Loom --python python3.12
```

```powershell
.\install.ps1 -Source "C:\src\Loom" -Python "python.exe"
```

`LOOM_INSTALL_SOURCE` and `LOOM_PYTHON` are equivalent environment-variable
overrides. Sources may be a checkout path, wheel, source archive, or a pip-compatible
Git URL. Do not place credentials in a Git URL passed to a shared shell history.

## 3. Stage and load the unpacked extension

The checked-in `extension/` directory is a source template and deliberately
contains a non-working OAuth placeholder. Stage a production-ready copy first:

```bash
loom extension install --api-url https://loom-api-zzy0.onrender.com
loom extension status --check-api
loom extension path
```

The command copies the extension to the current user's Loom configuration
directory, injects the Chrome OAuth client ID published by the selected server,
removes default credentials, and limits API host access to that server. The
default paths are:

- macOS and Linux: `~/.loom/extension`
- Windows: `%USERPROFILE%\.loom\extension`

In Chrome:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Select the exact directory printed by `loom extension path`.
5. Pin Loom from the extensions menu if desired.

For a self-hosted server, replace the URL. That server must expose its Chrome
OAuth client configuration and allow the extension origin:

```bash
loom extension install --api-url https://loom.example.com
loom extension status --check-api
```

## 4. Connect a project

Run these commands inside the software repository whose context should be
shared:

```bash
loom login
loom init "My Project" --install all
```

Then open the Loom extension, continue with the same Google account, select the
project, and link a supported AI conversation. Credentials remain in the user
configuration directory and browser storage; they are not written into the
cloned Loom repository or the connected software repository.

## Upgrade

Review the incoming changes, update the checkout, and rerun the installer:

```bash
git pull --ff-only
./install.sh
loom extension install --api-url https://loom-api-zzy0.onrender.com --force
loom extension status --check-api
```

On Windows, replace `./install.sh` with `.\install.ps1`. Return to
`chrome://extensions` and select the reload button on the Loom extension.

For release-pinned deployments, check out the new release tag before rerunning
the installer.

## Uninstall

```bash
pipx uninstall loom
```

Remove Loom from `chrome://extensions` separately. User configuration and
browser data are retained intentionally so an accidental uninstall does not
destroy credentials or queued context. Delete the per-user `.loom` directory
only when that data is no longer needed.

## Troubleshooting

- **`loom` is not found:** restart the terminal after installation, then run
  `pipx ensurepath` and open another terminal.
- **Python is too old:** install Python 3.11 or newer and pass its executable
  using `--python` or `-Python`.
- **Extension status reports an OAuth error:** confirm the API URL is correct
  and that the server has `GOOGLE_EXTENSION_CLIENT_ID` configured, then rerun
  `loom extension install ... --force`.
- **Chrome still runs an older extension:** select reload on
  `chrome://extensions`; the unpacked directory remains stable across upgrades.
- **Corporate endpoint controls block scripts:** perform the equivalent manual
  user-level installation with `python -m pip install --user pipx`, `pipx
  ensurepath`, and `pipx install /absolute/path/to/Loom`.
