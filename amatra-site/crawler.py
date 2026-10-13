#!/usr/bin/env python3
"""CLI do crawler de espelhamento do site da AMATRA 9.

Exemplos::

    # Espelha o site inteiro (HTML + assets) em ./site
    python crawler.py --output site

    # Apenas HTML, 200 páginas no máximo, 4 workers
    python crawler.py --no-assets --max-pages 200 --workers 4

    # Recomeça do zero (ignora estado anterior)
    python crawler.py --overwrite
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from amatra_crawler import CrawlConfig, DEFAULT_START_URL, SiteCrawler


def build_parser() -> argparse.ArgumentParser:
    """Monta o parser de argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        prog="crawler.py",
        description="Baixa todo o conteúdo de um site (mirror) para redesenho.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--start-url",
        dest="start_urls",
        action="append",
        metavar="URL",
        help="URL semente (pode ser repetida).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("site"),
        help="Diretório onde o espelho será gravado.",
    )
    parser.add_argument("--workers", type=int, default=8, help="Threads simultâneas.")
    parser.add_argument("--delay", type=float, default=0.2, help="Intervalo mínimo entre requisições (s).")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout por requisição (s).")
    parser.add_argument("--retries", type=int, default=3, help="Tentativas adicionais em caso de erro.")
    parser.add_argument("--max-pages", type=int, default=None, help="Máximo de páginas HTML a baixar.")
    parser.add_argument("--max-depth", type=int, default=None, help="Profundidade máxima de páginas.")
    parser.add_argument(
        "--extra-host",
        dest="extra_hosts",
        action="append",
        default=[],
        metavar="HOST",
        help="Host adicional permitido (ex.: CDN). Pode ser repetido.",
    )
    parser.add_argument("--no-assets", action="store_true", help="Baixa apenas HTML (sem imagens/CSS/JS/PDF).")
    parser.add_argument("--no-sitemaps", action="store_true", help="Não usar sitemaps XML para descobrir URLs.")
    parser.add_argument(
        "--exclude",
        dest="exclude",
        action="append",
        default=[],
        metavar="REGEX",
        help="Ignora URLs que casem com a expressão regular. Pode ser repetida.",
    )
    parser.add_argument("--no-robots", action="store_true", help="Ignorar o robots.txt do site.")
    parser.add_argument("--overwrite", action="store_true", help="Ignora estado anterior e rebaixa tudo.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Log em nível DEBUG.")
    return parser


def build_config(args: argparse.Namespace) -> CrawlConfig:
    """Converte argumentos de CLI em uma :class:`CrawlConfig`."""
    return CrawlConfig(
        start_urls=args.start_urls or [DEFAULT_START_URL],
        output_dir=args.output,
        extra_allowed_hosts=set(args.extra_hosts),
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        include_assets=not args.no_assets,
        delay=args.delay,
        workers=max(1, args.workers),
        timeout=args.timeout,
        retries=max(0, args.retries),
        respect_robots=not args.no_robots,
        use_sitemaps=not args.no_sitemaps,
        overwrite=args.overwrite,
        log_level="DEBUG" if args.verbose else "INFO",
        exclude_patterns=args.exclude,
    )


def configure_logging(level: str) -> None:
    """Configura o logging para stdout."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada da CLI. Retorna o código de saída do processo."""
    args = build_parser().parse_args(argv)
    config = build_config(args)
    configure_logging(config.log_level)

    logging.getLogger(__name__).info(
        "Iniciando crawl de %s em %s", ", ".join(config.start_urls), config.output_dir
    )
    stats = SiteCrawler(config).run()
    summary = stats.as_dict()

    logging.getLogger(__name__).info(
        "Concluído em %.1fs | páginas=%d (falhas=%d) | recursos=%d (falhas=%d) | "
        "ignorados=%d | bloqueados=%d | %.2f MB",
        summary["duration_seconds"],
        summary["pages_saved"],
        summary["pages_failed"],
        summary["assets_saved"],
        summary["assets_failed"],
        summary["skipped"],
        summary["blocked"],
        summary["bytes_downloaded"] / 1024 / 1024,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
