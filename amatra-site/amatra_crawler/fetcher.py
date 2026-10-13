"""Cliente HTTP com retries, rate limiting e suporte a ``robots.txt``."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

from .config import CrawlConfig

LOG = logging.getLogger(__name__)

# Códigos HTTP que justificam nova tentativa.
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def _normalize_headers(response: requests.Response) -> dict[str, str]:
    """Converte cabeçalhos HTTP em um dict com chaves minúsculas.

    Servidores podem variar a capitalização do ``Content-Type`` (ex.:
    ``Content-type``). Normalizar evita falhas silenciosas na detecção de tipo.
    """
    return {key.lower(): value for key, value in response.headers.items()}


@dataclass
class FetchResult:
    """Resultado de uma requisição HTTP."""

    url: str
    status: int | None = None
    content: bytes = b""
    headers: dict = field(default_factory=dict)
    final_url: str = ""
    error: str | None = None
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        """Indica sucesso (2xx/3xx sem erro de transporte)."""
        return self.error is None and self.status is not None and 200 <= self.status < 400

    @property
    def content_type(self) -> str:
        """Content-Type normalizado (sem charset e em minúsculas)."""
        return self.headers.get("content-type", "").split(";")[0].strip().lower()


class RateLimiter:
    """Limita a taxa global de requisições, de forma thread-safe."""

    def __init__(self, delay: float) -> None:
        self.delay = max(0.0, delay)
        self._lock = threading.Lock()
        self._next_allowed = 0.0

    def wait(self) -> None:
        """Bloqueia a thread atual até que a próxima requisição seja permitida."""
        if self.delay <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_allowed - now
            self._next_allowed = max(now, self._next_allowed) + self.delay
        if sleep_for > 0:
            time.sleep(sleep_for)


class Fetcher:
    """Envelopa ``requests.Session`` com retries, backoff e robots.txt."""

    def __init__(self, config: CrawlConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
            }
        )
        self.limiter = RateLimiter(config.delay)
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = threading.Lock()

    # ------------------------------------------------------------------ robots
    def allowed_by_robots(self, url: str) -> bool:
        """Verifica se a URL pode ser acessada segundo o ``robots.txt``."""
        if not self.config.respect_robots:
            return True
        parts = urlparse(url)
        if not parts.scheme or not parts.netloc:
            return True
        parser = self._robots_parser(f"{parts.scheme}://{parts.netloc}")
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.config.user_agent, url)
        except Exception:  # pragma: no cover - defensivo
            return True

    def _robots_parser(self, base_url: str) -> RobotFileParser | None:
        with self._robots_lock:
            if base_url in self._robots:
                return self._robots[base_url]

        parser: RobotFileParser | None = RobotFileParser()
        try:
            response = requests.get(
                f"{base_url}/robots.txt",
                headers={"User-Agent": self.config.user_agent},
                timeout=min(self.config.timeout, 15.0),
            )
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
            else:
                parser = None
        except requests.RequestException as exc:
            LOG.warning("Não foi possível ler robots.txt de %s: %s", base_url, exc)
            parser = None

        with self._robots_lock:
            self._robots[base_url] = parser
        return parser

    # ------------------------------------------------------------------ fetch
    def fetch(self, url: str) -> FetchResult:
        """Baixa uma URL aplicando retries com backoff exponencial."""
        last_error = "erro desconhecido"
        for attempt in range(self.config.retries + 1):
            self.limiter.wait()
            started = time.monotonic()
            try:
                response = self.session.get(url, timeout=self.config.timeout, stream=False)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                LOG.debug("Tentativa %d falhou para %s: %s", attempt + 1, url, last_error)
            else:
                elapsed = time.monotonic() - started
                if response.status_code in RETRYABLE_STATUS and attempt < self.config.retries:
                    last_error = f"HTTP {response.status_code}"
                elif response.status_code >= 400:
                    return FetchResult(
                        url=url,
                        status=response.status_code,
                        headers=_normalize_headers(response),
                        final_url=response.url,
                        error=f"HTTP {response.status_code}",
                        elapsed=elapsed,
                    )
                else:
                    return FetchResult(
                        url=url,
                        status=response.status_code,
                        content=response.content,
                        headers=_normalize_headers(response),
                        final_url=response.url,
                        elapsed=elapsed,
                    )

            if attempt < self.config.retries:
                backoff = min(2.0 ** attempt, 8.0)
                LOG.debug("Aguardando %.1fs antes de tentar %s novamente", backoff, url)
                time.sleep(backoff)

        return FetchResult(url=url, final_url=url, error=last_error)

    def close(self) -> None:
        """Fecha a sessão HTTP."""
        self.session.close()
