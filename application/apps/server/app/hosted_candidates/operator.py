"""Fixed operator candidate entry point; no HTTP-selected mode or local fallback."""

from app.hosted_candidates.runtime import launch


def main():
    launch("operator")


if __name__ == "__main__":
    main()
