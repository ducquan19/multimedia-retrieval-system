import threading
import time
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, OpenerDirector, Request, build_opener


class SignedUrlError(RuntimeError):
    """Raised when the Hub does not return a signed download URL."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


class HuggingFaceUrlSigner:
    """Resolve files of a private Hub dataset to short-lived, token-free CDN URLs.

    The Hub answers an authenticated ``resolve`` request with a redirect to a signed CDN URL
    (valid for about an hour). The browser can stream that URL directly with HTTP Range
    requests, so the token never leaves the backend. URLs are cached per path until
    ``ttl_seconds`` or shortly before the CDN ``Expires`` time, whichever comes first.
    """

    _EXPIRY_MARGIN_SECONDS = 300

    def __init__(
        self,
        token: str,
        repo_id: str,
        *,
        revision: str = "main",
        endpoint: str = "https://huggingface.co",
        ttl_seconds: float = 2700,
        timeout_seconds: float = 10,
        opener: OpenerDirector | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._token = token
        self._base_url = (
            f"{endpoint.rstrip('/')}/datasets/{repo_id}/resolve/{quote(revision, safe='')}/"
        )
        self._ttl_seconds = ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._opener = opener or build_opener(_NoRedirect)
        self._clock = clock
        self._cache: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def sign(self, path_in_repo: str, *, refresh: bool = False) -> str:
        now = self._clock()
        if not refresh:
            with self._lock:
                cached = self._cache.get(path_in_repo)
            if cached is not None and cached[1] > now:
                return cached[0]

        url = self._request_signed_url(path_in_repo)
        with self._lock:
            self._cache[path_in_repo] = (url, self._cache_until(url, now))
        return url

    def _request_signed_url(self, path_in_repo: str) -> str:
        request = Request(
            self._base_url + quote(path_in_repo),
            method="HEAD",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                status, location = response.status, response.headers.get("Location")
        except HTTPError as exc:
            status, location = exc.code, exc.headers.get("Location")
        except (URLError, TimeoutError) as exc:
            raise SignedUrlError(f"Hugging Face Hub is unreachable: {exc}") from exc

        if status in {301, 302, 303, 307, 308} and location:
            return urljoin(request.full_url, location)
        if status in {401, 403}:
            raise SignedUrlError("Hugging Face token was rejected for the private video repository")
        if status == 404:
            raise SignedUrlError(f"{path_in_repo} was not found in the private video repository")
        raise SignedUrlError(f"Unexpected Hugging Face Hub response (HTTP {status})")

    def _cache_until(self, url: str, now: float) -> float:
        until = now + self._ttl_seconds
        expires = parse_qs(urlparse(url).query).get("Expires")
        if expires and expires[0].isdigit():
            until = min(until, int(expires[0]) - self._EXPIRY_MARGIN_SECONDS)
        return until
