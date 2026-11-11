"""Fixed host_agent candidate entry point; no HTTP-selected mode or local fallback."""

from app.hosted_candidates.runtime import launch


def main():
    launch("host_agent")


if __name__ == "__main__":
    main()
