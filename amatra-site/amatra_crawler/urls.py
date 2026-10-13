"""Normalização de URLs e mapeamento URL -> caminho local.

O mapeamento é **determinístico**: a mesma URL sempre gera o mesmo caminho
local. Isso permite reescrever links do espelho sem precisar conhecer
previamente todo o conjunto de páginas já baixadas.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urldefrag, urlsplit, urlunsplit

# Extensões tratadas como recursos (arquivos), e não como páginas HTML.
ASSET_EXTENSIONS: frozenset[str] = frozenset(
    {
        # imagens
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp",
        ".tif", ".tiff", ".avif", ".heic",
        # folhas de estilo / scripts / dados
        ".css", ".js", ".mjs", ".json", ".xml", ".rss", ".atom", ".txt", ".csv",
        # documentos
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".odt", ".ods", ".odp", ".epub", ".rtf",
        # arquivos compactados
        ".zip", ".rar", ".7z", ".gz", ".tar", ".tgz",
        # mídia
        ".mp3", ".mp4", ".webm", ".ogg", ".oga", ".wav", ".avi", ".mov",
        ".m4a", ".m4v", ".flv", ".wmv",
        # fontes
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
    }
)

# Extensões consideradas páginas navegáveis.
PAGE_EXTENSIONS: frozenset[str] = frozenset(
    {"", ".html", ".htm", ".php", ".asp", ".aspx", ".jsp", ".shtml", ".xhtml"}
)

_UNSAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._~@%+=,-]")
_INDEX_NAMES = {"index.html", "index.htm"}


def normalize_url(url: str) -> str:
    """Normaliza uma URL para uso como chave de deduplicação.

    Remove fragmentos (``#...``), normaliza *scheme*/host para minúsculas,
    remove a porta padrão e garante um *path* mínimo de ``/``.
    """
    url, _ = urldefrag(url)
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if (scheme == "http" and netloc.endswith(":80")) or (
        scheme == "https" and netloc.endswith(":443")
    ):
        netloc = netloc.rsplit(":", 1)[0]
    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def host_of(url: str) -> str:
    """Retorna o host (netloc) normalizado de uma URL."""
    return urlsplit(url).netloc.lower()


def path_suffix(url: str) -> str:
    """Retorna a extensão (minúscula) do último segmento do path da URL."""
    path = urlsplit(url).path
    segment = path.rsplit("/", 1)[-1]
    if "." not in segment:
        return ""
    return "." + segment.rsplit(".", 1)[-1].lower()


def is_asset_url(url: str) -> bool:
    """Indica se a URL aponta para um recurso (imagem, CSS, JS, PDF...).

    URLs com *query string* ou sem extensão conhecida são tratadas como
    páginas navegáveis por padrão.
    """
    suffix = path_suffix(url)
    if suffix in ASSET_EXTENSIONS:
        return True
    if suffix in PAGE_EXTENSIONS:
        return False
    # Extensão desconhecida: trata como recurso para não perder o arquivo.
    return bool(suffix)


def is_internal_url(url: str, allowed_hosts: set[str]) -> bool:
    """Indica se a URL pertence a um dos hosts internos permitidos."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        return False
    return parts.netloc.lower() in allowed_hosts


def _sanitize_segment(segment: str) -> str:
    cleaned = _UNSAFE_SEGMENT.sub("_", segment)
    cleaned = cleaned.strip(".")
    return cleaned or "_"


def _sanitize_host(netloc: str) -> str:
    return _UNSAFE_SEGMENT.sub("_", netloc.lower()) or "unknown-host"


def local_path_for(url: str) -> str:
    """Converte uma URL em um caminho relativo (POSIX) dentro do espelho.

    Regras principais:

    * o host vira o primeiro diretório (``www.amatra9.org.br/index.html``);
    * URLs terminando em ``/`` ou sem extensão viram ``.../index.html``;
    * *query strings* são convertidas em um sufixo determinístico
      (``__q<sha1>``) para evitar colisões entre URLs distintas.

    Args:
        url: URL absoluta já normalizada.

    Returns:
        Caminho relativo (com separador ``/``) dentro do diretório de saída.
    """
    parts = urlsplit(normalize_url(url))
    host = _sanitize_host(parts.netloc)
    raw_path = unquote(parts.path or "/")
    had_trailing_slash = raw_path.endswith("/") or raw_path == ""

    normalized_path = posixpath.normpath(raw_path)
    segments = [
        _sanitize_segment(seg)
        for seg in normalized_path.split("/")
        if seg not in ("", ".", "..")
    ]

    name = segments.pop() if segments else ""
    is_page_like = had_trailing_slash or "." not in name
    if is_page_like:
        if name:
            segments.append(name)
        name = "index.html"

    if parts.query:
        stem, dot, ext = name.rpartition(".")
        digest = hashlib.sha1(parts.query.encode("utf-8")).hexdigest()[:10]
        name = f"{stem}__q{digest}.{ext}" if dot else f"{name}__q{digest}"

    return "/".join([host, *segments, name])


def relative_link(from_local_path: str, to_local_path: str) -> str:
    """Calcula um link relativo entre dois arquivos do espelho.

    Args:
        from_local_path: Caminho local (POSIX) da página de origem.
        to_local_path: Caminho local (POSIX) do destino.

    Returns:
        Caminho relativo utilizável em atributos ``href``/``src``.
    """
    from_dir = str(PurePosixPath(from_local_path).parent)
    return posixpath.relpath(to_local_path, start=from_dir)


def is_index_path(rel_path: str) -> bool:
    """Indica se o caminho relativo corresponde a um arquivo de índice."""
    return PurePosixPath(rel_path).name in _INDEX_NAMES
