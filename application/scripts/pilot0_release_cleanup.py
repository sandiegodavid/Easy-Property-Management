"""Conservative Pilot 0 host release cleanup helper.

Inspects and safely removes unused Docker containers, unused Docker images,
Docker build cache, temporary build artifacts in /tmp, and unreferenced
qualification/staging directories under /opt/epm.

Never touches running containers, the active Admin MANIFEST image, the offline
Python build base image, active/latest qualified_releases catalog entries,
explicitly retained rollback images, or any workspace/control/backup data under
/srv/epm/data.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import subprocess
from typing import Iterable

OPT_ROOT = Path("/opt/epm")
TMP_ROOT = Path("/tmp")
ADMIN_RUN_IDENTITY = Path("/opt/epm/h0312/run_identity.py")
ADMIN_SQLITE = Path("/srv/epm/data/host/h0312-identity/admin.sqlite")

CORE_OPT_PROTECTED = frozenset(
    {
        "agent-bundle",
        "demo",
        "h0312",
        "host-agent",
        "pilot0",
        "python",
        "tools",
    }
)

OPT_REFERENCE_ROOTS = (
    Path("/etc/systemd/system"),
    Path("/usr/lib/systemd/system"),
    Path("/run/systemd/system"),
    Path("/etc/epm"),
    Path("/opt/epm/h0312"),
    Path("/opt/epm/pilot0"),
)

OPT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MANIFEST_RE = re.compile(r'^MANIFEST\s*=\s*"([0-9a-f]{64})"$', re.MULTILINE)
CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

MIN_SHORT_ID_LEN = 12
DU_COLUMNS = 2
MOUNTINFO_MIN_FIELDS = 5


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def normalize_digest(value: str) -> str:
    raw = value.strip().lower()
    if raw.startswith("sha256:"):
        raw = raw[7:]
    if re.fullmatch(r"[0-9a-f]{64}", raw):
        return f"sha256:{raw}"
    return value.strip()


@dataclass(frozen=True)
class ContainerRecord:
    container_id: str
    name: str
    image_id: str
    image_ref: str
    status: str
    running: bool


@dataclass(frozen=True)
class ImageRecord:
    image_id: str
    repository: str
    tag: str
    size: str
    created_at: str

    @property
    def short_id(self) -> str:
        raw = self.image_id[7:] if self.image_id.startswith("sha256:") else self.image_id
        return raw[:12]

    @property
    def display_ref(self) -> str:
        if self.repository == "<none>" or self.tag == "<none>":
            return f"{self.repository}:{self.tag}"
        return f"{self.repository}:{self.tag}"

    @property
    def remove_target(self) -> str:
        if self.repository != "<none>" and self.tag != "<none>":
            return f"{self.repository}:{self.tag}"
        return self.image_id


@dataclass
class ClassifiedImage:
    record: ImageRecord
    reasons: list[str] = field(default_factory=list)

    @property
    def protected(self) -> bool:
        return bool(self.reasons)


@dataclass
class ClassifiedOptDir:
    name: str
    size: str
    reasons: list[str] = field(default_factory=list)

    @property
    def protected(self) -> bool:
        return bool(self.reasons)


@dataclass(frozen=True)
class ImageProtectionContext:
    admin_manifest_digest: str | None = None
    catalog_latest_digests: tuple[str, ...] = ()
    catalog_referenced_digests: tuple[str, ...] = ()
    keep_refs: tuple[str, ...] = ()


def matches_image_ref(image: ImageRecord, ref: str) -> bool:
    candidate = ref.strip()
    if not candidate:
        return False
    if candidate in {image.display_ref, image.image_id}:
        return True
    if normalize_digest(candidate) == image.image_id:
        return True
    raw_id = image.image_id[7:] if image.image_id.startswith("sha256:") else image.image_id
    raw_cand = candidate[7:] if candidate.startswith("sha256:") else candidate
    if len(raw_cand) >= MIN_SHORT_ID_LEN and re.fullmatch(r"[0-9a-f]+", raw_cand.lower()):
        return raw_id.startswith(raw_cand.lower())
    return False


@dataclass(frozen=True)
class _NormalizedProtection:
    running_by_image: dict[str, list[str]]
    stopped_by_image: dict[str, list[str]]
    manifest: str | None
    latest_catalog: set[str]
    referenced_catalog: set[str]
    keep_list: list[str]


def _image_protection_reasons(img: ImageRecord, prot: _NormalizedProtection) -> list[str]:
    reasons: list[str] = []
    norm_id = normalize_digest(img.image_id)
    reasons.extend(
        f"running container: {n}" for n in sorted(prot.running_by_image.get(norm_id, ()))
    )
    if prot.manifest and norm_id == prot.manifest:
        reasons.append("active Admin MANIFEST (/opt/epm/h0312/run_identity.py)")
    if norm_id in prot.latest_catalog:
        reasons.append("latest qualified_releases catalog entry")
    if norm_id in prot.referenced_catalog:
        reasons.append("referenced by operator in admin.sqlite")
    if img.repository in {"python", "library/python"}:
        reasons.append("offline build base image (python)")
    matched_keep = next((ref for ref in prot.keep_list if matches_image_ref(img, ref)), None)
    if matched_keep is not None:
        reasons.append(f"explicit rollback retention ({matched_keep})")
    reasons.extend(
        f"pinned by stopped container: {n} (remove container first)"
        for n in sorted(prot.stopped_by_image.get(norm_id, ()))
    )
    return reasons


def classify_images(
    images: Iterable[ImageRecord],
    containers: Iterable[ContainerRecord],
    context: ImageProtectionContext | None = None,
) -> list[ClassifiedImage]:
    """Classify Docker images into protected vs removable."""
    ctx = context or ImageProtectionContext()
    running_by_image: dict[str, list[str]] = {}
    stopped_by_image: dict[str, list[str]] = {}
    for ctr in containers:
        norm_img = normalize_digest(ctr.image_id)
        target = running_by_image if ctr.running else stopped_by_image
        target.setdefault(norm_img, []).append(ctr.name)

    prot = _NormalizedProtection(
        running_by_image=running_by_image,
        stopped_by_image=stopped_by_image,
        manifest=(
            normalize_digest(ctx.admin_manifest_digest) if ctx.admin_manifest_digest else None
        ),
        latest_catalog={normalize_digest(d) for d in ctx.catalog_latest_digests if d},
        referenced_catalog={normalize_digest(d) for d in ctx.catalog_referenced_digests if d},
        keep_list=[k.strip() for k in ctx.keep_refs if k.strip()],
    )

    image_list = list(images)
    for ref in prot.keep_list:
        require(
            any(matches_image_ref(img, ref) for img in image_list),
            f"Retained rollback image not found on host: {ref}",
        )

    return [
        ClassifiedImage(record=img, reasons=_image_protection_reasons(img, prot))
        for img in image_list
    ]


def references_in(data: bytes, root: Path) -> set[str]:
    prefix = re.escape(str(root).encode())
    return {name.decode() for name in re.findall(prefix + rb"/([A-Za-z0-9][A-Za-z0-9._-]*)", data)}


def scan_path(path: Path) -> Iterable[tuple[Path, bytes]]:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        yield path, os.readlink(path).encode()
        return
    if path.is_file():
        try:
            yield path, path.read_bytes()
        except OSError:
            return
    elif path.is_dir():
        try:
            children = list(path.iterdir())
        except OSError:
            return
        for child in children:
            yield from scan_path(child)


def _protect_opt_entry(
    opt_root: Path,
    entry: Path,
    protect,
) -> None:
    if not OPT_NAME_RE.fullmatch(entry.name):
        protect(entry.name, "unexpected directory name")
        return
    if entry.name in CORE_OPT_PROTECTED:
        protect(entry.name, "core Pilot 0 runtime directory")
    if entry.is_symlink() or not entry.is_dir():
        protect(entry.name, "not a regular directory")
        if entry.is_symlink():
            try:
                resolved = entry.resolve(strict=True)
            except OSError:
                return
            if resolved.is_relative_to(opt_root):
                protect(
                    resolved.relative_to(opt_root).parts[0],
                    f"symlink target of {entry.name}",
                )


def classify_opt_dirs(
    opt_root: Path,
    reference_roots: Iterable[Path],
    processes: Iterable[tuple[Path, bytes]],
    sizes: dict[str, str] | None = None,
) -> list[ClassifiedOptDir]:
    """Classify direct children of /opt/epm into protected vs removable."""
    info = opt_root.lstat()
    require(stat.S_ISDIR(info.st_mode), f"{opt_root} must be a real directory.")

    reasons_map: dict[str, set[str]] = {}

    def protect(name: str, reason: str) -> None:
        reasons_map.setdefault(name, set()).add(reason)

    entries = sorted(opt_root.iterdir(), key=lambda p: p.name)
    for entry in entries:
        _protect_opt_entry(opt_root, entry, protect)

    for ref_root in reference_roots:
        for path, data in scan_path(ref_root):
            for name in references_in(data, opt_root):
                protect(name, f"referenced by {path}")

    for path, data in processes:
        for name in references_in(data, opt_root):
            protect(name, f"running process: {path}")

    size_lookup = sizes or {}
    return [
        ClassifiedOptDir(
            name=entry.name,
            size=size_lookup.get(entry.name, "?"),
            reasons=sorted(reasons_map.get(entry.name, ())),
        )
        for entry in entries
    ]


def list_tmp_build_artifacts(tmp_root: Path = TMP_ROOT) -> list[Path]:
    """Return only safe EPM build staging entries directly inside /tmp."""
    if not tmp_root.is_dir():
        return []
    artifacts: list[Path] = []
    for entry in sorted(tmp_root.iterdir(), key=lambda p: p.name):
        name = entry.name
        if name in {"epm-contexts.tar.gz", "build"} or name.startswith("epm-"):
            artifacts.append(entry)
    return artifacts


def read_admin_manifest(path: Path = ADMIN_RUN_IDENTITY) -> str | None:
    if not path.is_file():
        return None
    match = MANIFEST_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    if not match:
        return None
    return f"sha256:{match.group(1)}"


def read_catalog_digests(db_path: Path = ADMIN_SQLITE) -> tuple[set[str], set[str]]:
    """Return (latest_digests, operator_referenced_digests) from admin.sqlite."""
    if not db_path.is_file():
        return set(), set()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        latest: set[str] = set()
        referenced: set[str] = set()
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "qualified_releases" in tables:
            cols = {
                row[1] for row in conn.execute("PRAGMA table_info(qualified_releases)").fetchall()
            }
            digest_col = "image_digest" if "image_digest" in cols else None
            if digest_col:
                order_col = "created_at" if "created_at" in cols else "rowid"
                row = conn.execute(
                    f"SELECT {digest_col} FROM qualified_releases ORDER BY {order_col} DESC LIMIT 1"
                ).fetchone()
                if row and row[0]:
                    latest.add(normalize_digest(str(row[0])))
                if "operators" in tables:
                    op_cols = {
                        r[1] for r in conn.execute("PRAGMA table_info(operators)").fetchall()
                    }
                    if "release_id" in cols and "current_release_id" in op_cols:
                        for (digest,) in conn.execute(
                            f"SELECT DISTINCT qr.{digest_col} FROM qualified_releases qr "
                            "JOIN operators o ON o.current_release_id = qr.release_id"
                        ).fetchall():
                            if digest:
                                referenced.add(normalize_digest(str(digest)))
        return latest, referenced
    finally:
        conn.close()


def _run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return proc.stdout


def query_docker_containers() -> list[ContainerRecord]:
    raw = _run(["docker", "ps", "-a", "--no-trunc", "--format", "{{.ID}}\t{{.Names}}\t{{.Status}}"])
    lines = [line for line in raw.splitlines() if line.strip()]
    if not lines:
        return []
    ids = [line.split("\t", 1)[0] for line in lines]
    inspect_raw = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.Id}}\t{{.Name}}\t{{.Image}}\t{{.Config.Image}}\t{{.State.Running}}",
            *ids,
        ]
    )
    status_by_id = {line.split("\t")[0]: line.split("\t")[2] for line in lines}
    records: list[ContainerRecord] = []
    for line in inspect_raw.splitlines():
        if not line.strip():
            continue
        cid, name, image_id, image_ref, running_str = line.split("\t", 4)
        records.append(
            ContainerRecord(
                container_id=cid,
                name=name.lstrip("/"),
                image_id=normalize_digest(image_id),
                image_ref=image_ref,
                status=status_by_id.get(cid, ""),
                running=running_str.strip().lower() == "true",
            )
        )
    return records


def query_docker_images() -> list[ImageRecord]:
    raw = _run(
        [
            "docker",
            "images",
            "--no-trunc",
            "--format",
            "{{.ID}}\t{{.Repository}}\t{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}",
        ]
    )
    records: list[ImageRecord] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        img_id, repo, tag, size, created_at = line.split("\t", 4)
        records.append(
            ImageRecord(
                image_id=normalize_digest(img_id),
                repository=repo,
                tag=tag,
                size=size,
                created_at=created_at,
            )
        )
    return records


def process_references() -> Iterable[tuple[Path, bytes]]:
    proc_root = Path("/proc")
    if not proc_root.is_dir():
        return
    for process in proc_root.iterdir():
        if not process.name.isdecimal():
            continue
        for leaf in ("cmdline", "maps", "cwd", "exe"):
            path = process / leaf
            try:
                data = os.readlink(path).encode() if leaf in {"cwd", "exe"} else path.read_bytes()
                yield path, data
            except FileNotFoundError, ProcessLookupError, PermissionError:
                continue


def query_opt_sizes(opt_root: Path = OPT_ROOT) -> dict[str, str]:
    if not opt_root.is_dir():
        return {}
    entries = [str(p) for p in sorted(opt_root.iterdir(), key=lambda p: p.name)]
    if not entries:
        return {}
    proc = subprocess.run(
        ["du", "-sh", "--", *entries],
        capture_output=True,
        text=True,
        check=False,
    )
    sizes: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == DU_COLUMNS:
            sizes[Path(parts[1]).name] = parts[0].strip()
    return sizes


def host_state(keep_refs: Iterable[str]) -> dict[str, object]:
    containers = query_docker_containers()
    images = query_docker_images()
    manifest = read_admin_manifest()
    latest_catalog, ref_catalog = read_catalog_digests()
    classified_images = classify_images(
        images,
        containers,
        ImageProtectionContext(
            admin_manifest_digest=manifest,
            catalog_latest_digests=tuple(latest_catalog),
            catalog_referenced_digests=tuple(ref_catalog),
            keep_refs=tuple(keep_refs),
        ),
    )
    opt_dirs = (
        classify_opt_dirs(
            OPT_ROOT,
            OPT_REFERENCE_ROOTS,
            process_references(),
            sizes=query_opt_sizes(OPT_ROOT),
        )
        if OPT_ROOT.is_dir()
        else []
    )
    tmp_artifacts = list_tmp_build_artifacts(TMP_ROOT)
    return {
        "containers": containers,
        "images": classified_images,
        "opt_dirs": opt_dirs,
        "tmp_artifacts": tmp_artifacts,
    }


def print_inspect(state: dict[str, object], *, as_json: bool) -> None:
    containers: list[ContainerRecord] = state["containers"]  # type: ignore[assignment]
    images: list[ClassifiedImage] = state["images"]  # type: ignore[assignment]
    opt_dirs: list[ClassifiedOptDir] = state["opt_dirs"]  # type: ignore[assignment]
    tmp_artifacts: list[Path] = state["tmp_artifacts"]  # type: ignore[assignment]

    if as_json:
        payload = {
            "running_containers": [
                {"name": c.name, "image": c.image_ref, "status": c.status}
                for c in containers
                if c.running
            ],
            "stopped_containers": [
                {"name": c.name, "image": c.image_ref, "status": c.status}
                for c in containers
                if not c.running
            ],
            "protected_images": [
                {
                    "ref": ci.record.display_ref,
                    "short_id": ci.record.short_id,
                    "id": ci.record.image_id,
                    "size": ci.record.size,
                    "reasons": ci.reasons,
                }
                for ci in images
                if ci.protected
            ],
            "removable_images": [
                {
                    "ref": ci.record.display_ref,
                    "short_id": ci.record.short_id,
                    "id": ci.record.image_id,
                    "size": ci.record.size,
                    "target": ci.record.remove_target,
                }
                for ci in images
                if not ci.protected
            ],
            "protected_opt_dirs": [
                {"name": d.name, "size": d.size, "reasons": d.reasons}
                for d in opt_dirs
                if d.protected
            ],
            "removable_opt_dirs": [
                {"name": d.name, "size": d.size} for d in opt_dirs if not d.protected
            ],
            "tmp_artifacts": [str(p) for p in tmp_artifacts],
        }
        print(json.dumps(payload, indent=2))
        return

    running = [c for c in containers if c.running]
    stopped = [c for c in containers if not c.running]
    print(f"=== CONTAINERS ({len(running)} running, {len(stopped)} stopped) ===")
    for c in running:
        print(f"  KEEP      {c.name}  ({c.image_ref})  [{c.status}]")
    for c in stopped:
        print(f"  STOPPED   {c.name}  ({c.image_ref})  [{c.status}]")

    prot_imgs = [ci for ci in images if ci.protected]
    rem_imgs = [ci for ci in images if not ci.protected]
    print(f"\n=== DOCKER IMAGES ({len(prot_imgs)} protected, {len(rem_imgs)} removable) ===")
    for ci in prot_imgs:
        print(
            f"  KEEP      {ci.record.short_id}  {ci.record.size:>7}  {ci.record.display_ref}"
            f"  -- {'; '.join(ci.reasons)}"
        )
    for ci in rem_imgs:
        print(
            f"  REMOVABLE {ci.record.short_id}  {ci.record.size:>7}  {ci.record.display_ref}"
            f"  ({ci.record.created_at})"
        )

    prot_opt = [d for d in opt_dirs if d.protected]
    rem_opt = [d for d in opt_dirs if not d.protected]
    print(f"\n=== /opt/epm DIRECTORIES ({len(prot_opt)} protected, {len(rem_opt)} removable) ===")
    for d in prot_opt:
        print(f"  KEEP      {d.size:>6}  /opt/epm/{d.name}  -- {'; '.join(d.reasons)}")
    for d in rem_opt:
        print(f"  REMOVABLE {d.size:>6}  /opt/epm/{d.name}")

    print(f"\n=== /tmp BUILD STAGING ({len(tmp_artifacts)} item(s)) ===")
    if not tmp_artifacts:
        print("  (none)")
    for p in tmp_artifacts:
        print(f"  REMOVABLE {p}")


def action_remove_containers(names: list[str], *, all_stopped: bool) -> None:
    containers = query_docker_containers()
    by_name = {c.name: c for c in containers}
    if all_stopped:
        targets = [c.name for c in containers if not c.running]
    else:
        targets = []
        for name in names:
            require(
                CONTAINER_NAME_RE.fullmatch(name) is not None,
                f"Invalid container name: {name}",
            )
            require(name in by_name, f"Container not found: {name}")
            require(not by_name[name].running, f"Refusing to remove running container: {name}")
            targets.append(name)
    if not targets:
        print("No stopped containers to remove.")
        return
    subprocess.run(["docker", "rm", "--", *targets], check=True)
    print(f"Removed {len(targets)} stopped container(s).")


def action_remove_images(refs: list[str], keep_refs: list[str], *, all_removable: bool) -> None:
    state = host_state(keep_refs)
    classified: list[ClassifiedImage] = state["images"]  # type: ignore[assignment]
    if all_removable:
        targets = [ci.record.remove_target for ci in classified if not ci.protected]
    else:
        targets = []
        for ref in refs:
            matches = [ci for ci in classified if matches_image_ref(ci.record, ref)]
            require(bool(matches), f"Image not found: {ref}")
            for ci in matches:
                require(
                    not ci.protected,
                    f"Refusing to remove protected image {ci.record.display_ref} "
                    f"({ci.record.short_id}): {'; '.join(ci.reasons)}",
                )
                targets.append(ci.record.remove_target)
    # Deduplicate preserving order
    unique_targets = list(dict.fromkeys(targets))
    if not unique_targets:
        print("No removable Docker images found.")
        return
    removed = 0
    for target in unique_targets:
        proc = subprocess.run(
            ["docker", "image", "rm", "--", target],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            removed += 1
            print(f"Removed image: {target}")
        else:
            print(f"Skipped image {target}: {proc.stderr.strip()}")
    print(f"Removed {removed}/{len(unique_targets)} Docker image(s).")


def action_prune_builder(*, include_all: bool) -> None:
    cmd = ["docker", "builder", "prune", "-f"]
    if include_all:
        cmd.insert(3, "-a")
    subprocess.run(cmd, check=True)


def action_remove_tmp() -> None:
    artifacts = list_tmp_build_artifacts(TMP_ROOT)
    if not artifacts:
        print("No /tmp EPM build artifacts found.")
        return
    for entry in artifacts:
        require(entry.parent == TMP_ROOT, f"Refusing path outside /tmp: {entry}")
        if entry.is_symlink() or entry.is_file():
            entry.unlink()
        elif entry.is_dir():
            require(shutil.rmtree.avoids_symlink_attacks, "Safe directory removal unavailable.")
            shutil.rmtree(entry)
        print(f"Removed temporary staging: {entry}")


def _assert_no_mount_under(target: Path) -> None:
    mountinfo = Path("/proc/self/mountinfo")
    if not mountinfo.is_file():
        return
    for line in mountinfo.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split()
        if len(parts) < MOUNTINFO_MIN_FIELDS:
            continue
        mount = Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), parts[4]))
        require(not mount.is_relative_to(target), f"Refusing mount inside {target}: {mount}")


def action_remove_opt_dirs(names: list[str], *, all_unreferenced: bool) -> None:
    opt_dirs = classify_opt_dirs(
        OPT_ROOT,
        OPT_REFERENCE_ROOTS,
        process_references(),
        sizes=query_opt_sizes(OPT_ROOT),
    )
    by_name = {d.name: d for d in opt_dirs}
    if all_unreferenced:
        targets = [d.name for d in opt_dirs if not d.protected]
    else:
        targets = []
        for name in names:
            require(OPT_NAME_RE.fullmatch(name) is not None, f"Invalid /opt/epm name: {name}")
            require(name in by_name, f"/opt/epm/{name} does not exist.")
            require(
                not by_name[name].protected,
                f"Refusing to remove protected /opt/epm/{name}: {'; '.join(by_name[name].reasons)}",
            )
            targets.append(name)
    if not targets:
        print("No unreferenced /opt/epm directories to remove.")
        return
    require(shutil.rmtree.avoids_symlink_attacks, "Safe directory removal unavailable.")
    for name in targets:
        target = OPT_ROOT / name
        _assert_no_mount_under(target)
        for directory in (OPT_ROOT, target):
            info = directory.lstat()
            require(
                stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                f"Refusing unsafe directory ownership/permissions: {directory}",
            )
        shutil.rmtree(target)
        print(f"Removed unreferenced directory: {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=(
            "inspect",
            "remove-containers",
            "remove-images",
            "prune-builder",
            "remove-tmp",
            "remove-opt-dirs",
        ),
    )
    parser.add_argument("--keep", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--all-stopped", action="store_true")
    parser.add_argument("--container", action="append", default=[])
    parser.add_argument("--all-removable", action="store_true")
    parser.add_argument("--image", action="append", default=[])
    parser.add_argument("--all", action="store_true", dest="prune_all")
    parser.add_argument("--all-unreferenced", action="store_true")
    parser.add_argument("--dir", action="append", default=[])
    args = parser.parse_args()

    require(os.geteuid() == 0, "Run this helper with sudo on the Pilot 0 host.")

    if args.action == "inspect":
        print_inspect(host_state(args.keep), as_json=args.json)
    elif args.action == "remove-containers":
        action_remove_containers(args.container, all_stopped=args.all_stopped)
    elif args.action == "remove-images":
        action_remove_images(args.image, args.keep, all_removable=args.all_removable)
    elif args.action == "prune-builder":
        action_prune_builder(include_all=args.prune_all)
    elif args.action == "remove-tmp":
        action_remove_tmp()
    elif args.action == "remove-opt-dirs":
        action_remove_opt_dirs(args.dir, all_unreferenced=args.all_unreferenced)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Cleanup stopped: {error}") from error
