"""Extração e reescrita de links em HTML e CSS.

Este módulo é responsável por:

* localizar todas as URLs relevantes de um documento HTML (links de páginas e
  recursos como imagens, CSS, JS, PDFs, vídeos e fontes);
* localizar URLs referenciadas dentro de arquivos CSS (``url(...)`` e
  ``@import``);
* reescrever essas URLs para caminhos locais, permitindo navegar no espelho
  do site offline.

A reescrita é **idempotente**: ela sempre parte do valor original do atributo
(``ExtractedLink.raw_value``), e não do valor já reescrito.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .urls import (
    is_asset_url,
    is_internal_url,
    local_path_for,
    normalize_url,
    relative_link,
)

# Pares (tag, atributo) que contêm uma única URL.
SINGLE_URL_ATTRS: tuple[tuple[str, str], ...] = (
    ("a", "href"),
    ("area", "href"),
    ("link", "href"),
    ("script", "src"),
    ("img", "src"),
    ("source", "src"),
    ("video", "src"),
    ("video", "poster"),
    ("audio", "src"),
    ("embed", "src"),
    ("object", "data"),
    ("track", "src"),
    ("iframe", "src"),
    ("input", "src"),
)

# Pares (tag, atributo) que contêm listas ``srcset``.
SRCSET_ATTRS: tuple[tuple[str, str], ...] = (
    ("img", "srcset"),
    ("source", "srcset"),
)

_CSS_URL_RE = re.compile(r"""url\(\s*(?P<quote>['"]?)(?P<url>[^'")]+)(?P=quote)\s*\)""", re.I)
_CSS_IMPORT_RE = re.compile(
    r"""@import\s+(?:url\(\s*(?P<quote1>['"]?)(?P<url1>[^'")]+)(?P=quote1)\s*\)"""
    r"""|(?P<quote2>['"])(?P<url2>[^'"]+)(?P=quote2))""",
    re.I,
)


@dataclass
class ExtractedLink:
    """URL(s) encontradas em um atributo de um elemento HTML.

    Attributes:
        element: Elemento HTML de origem.
        attribute: Nome do atributo (``href``, ``src``, ``srcset``...).
        urls: URLs absolutas e normalizadas presentes no atributo.
        raw_value: Valor original do atributo (base para reescrita idempotente).
        is_srcset: Indica se o atributo é uma lista ``srcset``.
    """

    element: Tag
    attribute: str
    urls: list[str] = field(default_factory=list)
    raw_value: str = ""
    is_srcset: bool = False

    @property
    def url(self) -> str:
        """Primeira URL do atributo (conveniência para atributos simples)."""
        return self.urls[0] if self.urls else ""


def decode_body(content: bytes, default_encoding: str = "utf-8") -> str:
    """Decodifica bytes tentando o encoding informado, ``utf-8`` e ``latin-1``."""
    for encoding in (default_encoding, "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def parse_html(markup: bytes | str) -> BeautifulSoup:
    """Faz o parse de HTML com o parser nativo (``html.parser``)."""
    return BeautifulSoup(markup, "html.parser")


def ensure_utf8_charset(soup: BeautifulSoup) -> None:
    """Garante que a página declare ``charset=utf-8``.

    Como o espelho grava todo o HTML em UTF-8, meta tags antigas de
    ``iso-8859-1`` causariam caracteres corrompidos ao abrir o arquivo local.
    """
    for meta in soup.find_all("meta"):
        if meta.get("charset"):
            meta["charset"] = "utf-8"
            return
        if (meta.get("http-equiv") or "").lower() == "content-type":
            meta["content"] = "text/html; charset=utf-8"
            return
    if soup.head is not None:
        soup.head.insert(0, soup.new_tag("meta", charset="utf-8"))


def _split_srcset(value: str) -> Iterator[tuple[str, str]]:
    """Itera pelos pares ``(url, descritor)`` de um atributo ``srcset``."""
    for candidate in value.split(","):
        candidate = candidate.strip()
        if not candidate:
            continue
        parts = candidate.split()
        url, descriptor = parts[0], " ".join(parts[1:])
        yield url, descriptor


def _absolutize(raw_url: str, base_url: str) -> str | None:
    raw_url = raw_url.strip()
    if not raw_url or raw_url.startswith(("data:", "mailto:", "tel:", "javascript:", "blob:")):
        return None
    absolute = normalize_url(urljoin(base_url, raw_url))
    if not absolute.startswith(("http://", "https://")):
        return None
    return absolute


def extract_links(
    markup: bytes | str, base_url: str
) -> tuple[BeautifulSoup, list[ExtractedLink]]:
    """Extrai todas as URLs relevantes de um documento HTML.

    Args:
        markup: Conteúdo HTML (bytes ou str).
        base_url: URL efetiva do documento, usada para resolver URLs relativas.

    Returns:
        Tupla ``(soup, links)`` com a árvore parseada (para reescrita) e a
        lista de links encontrados, já em formato absoluto e normalizado.
    """
    soup = parse_html(markup)
    links: list[ExtractedLink] = []

    for tag_name, attr in SINGLE_URL_ATTRS:
        for element in soup.find_all(tag_name):
            raw = element.get(attr)
            if not isinstance(raw, str) or not raw.strip():
                continue
            absolute = _absolutize(raw, base_url)
            if absolute is None:
                continue
            links.append(ExtractedLink(element, attr, [absolute], raw))

    for tag_name, attr in SRCSET_ATTRS:
        for element in soup.find_all(tag_name):
            raw = element.get(attr)
            if not isinstance(raw, str) or not raw.strip():
                continue
            candidates = [
                absolute
                for candidate_url, _ in _split_srcset(raw)
                if (absolute := _absolutize(candidate_url, base_url))
            ]
            if candidates:
                links.append(ExtractedLink(element, attr, candidates, raw, is_srcset=True))

    return soup, links


def classify_link(url: str, allowed_hosts: set[str]) -> str | None:
    """Classifica um link como ``"page"``, ``"asset"`` ou ``None`` (externo)."""
    if not is_internal_url(url, allowed_hosts):
        return None
    return "asset" if is_asset_url(url) else "page"


def _should_rewrite(absolute: str, allowed_hosts: set[str], include_assets: bool) -> bool:
    """Decide se uma URL interna deve ser reescrita para caminho local."""
    if not is_internal_url(absolute, allowed_hosts):
        return False
    if not include_assets and is_asset_url(absolute):
        return False
    return True


def rewrite_link(
    link: ExtractedLink,
    base_url: str,
    current_page_rel: str,
    allowed_hosts: set[str],
    include_assets: bool = True,
) -> None:
    """Reescreve, in-place, as URLs internas do elemento para caminhos locais.

    Args:
        link: Link extraído do documento.
        base_url: URL absoluta do documento (base para resolver relativos).
        current_page_rel: Caminho local (POSIX) da página que está sendo salva.
        allowed_hosts: Hosts internos; links externos são preservados.
        include_assets: Se ``False``, recursos (imagens/CSS/JS/PDF) não são
            reescritos, pois não estarão disponíveis no espelho.
    """
    if not link.is_srcset:
        if _should_rewrite(link.url, allowed_hosts, include_assets):
            link.element[link.attribute] = relative_link(
                current_page_rel, local_path_for(link.url)
            )
        return

    rebuilt: list[str] = []
    for candidate_url, descriptor in _split_srcset(link.raw_value):
        absolute = _absolutize(candidate_url, base_url)
        if absolute is not None and _should_rewrite(absolute, allowed_hosts, include_assets):
            candidate = relative_link(current_page_rel, local_path_for(absolute))
        else:
            candidate = candidate_url
        rebuilt.append(f"{candidate} {descriptor}".strip())
    link.element[link.attribute] = ", ".join(rebuilt)


def rewrite_css(css_text: str, base_url: str, css_rel_path: str) -> tuple[str, set[str]]:
    """Reescreve ``url(...)`` e ``@import`` de um CSS para caminhos locais.

    Args:
        css_text: Conteúdo textual do CSS.
        base_url: URL absoluta do arquivo CSS (base para resolver relativos).
        css_rel_path: Caminho local (POSIX) onde o CSS será gravado.

    Returns:
        Tupla ``(novo_css, urls_absolutas)``, em que ``urls_absolutas`` contém
        os destinos encontrados (para enfileiramento do download).
    """
    discovered: set[str] = set()

    def _rewrite_reference(raw_url: str) -> str:
        absolute = _absolutize(raw_url, base_url)
        if absolute is None:
            return raw_url
        discovered.add(absolute)
        return relative_link(css_rel_path, local_path_for(absolute))

    def _replace(match: re.Match[str]) -> str:
        quote = match.group("quote") or ""
        local = _rewrite_reference(match.group("url"))
        return f"url({quote}{local}{quote})"

    def _replace_import(match: re.Match[str]) -> str:
        raw_url = (match.group("url1") or match.group("url2") or "").strip()
        quote = match.group("quote1") or match.group("quote2") or ""
        local = _rewrite_reference(raw_url)
        return f"@import {quote}{local}{quote}"

    new_css = _CSS_IMPORT_RE.sub(_replace_import, css_text)
    new_css = _CSS_URL_RE.sub(_replace, new_css)
    return new_css, discovered
