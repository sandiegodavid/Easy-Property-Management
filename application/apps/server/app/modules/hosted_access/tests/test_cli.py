"""Explicit launch contract keeps the hosted listener private and single-process."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from app import __main__ as cli


def test_hosted_launcher_has_no_public_host_worker_or_development_origin_override(monkeypatch):
    parser = cli._build_parser()
    args = parser.parse_args(
        ["serve-hosted", "--deployment", "/etc/epm/hosted-a.json", "--port", "8001"]
    )
    uvicorn, application = Mock(), Mock()
    module = Mock(create_app=Mock(return_value=application))
    monkeypatch.setattr(cli, "import_module", lambda name: uvicorn if name == "uvicorn" else module)
    cli._serve(args, parser, Path("/var/lib/epm-a/config.json"))
    module.create_app.assert_called_once_with(
        Path("/var/lib/epm-a/config.json"), hosted_deployment_path=Path("/etc/epm/hosted-a.json")
    )
    uvicorn.run.assert_called_once_with(
        application, host="127.0.0.1", port=8001, proxy_headers=False
    )
    for forbidden in (
        ["--host", "0.0.0.0"],
        ["--workers", "2"],
        ["--development-origin", "http://localhost:5173"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(["serve-hosted", "--deployment", "/etc/epm/a.json", *forbidden])


def test_hosted_launch_does_not_silently_fall_back_to_local_on_invalid_configuration(monkeypatch):
    parser = cli._build_parser()
    args = parser.parse_args(["serve-hosted", "--deployment", "/unqualified.json"])
    uvicorn = Mock()
    module = Mock(create_app=Mock(side_effect=cli.HostedConfigurationError("not qualified")))
    monkeypatch.setattr(cli, "import_module", lambda name: uvicorn if name == "uvicorn" else module)
    with pytest.raises(SystemExit):
        cli._serve(args, parser, None)
    uvicorn.run.assert_not_called()
