"""Configuração do crawler."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_START_URL = "https://www.amatra9.org.br/"
DEFAULT_USER_AGENT = (
    "AmatraSiteCrawler/1.0 (+redesign do site; node amatra-site)"
)


@dataclass
class CrawlConfig:
    """Parâmetros que controlam o comportamento do crawler.

    Atributos:
        start_urls: URLs semente do crawl.
        output_dir: Diretório raiz onde o espelho do site será gravado.
        allowed_hosts: Hosts internos permitidos. Se vazio, é derivado das
            ``start_urls``.
        extra_allowed_hosts: Hosts adicionais permitidos (ex.: CDN do site).
        max_depth: Profundidade máxima de páginas (``None`` = ilimitado).
        max_pages: Número máximo de páginas HTML a baixar (``None`` = ilimitado).
        include_assets: Se ``False``, baixa apenas HTML (sem imagens/CSS/JS/PDF).
        delay: Intervalo mínimo, em segundos, entre requisições (rate limiting).
        workers: Número de threads de download simultâneas.
        timeout: Timeout de leitura/connect em segundos.
        retries: Número de tentativas adicionais em caso de erro/timeout.
        user_agent: Cabeçalho User-Agent enviado nas requisições.
        respect_robots: Se ``True``, respeita o ``robots.txt`` do site.
        use_sitemaps: Se ``True``, descobre URLs extras via sitemaps XML.
        overwrite: Se ``True``, ignora estado anterior e rebaixa tudo.
        log_level: Nível de log do pacote.
    """

    start_urls: list[str] = field(default_factory=lambda: [DEFAULT_START_URL])
    output_dir: Path = Path("site")
    allowed_hosts: set[str] = field(default_factory=set)
    extra_allowed_hosts: set[str] = field(default_factory=set)
    max_depth: int | None = None
    max_pages: int | None = None
    include_assets: bool = True
    delay: float = 0.2
    workers: int = 8
    timeout: float = 30.0
    retries: int = 3
    user_agent: str = DEFAULT_USER_AGENT
    respect_robots: bool = True
    use_sitemaps: bool = True
    overwrite: bool = False
    log_level: str = "INFO"
    # Expressões regulares (aplicadas à URL completa) que devem ser ignoradas.
    exclude_patterns: list[str] = field(default_factory=list)

    def resolved_allowed_hosts(self) -> set[str]:
        """Retorna o conjunto final de hosts internos permitidos."""
        if self.allowed_hosts:
            return {h.lower() for h in self.allowed_hosts} | {
                h.lower() for h in self.extra_allowed_hosts
            }
        hosts = set()
        for url in self.start_urls:
            host = url.split("//", 1)[-1].split("/", 1)[0].lower()
            if host:
                hosts.add(host)
        return hosts | {h.lower() for h in self.extra_allowed_hosts}
