# Deploy a release wheel on a new VM

[Manual contents](README.md) · [Build from a checkout](installation.md)

For updates to the already-configured Google Cloud hosted demo, use the
[ongoing Google Cloud runbook](../docs/hosting/operations/GOOGLE_CLOUD_ONGOING_RUNBOOK.md).
The installation below describes a new local-mode VM, not that hosted service.

This guide starts with a built release wheel and a clean VM. It is for the installer, not the daily operator. The commands below use a **Linux VM with Ubuntu 24.04**, a normal login user with sudo rights, and network access to install Python dependencies. Other supported hosts need equivalent Python/virtual-environment provisioning.

The application remains a single-operator local application. Use a browser in the VM's desktop session through your VM console/approved desktop access. The server binds to `127.0.0.1`; this guide does not publish it as a remote website. A headless VM without a way to use a browser in that environment needs a separately approved access arrangement.

## Release contents required before deployment

**The current wheel alone is insufficient.** It contains Python modules and `app/web_build`, but omits the schema files that startup/workspace validation locates relative to the installed Python package. Get the following matching release bundle from the release maintainer:

```text
release/
├── easy_property_management-0.1.0-py3-none-any.whl
├── stage_schema_resources.py
├── verify_installation.py
├── configure_workspace.py
└── schema-resources/
    ├── alembic.ini
    └── database/
        └── sqlite-migrations/          # complete folder from the same source release
            ├── env.py
            └── versions/...
```

The version is an example; use your supplied filename. The three standalone helper scripts and schema files must come from the exact source revision used to build the wheel. A wheel filename/version alone does not establish that pairing when releases reuse a version. Ask for a release identifier and checksums, and verify the transferred files against those supplied values.

No source checkout, Node, npm, `uv`, frontend build or frontend staging is needed **on the VM** when the wheel contains the compiled frontend and the matching schema resources are supplied. This guide explicitly stages the missing resources in the dedicated environment's currently derived application root. It is an installation workaround for the present package layout, not a wheel-only installer; a future packaging change should include and locate those resources within the distribution.

## 1. Provision Python and a dedicated directory

In the VM terminal:

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv python3-pip
python3 --version
mkdir -p "$HOME/epm/artifacts" "$HOME/epm/config" "$HOME/epm/data"
chmod 700 "$HOME/epm" "$HOME/epm/config" "$HOME/epm/data"
```

Verify Python is **3.12 or newer** before continuing. Run the application as this login user, not root. Use a supported local VM disk for live SQLite data. Select a separate supported backup volume/destination; snapshots of only a running database file are not the app's backup procedure.

Transfer the trusted bundle into `$HOME/epm/artifacts/`. The wheel should be directly in that folder, and `schema-resources/` alongside it. Do not transfer live configuration, credentials or customer records as part of the application artifact.

## 2. Install the wheel

```bash
python3 -m venv "$HOME/epm/runtime"
source "$HOME/epm/runtime/bin/activate"
python -m pip install "$HOME/epm/artifacts/easy_property_management-0.1.0-py3-none-any.whl"
python -m pip check
```

Substitute the supplied version in the filename. Pip installs runtime dependencies from the configured index. Do not install the project editable, its development extras, or the source repository on this VM.

For a VM without package-index access, have the release maintainer also supply a dependency wheelhouse built/downloaded for the target OS, architecture and Python version. Then use:

```bash
python -m pip install --no-index --find-links "$HOME/epm/artifacts/wheelhouse" \
  "$HOME/epm/artifacts/easy_property_management-0.1.0-py3-none-any.whl"
```

A macOS wheelhouse cannot be assumed to contain the Linux dependencies. Keep the supplied dependency versions with the release record; this app wheel's dependency ranges are not a fully locked environment.

## 3. Stage the matching schema resources

Keep the environment active. The [schema staging script](../application/scripts/stage_schema_resources.py) determines the installed application's schema-resource location; you do not need to compute it manually.

```bash
python "$HOME/epm/artifacts/stage_schema_resources.py" \
  "$HOME/epm/artifacts/schema-resources"
```

It requires a virtual environment and an application installed inside it, validates the supplied resources, refuses existing destination resources, and prints the staged location. It prepares copies before publication; it does not initialize or open a workspace. Supply the exact matching release bundle—these checks do not independently prove source-revision pairing.

Do not copy into the global Python installation. Use a new dedicated environment for another release; matching schema resources must not be silently overwritten by a different release. If staging fails, inspect the safe failure message before retrying; do not manually bypass its destination checks.

## 4. Verify the installed release files

```bash
python "$HOME/epm/artifacts/verify_installation.py"
```

The [verification script](../application/scripts/verify_installation.py) checks installed frontend assets and schema discovery, and prints the package version, module location and schema revision. A failed check exits with a failure message. It does not replace workspace initialization, browser acceptance or an actual restore trial.

## 5. Configure the external workspace

Create a new configuration without overwriting an existing one:

```bash
python "$HOME/epm/artifacts/configure_workspace.py" \
  --config "$HOME/epm/config/config.local.json" \
  --workspace "$HOME/epm/data/live"
```

The [configuration script](../application/scripts/configure_workspace.py) requires absolute paths, creates a private locator file and refuses to overwrite an existing file. It does not create/initialize the selected workspace or change existing records. If a locator already exists, review its intended workspace instead of recreating it blindly.

The workspace is outside the Python runtime, so replacing an environment does not replace records. Configuration is explicitly passed to every command because the package's default config location is unsuitable for this deployment layout.

For a **new empty workspace**:

```bash
python -m app --config "$HOME/epm/config/config.local.json" initialize-workspace
python -m app --config "$HOME/epm/config/config.local.json" workspace-status
```

For **restoring existing records**, do not initialize first. Validate/restore the archive into a new external folder, then point this configuration at it and run `workspace-status`. Follow [restore instructions](data-and-recovery.md#restore-a-backup), adding `--config "$HOME/epm/config/config.local.json"` before each command. Supply backup passphrases through the prompt, never in command arguments or config. Configure fresh device credentials after restore when needed.

## 6. Start and accept the deployment

```bash
python -m app --config "$HOME/epm/config/config.local.json" serve --port 8000
```

In the **VM browser**, open [http://127.0.0.1:8000/home](http://127.0.0.1:8000/home). Keep the terminal running; Ctrl+C stops it. From a new terminal, activate `$HOME/epm/runtime/bin/activate` before using the same launch command.

Installer acceptance checklist:

- The intended workspace opens. An empty new portfolio is distinguishable from an unavailable read.
- Home, Properties and Settings load the compiled UI, not `web_build_unavailable`.
- Current Home checks work and errors are visible; no cron or model provider is required.
- A deliberate harmless preference change saves and remains after restart.
- A backup can be created/validated and restored into a separate trial destination before relying on recovery.
- Live workspace and backup paths are documented for the operator; runtime replacement does not touch them.

The app has no application login in this local mode. Keep access within the approved VM desktop context. Do not bind a substitute server to `0.0.0.0`, add a public reverse proxy or use a development-origin exception to turn it into a hosted product.

## 7. Backups, credentials and routine operation

Use [data protection](data-and-recovery.md) with the explicit VM config path. For example, after stopping the server:

```bash
python -m app --config "$HOME/epm/config/config.local.json" \
  configure-backup-destination /absolute/path/to/separate-backup-destination
python -m app --config "$HOME/epm/config/config.local.json" backup
```

Check the destination's filesystem support; keep completed encrypted archives outside the VM's sole failure domain where possible. A provider/VM snapshot does not substitute for the application's consistent encrypted archive and restore validation.

Manual backups need a passphrase prompt. Automatic backup and AI credentials use the operating-system credential store; a fresh/headless Linux VM may lack an available/unlocked backend. Have the installer verify it in the actual execution session before enabling those features. Do not work around a missing store by putting secrets in config or scripts. Automatic backups depend on the app running. Dashboard cron remains post-MVP.

This guide uses foreground execution. Unattended startup/service management is a separate device setup choice that must preserve the same user, explicit config, single server instance, private access and required credential-store availability.

## 8. Deploy a replacement release

1. Save/reconcile work, make and validate an encrypted backup, and stop the current server.
2. Transfer the replacement wheel and its exact matching schema bundle.
3. Create a **new** dedicated environment, install the replacement wheel, and stage/verify its resources using the same procedure with that new environment active.
4. Run `workspace-status` against the existing explicit config before starting. If schema/format is unsupported, stop; do not initialize or alter records to bypass validation. This greenfield app has no promised legacy upgrade path.
5. Start exactly one server, repeat the acceptance checks and retain the previous compatible environment plus backup until verified.

Rollback requires a compatible application and data set. Do not launch an older environment against a workspace that a newer incompatible release changed; restore the appropriate validated backup into a separate folder and explicitly select it.

## Release maintainer: supply the missing schema bundle

On the build machine, after producing the combined wheel from the approved source revision, run from `application/`:

```bash
mkdir -p dist/schema-resources/database
cp alembic.ini dist/schema-resources/alembic.ini
cp -R database/sqlite-migrations dist/schema-resources/database/
cp scripts/stage_schema_resources.py scripts/verify_installation.py \
  scripts/configure_workspace.py dist/
```

Use a fresh `schema-resources` destination for each release; do not merge folders from different builds. Transfer that folder and all three helper scripts alongside the final wheel and a trusted release/checksum record. The scripts use the installed application or standard library directly and do not require the source checkout on the VM. No schema initialization should take place against customer data on the build machine.

This deployment procedure is based on the current package layout; a fresh VM deployment was not executed while writing the guide. The explicit installed-resource, workspace and browser checks above are required before handing over the VM.
