"""Polite HTTP fetcher: robots.txt, per-domain delay, retries with backoff."""
from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urlparse

import requests


class RobotsDisallowed(Exception):
    pass


class Fetcher:
    def __init__(self, user_agent: str, min_delay: float = 3.0, timeout: int = 30,
                 retries: int = 3, respect_robots: bool = True):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": user_agent, "Accept-Language": "fa,en;q=0.8"})
        self.min_delay, self.timeout, self.retries = min_delay, timeout, retries
        self.respect_robots = respect_robots
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=self.timeout)
                rp.parse(r.text.splitlines() if r.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self._robots[base] = rp
        return self._robots[base].can_fetch(self.s.headers["User-Agent"], url)

    def _wait(self, url: str):
        host = urlparse(url).netloc
        dt = time.monotonic() - self._last.get(host, 0)
        if dt < self.min_delay:
            time.sleep(self.min_delay - dt)
        self._last[host] = time.monotonic()

    def request(self, method: str, url: str, **kw) -> requests.Response:
        if not self._allowed(url):
            raise RobotsDisallowed(url)
        kw.setdefault("timeout", self.timeout)
        err = None
        for attempt in range(self.retries):
            self._wait(url)
            try:
                r = self.s.request(method, url, **kw)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"HTTP {r.status_code}")
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                err = e
                time.sleep(2 ** attempt * self.min_delay)
        raise err

    def get(self, url: str, **kw) -> requests.Response:
        return self.request("GET", url, **kw)
