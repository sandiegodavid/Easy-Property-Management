"""Protected startup and resource delivery with the actual Admin schema and provider loader."""

from hashlib import sha256
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from app.modules.hosted_access.application.managed_provider import ProviderUnavailable
from app.modules.hosted_access.infrastructure import admin_entry
from app.modules.hosted_access.tests.test_identity_contracts import setup
from app.platform.hosted_schema import initialize_store
from app.platform.hosted_writer_lock import HostedWriterLock
from app.platform.locking import WorkspaceOperationInProgressError
from app.platform.schema_resources import HostedStore

APPLICATION = Path(__file__).resolve().parents[6]


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    private = tmp_path.resolve()
    private.chmod(0o700)

    def write(name, content):
        path = private / name
        path.write_text(content)
        path.chmod(0o600)
        return path

    selected = setup()
    provider = {
        "version": 1,
        "realm": selected.realm.model_dump(),
        "origins": selected.origins.model_dump(),
        "api_key": "synthetic-provider-api-key",
        "google_enabled": True,
        "email_link_enabled": True,
        "totp_enabled": True,
        "provider_email_sends_per_day": selected.provider_sends_per_day,
    }
    raw = json.dumps(provider)
    provider_path = write("provider.json", raw)
    selected = selected.model_copy(
        update={
            "configuration_state": "verified",
            "provider_config_sha256": sha256(raw.encode()).hexdigest(),
        }
    )
    database = private / "admin.sqlite"
    initialize_store(HostedStore.ADMIN, database, application_directory=APPLICATION)
    database.chmod(0o600)
    lock = write("writer.lock", "")
    bearer = write("bearer", "synthetic-bearer-one")
    config = {
        "database": str(database),
        "writer_lock": str(lock),
        "setup": str(write("setup.json", selected.model_dump_json())),
        "provider_configuration": str(provider_path),
        "bearer_file": str(bearer),
        "mail_key_file": str(write("mail-key", "x" * 32)),
        "deployment_id": "00000000-0000-4000-8000-000000000001",
        "application_directory": str(APPLICATION),
        "support_contact": "owner@example.invalid",
    }
    configuration = write("deployment.json", json.dumps(config))
    fake_module = private / "app/modules/hosted_access/infrastructure/admin_entry.py"
    fake_module.parent.mkdir(parents=True)
    fake_module.touch()
    ui = private / "app/admin_build/dist"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>Packaged Admin</title>")
    (ui / "assets/main.js").write_text("export {};")
    monkeypatch.setattr(admin_entry, "__file__", str(fake_module))
    return configuration, config, selected


def test_protected_startup_lock_public_config_and_private_credential_rotation(
    deployment, monkeypatch
):
    configuration, config, selected = deployment
    captured = []
    build = admin_entry.build_central_provider

    def capture(*args, **kwargs):
        assert kwargs["rate_admission"].daily_limit == 9
        provider = build(*args, **kwargs)
        captured.append(provider)
        return provider

    monkeypatch.setattr(admin_entry, "build_central_provider", capture)
    app = admin_entry.create_app(configuration)
    with TestClient(app, base_url=selected.origins.admin) as client:
        with (
            pytest.raises(WorkspaceOperationInProgressError),
            HostedWriterLock(Path(config["writer_lock"])),
        ):
            pass
        assert client.get("/").text.endswith("Packaged Admin</title>")
        assert client.get("/assets/main.js").status_code == 200
        start = client.get("/auth/start")
        assert start.status_code == 200
        assert start.json()["firebase"]["projectId"] == selected.realm.project_id
        assert start.json()["supportContact"] == config["support_contact"]
        assert "synthetic-bearer" not in start.text
        assert "x" * 32 not in start.text
        assert client.get("/api/admin/session").status_code == 401
        assert (
            client.get(
                "/",
                headers={
                    "Host": "unregistered.invalid",
                    "X-Forwarded-Host": selected.origins.admin.removeprefix("https://"),
                },
            ).status_code
            == 401
        )
        assert client.head("/auth/start").status_code == 405
        assert client.options("/auth/start").status_code == 405
        assert client.get("/assets/main.map").status_code == 401
        assert captured[0].bearer() == "synthetic-bearer-one"
        Path(config["bearer_file"]).write_text("synthetic-bearer-two")
        assert captured[0].bearer() == "synthetic-bearer-two"
        Path(config["bearer_file"]).write_text("broken\nbearer")
        with pytest.raises(ProviderUnavailable):
            captured[0].bearer()
        Path(config["bearer_file"]).write_text("x" * 16385)
        with pytest.raises(ProviderUnavailable):
            captured[0].bearer()
    with HostedWriterLock(Path(config["writer_lock"])):
        pass


def test_unverified_setup_and_provider_digest_fail_before_serving(deployment):
    configuration, config, _ = deployment
    provider = Path(config["provider_configuration"])
    provider.write_text("{}")
    with pytest.raises(ProviderUnavailable):
        admin_entry.create_app(configuration)


def test_public_deployment_file_and_missing_assets_fail_before_serving(deployment, monkeypatch):
    configuration, _, _ = deployment
    configuration.chmod(0o644)
    with pytest.raises(ValueError, match="private input"):
        admin_entry.create_app(configuration)
    configuration.chmod(0o600)
    monkeypatch.setattr(
        admin_entry, "__file__", str(configuration.parent / "missing/a/b/c/module.py")
    )
    with pytest.raises(ValueError, match="Build and package"):
        admin_entry.create_app(configuration)


def test_loopback_tls_serves_exact_admin_host_and_releases_lock(deployment):
    """Real TLS transport, isolated synthetic configuration and a disposable port."""
    from datetime import UTC, datetime, timedelta
    import http.client
    import ipaddress
    import socket
    import ssl
    from threading import Thread
    import time

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    import uvicorn

    configuration, config, selected = deployment
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Admin qualification")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(selected.origins.admin.removeprefix("https://")),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = configuration.parent / "test.crt"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path = configuration.parent / "test.key"
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    key_path.chmod(0o600)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            admin_entry.create_app(configuration),
            ssl_keyfile=str(key_path),
            ssl_certfile=str(cert_path),
            proxy_headers=False,
            access_log=False,
            log_level="error",
        )
    )
    thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        context = ssl.create_default_context(cafile=str(cert_path))
        for host, status in (
            (selected.origins.admin.removeprefix("https://"), 200),
            ("unregistered.invalid", 401),
        ):
            client = http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=3)
            try:
                client.request("GET", "/auth/start", headers={"Host": host})
                response = client.getresponse()
                assert response.status == status
                assert response.getheader("Cache-Control") == "no-store"
                response.read()
            finally:
                client.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
    assert not thread.is_alive()
    with HostedWriterLock(Path(config["writer_lock"])):
        pass


def test_shared_identity_uses_packaged_hosts_only(deployment, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from sqlalchemy import text

    from app.modules.hosted_access.infrastructure import shared_identity_entry as entry
    from app.platform.sqlite_engine import create_sqlite_engine, immediate_transaction

    configuration, config, selected = deployment
    private = configuration.parent
    engine = create_sqlite_engine(Path(config["database"]))
    with immediate_transaction(engine) as connection:
        connection.execute(
            text("""
                INSERT INTO control_meta (id, deployment_id, public_base_domain, login_origin,
                                          registry_generation, created_at)
                VALUES (1, :id, 'example.invalid', :origin, 1, 1)
            """),
            {"id": config["deployment_id"], "origin": selected.origins.central},
        )
    engine.dispose()

    def write(name, raw):
        path = private / name
        path.write_bytes(raw)
        path.chmod(0o600)
        return str(path)

    packaged = Path(admin_entry.__file__).parents[3]
    central_assets = packaged / "central_build/dist/assets"
    central_assets.mkdir(parents=True)
    (central_assets / "central.js").write_text("export {};")
    (central_assets.parent / "index.html").write_text("<!doctype html><title>Central</title>")
    monkeypatch.setattr(entry, "__file__", admin_entry.__file__)

    calls = []

    def helper(_self, path, query):
        calls.append((path, query))
        return b"synthetic provider helper", "text/html"

    monkeypatch.setattr(entry.FirebaseHelpers, "fetch", helper)
    settings = {
        "admin_configuration": str(configuration),
        "signing_key": write("ed25519", Ed25519PrivateKey.generate().private_bytes_raw()),
        "signing_key_id": selected.central_signing_key_ref,
        "source_registry": write("source-registry.json", b'{"sources": []}'),
        "host_relay_socket": str(private / "absent.sock"),
        "host_relay_uid": 0,
        "socket_directory": str(private),
        "gateway_address": "10.3.0.2",
        "listen_address": "10.3.0.3",
        "provider_proxy": "http://10.3.0.1:1080",
    }
    path = Path(write("shared.json", json.dumps(settings).encode()))
    app, _ = entry.create_app(path)
    ingress = {"X-Forwarded-Proto": "https"}
    with TestClient(app, base_url=selected.origins.admin, client=("10.3.0.2", 12345)) as client:
        assert client.get("/", headers=ingress).status_code == 200
        assert (
            client.get("/", headers=ingress | {"X-Forwarded-Host": "attacker.invalid"}).status_code
            == 421
        )
        assert client.get("/", headers={}).status_code == 421
        assert client.get("/assets/main.js", headers=ingress).status_code == 200
        assert client.get("/assets/central.js", headers=ingress).status_code in {401, 404}
        central = selected.origins.central
        assert client.get(central + "/assets/central.js", headers=ingress).status_code == 200
        assert client.get(central + "/assets/main.js", headers=ingress).status_code in {401, 404}
        assert client.get(central + "/api/admin/session", headers=ingress).status_code == 404
        result = client.get(central + "/__/auth/handler?flow=opaque", headers=ingress)
        assert result.content == b"synthetic provider helper"
        assert result.headers["Cache-Control"] == "no-store"
        init = client.get(central + "/__/firebase/init.json", headers=ingress)
        assert init.status_code == 200
        assert init.json() == {
            "apiKey": client.get("/auth/start", headers=ingress).json()["firebase"]["apiKey"],
            "authDomain": central.removeprefix("https://"),
            "projectId": selected.realm.project_id,
        }
        assert calls == [("/__/auth/handler", b"flow=opaque")]
        assert client.post(central + "/__/auth/handler", headers=ingress).status_code == 404
    app, _ = entry.create_app(path)
    with TestClient(app, base_url=selected.origins.admin, client=("10.3.0.4", 12345)) as client:
        assert client.get("/", headers=ingress).status_code == 421


def test_firebase_helpers_use_only_the_selected_project_peer(deployment, monkeypatch):
    from email.message import Message
    from unittest.mock import Mock

    from app.modules.hosted_access.application.managed_provider import ProviderUnavailable
    from app.modules.hosted_access.infrastructure import firebase_helpers

    _, _, selected = deployment
    server = Mock()
    response = server.getresponse.return_value
    response.status = 200
    response.headers = Message()
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.fp = None
    response.read1.side_effect = [b"provider helper", b""]
    connection = Mock(return_value=server)
    monkeypatch.setattr(firebase_helpers, "HTTPSConnection", connection)
    helper = firebase_helpers.FirebaseHelpers(selected, "http://10.3.0.1:1080")
    assert helper.fetch("/__/auth/handler", b"flow=opaque")[0] == b"provider helper"
    server.set_tunnel.assert_called_once_with(selected.realm.project_id + ".firebaseapp.com", 443)
    server.request.assert_called_once_with(
        "GET",
        "/__/auth/handler?flow=opaque",
        headers={"Host": selected.realm.project_id + ".firebaseapp.com"},
    )
    with pytest.raises(ProviderUnavailable):
        helper.fetch("/invalid", b"")
    response.status = 302
    with pytest.raises(ProviderUnavailable):
        helper.fetch("/__/auth/handler", b"")
