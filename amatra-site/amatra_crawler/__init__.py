"""Pacote do crawler de espelhamento (mirror) do site da AMATRA 9.

O objetivo é baixar todo o conteúdo publicamente acessível de
https://www.amatra9.org.br/ (HTML + assets como imagens, CSS, JS, PDFs)
para permitir um redesenho do site com base no conteúdo atual.

Uso típico (via CLI em ``crawler.py``)::

    python crawler.py --start-url https://www.amatra9.org.br/ --output site
"""

from .config import DEFAULT_START_URL, CrawlConfig
from .crawler import SiteCrawler, Stats
from .fetcher import Fetcher
from .storage import LocalStore

__all__ = [
    "CrawlConfig",
    "DEFAULT_START_URL",
    "Fetcher",
    "LocalStore",
    "SiteCrawler",
    "Stats",
]

__version__ = "1.0.0"
