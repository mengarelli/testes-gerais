"""Gravação do espelho do site em disco e manifesto de execução."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .urls import local_path_for

META_DIRNAME = "_crawl"


class LocalStore:
    """Escreve arquivos do espelho preservando a estrutura de URLs.

    Os caminhos são derivados deterministicamente por
    :func:`amatra_crawler.urls.local_path_for`.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.meta_dir = self.root / META_DIRNAME

    def ensure_dirs(self) -> None:
        """Cria o diretório raiz do espelho e o diretório de metadados."""
        self.root.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, url: str) -> Path:
        """Retorna o caminho absoluto em disco para uma URL."""
        return self.root / local_path_for(url)

    def exists(self, url: str) -> bool:
        """Indica se o arquivo correspondente à URL já existe no espelho."""
        return self.path_for(url).exists()

    def save(self, url: str, content: bytes) -> tuple[Path, int]:
        """Grava o conteúdo de forma atômica (tmp + rename).

        Returns:
            Tupla ``(caminho, bytes_gravados)``.
        """
        path = self.path_for(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(content)
        tmp.replace(path)
        return path, len(content)

    def relative_path(self, url: str) -> str:
        """Retorna o caminho relativo (POSIX) da URL dentro do espelho."""
        return local_path_for(url)


class Manifest:
    """Registro incremental (JSON Lines) de tudo que foi processado."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._file = self.path.open("a", encoding="utf-8")

    def append(self, record: dict) -> None:
        """Adiciona um registro ao manifesto (thread-safe)."""
        with self._lock:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()

    def close(self) -> None:
        """Fecha o arquivo do manifesto."""
        with self._lock:
            if not self._file.closed:
                self._file.close()
