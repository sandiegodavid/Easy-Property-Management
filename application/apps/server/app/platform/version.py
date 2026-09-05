"""Application release metadata supplied by installed package metadata."""

from importlib.metadata import PackageNotFoundError, version


def application_version() -> str:
    """Return the installed distribution version without duplicating release constants."""
    try:
        return version("easy-property-management")
    except PackageNotFoundError:
        return "development"
