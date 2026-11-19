"""A small deadlock-api client: paced (at most 2 requests a second), retried on 429/503 with Retry-After, a User-Agent naming the
project and its site, an optional API key (X-API-KEY). Standard library only."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import config


class ApiError(Exception):
    def __init__(self, msg, status=0):
        super().__init__(msg)
        self.status = status


def _urlopen(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        try:
            body = e.read()
        except Exception:
            body = b""
        return e.code, dict((e.headers or {}).items()), body


def _retry_after(headers):
    for k, v in (headers or {}).items():
        if k.lower() == "retry-after":
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                return None
    return None


def _qs(params):
    """Query string: lists become comma-separated values (deadlock-api's array parameters), booleans true/false, None left out."""
    out = []
    for k, v in params.items():
        if v is None:
            continue
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, (list, tuple, set)):
            v = ",".join(str(x) for x in v)
        out.append((k, str(v)))
    return urllib.parse.urlencode(out, safe=",")


class Api:
    def __init__(self, base=config.API, ua="NightshiftBuilds/1", key=None, pace=config.PACE, tries=config.TRIES, opener=None,
                 sleep=time.sleep, clock=time.monotonic, timeout=config.TIMEOUT):
        self.base = base.rstrip("/")
        self.ua = ua
        self.key = key or None
        self.pace = pace
        self.tries = max(1, tries)
        self.opener = opener or _urlopen
        self.sleep = sleep
        self.clock = clock
        self.timeout = timeout
        self.count = 0
        self._last = None

    def _wait(self):
        if self._last is not None:
            gap = self.pace - (self.clock() - self._last)
            if gap > 0:
                self.sleep(gap)
        self._last = self.clock()

    def _call(self, method, url, body=None):
        headers = {"User-Agent": self.ua, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.key:
            headers["X-API-KEY"] = self.key
        status = 0
        for attempt in range(self.tries):
            self._wait()
            self.count += 1
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            try:
                status, hdrs, data = self.opener(req, self.timeout)
            except (OSError, ValueError) as e:
                raise ApiError("network: " + type(e).__name__, 0)
            if status == 200:
                try:
                    return json.loads(data.decode("utf-8"))
                except ValueError:
                    raise ApiError("answer not JSON", 200)
            if status in (429, 503) and attempt + 1 < self.tries:
                ra = _retry_after(hdrs)
                self.sleep(min(ra if ra is not None else 2 ** attempt, config.RETRY_AFTER_MAX))
                continue
            raise ApiError("http %d" % status, status)
        raise ApiError("http %d" % status, status)

    def get(self, path, params=None):
        q = _qs(params or {})
        return self._call("GET", self.base + path + ("?" + q if q else ""))

    def gql(self, query):
        r = self._call("POST", self.base + "/v1/graphql", json.dumps({"query": query}).encode("utf-8"))
        if not isinstance(r, dict):
            raise ApiError("graphql: answer not an object", 200)
        if r.get("errors"):
            # the server's text may echo part of the query (account ids): it never goes into a message that reaches a log
            raise ApiError("graphql: an error answer (%d)" % len(r["errors"]), 200)
        return r.get("data") or {}
