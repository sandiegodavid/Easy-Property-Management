"""Loopback-only test harness for the H02.7 interstitial, not a hosted launcher."""

from http.server import HTTPServer

from app.hosted_candidates.runtime import HostedStatusHandler


if __name__ == "__main__":
    with HTTPServer(("127.0.0.1", 18753), HostedStatusHandler) as server:
        server.binding = None
        server.serve_forever()
