# Installation and setup

[Manual contents](README.md) · [Deploy a release wheel on a new VM](deployment.md)

These steps are for the installer/product owner. The current release uses a local checkout and terminal commands; it does not have a self-service desktop installer. The Python wheel contains backend code and compiled web assets, but workspace schema resources still depend on the checkout. Retain the complete supplied checkout.

## 1. Prepare the application

Obtain the approved application checkout from the product owner. You need Python 3.12 or newer, Node.js 22.13 or newer with npm, and `uv` on PATH to build it. Use the machine's approved installation method for those tools. Node is needed for building, not everyday serving of compiled assets.

### Install Python dependencies and build the wheel

From the repository root:

```bash
cd application
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
export EPM_PYTHON="$PWD/.venv/bin/python"
./scripts/build_wheel.sh --install-deps
```

The script installs locked Node dependencies with `npm ci`, runs lint/format/type checks, validates generated contracts, builds React and packages it with Python. It then checks the wheel's Python entry point, compiled assets and archive integrity. Successful completion prints **Wheel ready:** followed by the absolute artifact path under `application/dist/`.

The filename currently follows `easy_property_management-<version>-py3-none-any.whl`; the version comes from `application/pyproject.toml`. The script does not install the wheel, copy assets into the running checkout, initialize a workspace or change live configuration. Complete asset staging and workspace setup below.

### Rebuild and select the interpreter

For subsequent builds, from the repository root:

```bash
./application/scripts/build_wheel.sh
```

Or from `application/`:

```bash
./scripts/build_wheel.sh
```

Use `--install-deps` after dependency/lockfile changes or for a fresh Node installation. The script locates its application directory automatically; invocation from another folder requires the appropriate path to the script. Use `--help` for options.

Python discovery uses `EPM_PYTHON` if set, then `application/.venv/bin/python`, then the repository's `.venv/easy-property-management/bin/python`. To choose a different prepared environment, set `EPM_PYTHON` to its interpreter's absolute path. It must have the project's Python dependencies installed; the script does not install them.

### Build errors

- **Missing tool/environment:** install the reported prerequisite or select the prepared interpreter; then rerun the script.
- **Lint, formatting or type-check failure:** packaging stops. Have the release maintainer correct the reported files and rerun the same script. Do not assume an existing wheel in `dist` belongs to the failed build. The initial script validation reported formatting issues in `application/demo/dataset.json` and `application/demo/README.md`; the current check output is authoritative.
- **Stale generated contracts:** ask the release maintainer to regenerate and review the contract changes before rebuilding.
- **Missing offline Python build dependency:** the packager uses `uv build --offline`. From `application/`, run `uv build --wheel` once with network access to populate the build cache, then rerun `./scripts/build_wheel.sh`. The cache-warming wheel is not the final combined artifact; use the wheel from a successful script run.

See [production packaging](../README.md#production-build-and-packaging-instructions) for artifact inspection and the wheel-only runtime limitation.

### Stage the frontend for the checkout runtime

For serving from this checkout, stage the freshly built public frontend in the source Python package. Run from `application/` after packaging succeeds, with the server stopped:

```bash
python scripts/stage_frontend.py
```

The script works independently of the current directory when invoked by its path. It validates public assets using the same rules as wheel packaging, prepares the replacement before changing the existing build, and prints the staged location. It replaces generated web assets only; it does not build them, start the server or change configuration/workspace records. Run it after each successful frontend release with the server stopped. Keep records and attachments outside the checkout.

## 2. Select the external workspace

Choose a local folder outside the application checkout for real records, for example `/Users/your-name/Property-Management-Data/live`. Use a different folder for the demo and a separate destination for backups. Live SQLite data must not sit on an unsupported network share or cloud-sync folder.

Create `application/config.local.json` in a text editor. Do not overwrite an existing configuration without first recording its workspace location. A minimal local configuration is:

```json
{
  "localWorkspacePath": "/Users/your-name/Property-Management-Data/live",
  "fileStorageProvider": "local"
}
```

Replace the example path with your full absolute path. Keep JSON quotation marks and commas valid. Do not put credentials or passphrases in this file.

For a **new** empty workspace, run from `application/` with the environment active:

```bash
python -m app --config "$PWD/config.local.json" initialize-workspace
python -m app --config "$PWD/config.local.json" workspace-status
```

For an **existing** workspace, point the configuration at that folder and run `workspace-status`; do not initialize a replacement to work around an error. Initialization creates the manifest, database and managed folders. It refuses an unrelated populated folder. Use [restore](data-and-recovery.md#restore-a-backup) when recovering an archive.

## 3. Start and open

From `application/`:

```bash
source .venv/bin/activate
python -m app --config "$PWD/config.local.json" serve --port 8000
```

Open [http://127.0.0.1:8000/home](http://127.0.0.1:8000/home) on the same computer. Keep the terminal running. For another port use, for example, `--port 8001` and open that same port in the browser. Do not use development-origin flags for normal operation.

Check that the intended workspace opens, Properties shows the expected records and Home has current availability/checked times. A loading or unavailable section is not an empty result. Configure a [backup destination](data-and-recovery.md) before entering substantial records.

## 4. Stop and restart

Finish or save open forms, check uncertain outcomes, then press **Ctrl+C in the server terminal**. Closing the browser alone does not stop the server. Start it again with the same command and configuration. Opening a second server on the same workspace can report Busy; stop the first instance rather than deleting lock files.

## 5. Practice with synthetic data

Use the separate [demo instructions](../application/demo/README.md). From `application/`, with this environment active, `python demo/serve.py` opens the already generated demo on port 8001. If it has not been generated, follow the demo's seed instructions into a new empty external folder. Never aim the generator at live records. Demo dates age normally; no real payments/messages are sent.

## Update an installed checkout

1. Save work, reconcile uncertain attempts and create a validated encrypted backup.
2. Stop the server and preserve the live config, external workspace and backup passphrase.
3. Have the installer apply the approved release and reinstall its Python dependencies. Run `./application/scripts/build_wheel.sh --install-deps` from the repository root, require successful wheel verification, then restage the frontend using the steps above.
4. Run `workspace-status` before starting the server. If schema/format is unsupported, stop and contact the product owner. Current greenfield releases accept only their supported latest format; no automatic legacy upgrade path is promised.
5. Start, inspect known records and check unfinished forms before resuming work.

Do not delete a workspace to make an update pass. A backup and the matching compatible application release are the recovery path.
