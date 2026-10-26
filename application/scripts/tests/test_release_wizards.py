"""Exercise wizard guards without executing build, cloud or service operations."""

import io
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]


def functions(name):
    return (SCRIPTS / name).read_text().rsplit('\nmain "$@"', 1)[0]


def shell(body, name="epm-release-vm.sh"):
    return subprocess.run(
        ["bash", "-c", functions(name) + "\n" + body],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("name", ["epm-release-mac.sh", "epm-release-vm.sh"])
def test_syntax_help_and_noninteractive_guard(name):
    script = SCRIPTS / name
    subprocess.run(["bash", "-n", str(script)], check=True)
    result = subprocess.run(
        ["bash", str(script), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    result = subprocess.run(["bash", str(script)], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "Stopped:" in result.stderr


@pytest.mark.parametrize("name", ["epm-release-mac.sh", "epm-release-vm.sh"])
@pytest.mark.parametrize("value", ["release-20261026-01", "release-20261026-100"])
def test_valid_release_identifier(name, value):
    assert shell(f"valid_release {shlex.quote(value)}", name).returncode == 0


@pytest.mark.parametrize("value", ["../other", "RELEASE", "release-20261026-1", "a;touch bad"])
def test_invalid_release_identifier(value):
    assert shell(f"valid_release {shlex.quote(value)}").returncode != 0


@pytest.mark.parametrize("instance,port", [("a", 8001), ("b", 8002)])
def test_instance_selection_generates_matching_paths(instance, port):
    result = shell(
        f'ask() {{ printf -v "$1" %s {instance}; }}\n'
        "write_env() { :; }\nselect_instance\n"
        'printf "%s\\n" "$local_config" "$deployment" "$unit" "$port" "$dropin"'
    )
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        f"/var/lib/epm-{instance}/hosted-local.json",
        f"/etc/epm/hosted-{instance}.json",
        f"epm-hosted@{instance}.service",
        str(port),
        f"/etc/systemd/system/epm-hosted@{instance}.service.d/90-release.conf",
    ]


def command(config="b", deployment="b", port=8002):
    python = "/opt/epm/releases/release-20261026-01/venv/bin/python"
    return (
        f"{{ path={python} ; argv[]={python} -m app "
        f"--config /var/lib/epm-{config}/hosted-local.json serve-hosted "
        f"--deployment /etc/epm/hosted-{deployment}.json --port {port} ; }}"
    )


@pytest.mark.parametrize(
    "config,deployment,port", [("a", "b", 8002), ("b", "a", 8002), ("b", "b", 8001)]
)
def test_b_rejects_a_paths_and_wrong_port(config, deployment, port):
    result = check_b_command(command(config, deployment, port))
    assert result.returncode != 0


def check_b_command(value):
    return shell(
        "local_config=/var/lib/epm-b/hosted-local.json\n"
        "deployment=/etc/epm/hosted-b.json\nport=8002\n"
        f"check_exec {shlex.quote(value)} /opt/epm/releases/release-20261026-01/venv/bin/python"
    )


def test_b_accepts_its_exact_effective_command():
    assert check_b_command(command()).returncode == 0


@pytest.mark.parametrize("path", ["/usr/bin/python", "/opt/epm/releases/RELEASE/../bad/python"])
def test_current_interpreter_rejects_unrecognized_paths(path):
    assert shell(f"runtime_from_exec {shlex.quote('{ path=' + path + ' ; }')}").returncode != 0


def test_missing_hosted_cli_is_rejected():
    result = shell('as_owner() { echo "backup serve workspace-status"; }; cli_check /old/python')
    assert result.returncode != 0
    assert "not the hosted CLI" in result.stderr


def make_archive(path, extra=None):
    names = {
        "SHA256SUMS": b"manifest",
        "SOURCE_COMMIT.txt": b"source",
        "TEST_EVIDENCE.txt": b"test",
        "stage_schema_resources.py": b"pass",
        "verify_installation.py": b"pass",
        "release-vm.sh": b"shell",
        "schema-resources/alembic.ini": b"ini",
        "schema-resources/database/sqlite-migrations/versions/0001.py": b"pass",
        "easy_property_management-0.1.0-py3-none-any.whl": b"wheel",
    }
    if extra:
        names.update(extra)
    with tarfile.open(path, "w:gz") as archive:
        for name, data in names.items():
            member = tarfile.TarInfo("./" + name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))


def check_archive(path):
    return shell(
        f"previous_python={shlex.quote(sys.executable)}\narchive={shlex.quote(str(path))}\n"
        "archive_check"
    )


def test_normalized_archive_paths_are_checked_without_extraction(tmp_path):
    path = tmp_path / "release.tar.gz"
    make_archive(path)
    assert check_archive(path).returncode == 0
    assert sorted(item.name for item in tmp_path.iterdir()) == ["release.tar.gz"]


@pytest.mark.parametrize(
    "extra",
    [
        {"../outside": b"bad"},
        {"schema-resources/database/sqlite-migrations/versions/._0001.py": b"\0"},
        {"schema-resources/database/sqlite-migrations/versions/0001.py": b"\0"},
        {"__pycache__/bad.pyc": b"bad"},
    ],
)
def test_unsafe_or_corrupt_archive_is_rejected_before_extraction(tmp_path, extra):
    path = tmp_path / "release.tar.gz"
    make_archive(path, extra)
    assert check_archive(path).returncode != 0


def test_stopped_failed_state_is_cleared_only_without_a_process():
    result = shell(
        "unit=epm-hosted@b.service\n"
        'sudo() { case "$*" in *ActiveState*) echo failed;; *MainPID*) echo 0;; '
        "*reset-failed*) echo reset;; *) return 1;; esac; }\nensure_stopped"
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "reset"
    result = shell(
        "unit=epm-hosted@b.service\n"
        'sudo() { case "$*" in *ActiveState*) echo failed;; *MainPID*) echo 123;; '
        "*) echo unexpected;; esac; }\nensure_stopped"
    )
    assert result.returncode != 0
    assert "unexpected" not in result.stdout


def test_readiness_does_not_accept_a_transient_active_process():
    result = shell(
        "unit=epm-hosted@a.service\nhost=demo-a.example.com\nport=8001\n"
        'sudo() { case "$*" in *is-active*) return 0;; *MainPID*) echo 44;; '
        "*NRestarts*) echo 1;; *) return 1;; esac; }\n"
        'curl() { case "$*" in */sign-in*) echo 200;; *) echo 401;; esac; }\n'
        "sleep() { :; }\nreadiness"
    )
    assert result.returncode != 0
    assert "restarted during readiness" in result.stderr


def test_rejected_acceptance_fences_and_stops_the_writer():
    result = shell(
        "origin=https://demo-a.example.com\ndeployment=/etc/epm/hosted-a.json\n"
        "unit=epm-hosted@a.service\n"
        'ask() { printf -v "$1" %s "not accepted"; }\n'
        "confirm() { return 1; }\n"
        'as_owner() { printf "owner: %s\\n" "$*"; }\n'
        'sudo() { printf "sudo: %s\\n" "$*"; }\n'
        "browser_acceptance /new/python"
    )
    assert result.returncode != 0
    assert "hosted-admin /etc/epm/hosted-a.json disable" in result.stdout
    assert "systemctl stop epm-hosted@a.service" in result.stdout


def test_resume_does_not_repeat_backup_or_override_switch():
    result = shell(
        "select_release() { next=/opt/epm/releases/release-20261026-01; }\n"
        "select_instance() { unit=epm-hosted@b.service; "
        "local_config=/var/lib/epm-b/hosted-local.json; "
        "deployment=/etc/epm/hosted-b.json; port=8002; }\n"
        "select_record() { record=/saved; }\n"
        "read_origin() { :; }\nreadiness() { echo ready; }\n"
        "activate_operator() { echo activated; }\nbrowser_acceptance() { echo accepted; }\n"
        f'sudo() {{ case "$*" in *"test -s"*|*"systemctl is-active"*) return 0;; '
        f'*"systemctl show"*) printf "%s\\n" {shlex.quote(command())};; '
        '*) die "Unexpected mutation: $*";; esac; }\nresume_release'
    )
    assert result.returncode == 0
    assert "ready\n" in result.stdout
    assert "activated\n" in result.stdout
    assert "accepted\n" in result.stdout


def test_archive_links_are_rejected(tmp_path):
    path = tmp_path / "release.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo("link")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/shadow"
        archive.addfile(member)
    assert check_archive(path).returncode != 0


def test_wizard_libraries_remain_identical():
    mac = (SCRIPTS / "epm-release-mac.sh").read_text().split("# STAGES:")[0]
    vm = (SCRIPTS / "epm-release-vm.sh").read_text().split("# STAGES:")[0]
    assert mac == vm


@pytest.mark.skipif(sys.platform != "darwin", reason="Tests the Mac system tar metadata flags")
def test_mac_archive_does_not_generate_appledouble_sidecars(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    migration = source / "0001.py"
    migration.write_text("pass\n")
    subprocess.run(
        ["xattr", "-wx", "com.apple.FinderInfo", "01" + "00" * 31, str(migration)], check=True
    )
    archive = tmp_path / "release.tar.gz"
    subprocess.run(
        ["tar", "--disable-copyfile", "-czf", str(archive), "-C", str(source), "."],
        env={**os.environ, "COPYFILE_DISABLE": "1"},
        check=True,
    )
    with tarfile.open(archive) as contents:
        assert not any(Path(member.name).name.startswith("._") for member in contents)
