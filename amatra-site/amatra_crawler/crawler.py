"""Motor de crawling: orquestra fila, workers, reescrita e persistência."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import CrawlConfig
from .fetcher import Fetcher
from .parser import (
    classify_link,
    decode_body,
    ensure_utf8_charset,
    extract_links,
    rewrite_css,
    rewrite_link,
)
from .storage import LocalStore, Manifest
from .urls import is_internal_url, normalize_url

LOG = logging.getLogger(__name__)

PAGE = "page"
ASSET = "asset"

HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/xml", "application/xml")
CSS_CONTENT_TYPES = ("text/css",)


@dataclass
class Task:
    """Unidade de trabalho da fila do crawler."""

    url: str
    depth: int = 0
    kind: str = PAGE


@dataclass
class Stats:
    """Estatísticas consolidadas de uma execução."""

    pages_saved: int = 0
    pages_failed: int = 0
    assets_saved: int = 0
    assets_failed: int = 0
    skipped: int = 0
    blocked: int = 0
    bytes_downloaded: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    @property
    def duration(self) -> float:
        """Duração da execução em segundos."""
        end = self.finished_at if self.finished_at is not None else time.time()
        return end - self.started_at

    def as_dict(self) -> dict:
        """Serializa as estatísticas para JSON."""
        data = {
            field_name: getattr(self, field_name)
            for field_name in (
                "pages_saved",
                "pages_failed",
                "assets_saved",
                "assets_failed",
                "skipped",
                "blocked",
                "bytes_downloaded",
            )
        }
        data["duration_seconds"] = round(self.duration, 2)
        data["started_at"] = datetime.fromtimestamp(self.started_at, timezone.utc).isoformat()
        if self.finished_at is not None:
            data["finished_at"] = datetime.fromtimestamp(
                self.finished_at, timezone.utc
            ).isoformat()
        return data


class SiteCrawler:
    """Faz o espelhamento de um site respeitando hosts, robots e limites."""

    def __init__(
        self,
        config: CrawlConfig,
        fetcher: Fetcher | None = None,
        store: LocalStore | None = None,
    ) -> None:
        self.config = config
        self.hosts = config.resolved_allowed_hosts()
        self.store = store or LocalStore(config.output_dir)
        self.fetcher = fetcher or Fetcher(config)
        self.manifest = Manifest(self.store.meta_dir / "manifest.jsonl")
        self.state_path = self.store.meta_dir / "state.json"
        self.summary_path = self.store.meta_dir / "summary.json"

        self.seen: set[str] = set()
        self.pending: deque[Task] = deque()
        self.stats = Stats()
        self._pages_started = 0
        self._state_lock = threading.Lock()
        self._exclude = [re.compile(pattern) for pattern in config.exclude_patterns]

    # ------------------------------------------------------------------ estado
    def _load_state(self) -> bool:
        """Carrega o estado de uma execução anterior. Retorna True se carregou."""
        if not self.state_path.exists():
            return False
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning("Estado anterior inválido (%s); ignorando.", exc)
            return False

        self.seen = {normalize_url(url) for url in state.get("seen", [])}
        self.pending = deque(
            Task(item["url"], item.get("depth", 0), item.get("kind", PAGE))
            for item in state.get("pending", [])
        )
        self.stats.bytes_downloaded = state.get("bytes_downloaded", 0)
        LOG.info(
            "Estado retomado: %d URLs vistas, %d pendentes.",
            len(self.seen),
            len(self.pending),
        )
        return True

    def _save_state(self) -> None:
        """Persiste o estado (vistos + pendentes) para permitir retomada."""
        state = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "seen": sorted(self.seen),
            "pending": [
                {"url": task.url, "depth": task.depth, "kind": task.kind}
                for task in self.pending
            ],
            "bytes_downloaded": self.stats.bytes_downloaded,
        }
        tmp = self.state_path.with_suffix(".tmp")
        with self._state_lock:
            tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.state_path)

    # ------------------------------------------------------------------ fila
    def _enqueue(self, tasks) -> None:
        """Adiciona tarefas à fila, deduplicando por URL normalizada."""
        for task in tasks:
            url = normalize_url(task.url)
            if url in self.seen:
                continue
            if not is_internal_url(url, self.hosts):
                continue
            if self._is_excluded(url):
                self.stats.skipped += 1
                continue
            self.seen.add(url)
            self.pending.append(Task(url, task.depth, task.kind))

    def _is_excluded(self, url: str) -> bool:
        """Indica se a URL casa com algum padrão de exclusão configurado."""
        return any(pattern.search(url) for pattern in self._exclude)

    def _page_limit_reached(self) -> bool:
        return self.config.max_pages is not None and self._pages_started >= self.config.max_pages

    def _fill_pool(self, pool: ThreadPoolExecutor, futures: dict[Future, Task]) -> None:
        while self.pending and len(futures) < self.config.workers:
            task = self.pending.popleft()
            if task.kind == PAGE:
                if self._page_limit_reached():
                    self.stats.skipped += 1
                    continue
                self._pages_started += 1
            futures[pool.submit(self._process, task)] = task

    def _prepare_frontier(self) -> None:
        """Define a fronteira inicial: estado anterior ou sementes+sitemaps."""
        if not self.config.overwrite and self._load_state():
            return
        self._enqueue(Task(url, 0, PAGE) for url in self.config.start_urls)
        if self.config.use_sitemaps:
            for url in self._discover_sitemap_urls():
                self._enqueue([Task(url, 0, PAGE)])

    # ------------------------------------------------------------------ sitemaps
    def _discover_sitemap_urls(self, max_sitemaps: int = 100) -> list[str]:
        """Descobre URLs a partir de sitemaps XML, seguindo índices aninhados."""
        import xml.etree.ElementTree as ET

        candidates = []
        for host in sorted(self.hosts):
            base = f"https://{host}"
            candidates.extend([f"{base}/sitemap_index.xml", f"{base}/sitemap.xml"])

        urls: list[str] = []
        visited: set[str] = set()
        queue = list(candidates)

        while queue and len(visited) < max_sitemaps:
            sitemap_url = queue.pop(0)
            if sitemap_url in visited:
                continue
            visited.add(sitemap_url)

            result = self.fetcher.fetch(sitemap_url)
            if not result.ok:
                LOG.debug("Sitemap indisponível (%s): %s", sitemap_url, result.status)
                continue
            try:
                root = ET.fromstring(result.content)
            except ET.ParseError:
                LOG.debug("Sitemap inválido: %s", sitemap_url)
                continue

            is_index = root.tag.lower().endswith("sitemapindex")
            for element in root.iter():
                if not element.tag.lower().endswith("loc") or not element.text:
                    continue
                loc = element.text.strip()
                if is_index:
                    queue.append(loc)
                else:
                    urls.append(loc)

        LOG.info("Sitemaps: %d URLs descobertas via %d arquivos.", len(urls), len(visited))
        return urls

    # ------------------------------------------------------------------ workers
    def _process(self, task: Task) -> list[Task]:
        """Processa uma tarefa e devolve novas tarefas descobertas."""
        url = task.url

        if not self.fetcher.allowed_by_robots(url):
            LOG.info("Bloqueado por robots.txt: %s", url)
            self.stats.blocked += 1
            self._record(task, status=None, note="blocked_by_robots")
            return []

        if task.kind == ASSET and not self.config.overwrite and self.store.exists(url):
            self.stats.skipped += 1
            return []

        result = self.fetcher.fetch(url)
        if not result.ok:
            self._on_failure(task, result)
            return []

        base_url = result.final_url or url
        if task.kind == PAGE and self._looks_like_html(result, base_url):
            return self._save_page(task, result, base_url)
        if task.kind == PAGE:
            # Página que na verdade retorna um recurso (ex.: PDF).
            task.kind = ASSET
        return self._save_asset(task, result, base_url)

    def _looks_like_html(self, result, base_url: str) -> bool:
        content_type = result.content_type
        if content_type in HTML_CONTENT_TYPES or content_type.startswith("text/html"):
            return True
        if not content_type:
            suffix = base_url.rsplit("?", 1)[0].rsplit(".", 1)[-1].lower()
            return suffix in ("html", "htm", "php", "xhtml")
        return False

    def _save_page(self, task: Task, result, base_url: str) -> list[Task]:
        """Salva uma página HTML reescrevendo links e enfileirando descobertas."""
        soup, links = extract_links(result.content, base_url)
        ensure_utf8_charset(soup)
        page_rel = self.store.relative_path(task.url)

        new_tasks: list[Task] = []
        for link in links:
            for absolute in link.urls:
                kind = classify_link(absolute, self.hosts)
                if kind is None:
                    continue
                if kind == ASSET and not self.config.include_assets:
                    continue
                if kind == PAGE and self.config.max_depth is not None:
                    if task.depth + 1 > self.config.max_depth:
                        continue
                new_tasks.append(
                    Task(absolute, task.depth + 1 if kind == PAGE else task.depth, kind)
                )
            rewrite_link(
                link, base_url, page_rel, self.hosts, self.config.include_assets
            )

        html_out = str(soup).encode("utf-8")
        path, size = self.store.save(task.url, html_out)
        self.stats.pages_saved += 1
        self.stats.bytes_downloaded += size
        LOG.info("[página] %s -> %s (%d bytes)", task.url, page_rel, size)
        self._record(task, status=result.status, size=size, path=path, content_type="text/html")
        return new_tasks

    def _save_asset(self, task: Task, result, base_url: str) -> list[Task]:
        """Salva um recurso; CSS tem suas referências reescritas e enfileiradas."""
        content = result.content
        asset_rel = self.store.relative_path(task.url)
        new_tasks: list[Task] = []

        if self.config.include_assets and self._is_css(result, base_url):
            charset = "utf-8"
            declared = result.headers.get("content-type", "")
            if "charset=" in declared:
                charset = declared.split("charset=")[-1].strip().strip('"')
            css_text = decode_body(content, charset)
            new_css, discovered = rewrite_css(css_text, base_url, asset_rel)
            content = new_css.encode("utf-8")
            for absolute in discovered:
                if classify_link(absolute, self.hosts) is None:
                    continue
                new_tasks.append(Task(absolute, task.depth, ASSET))

        path, size = self.store.save(task.url, content)
        self.stats.assets_saved += 1
        self.stats.bytes_downloaded += size
        LOG.debug("[recurso] %s -> %s (%d bytes)", task.url, asset_rel, size)
        self._record(
            task,
            status=result.status,
            size=size,
            path=path,
            content_type=result.content_type,
        )
        return new_tasks

    @staticmethod
    def _is_css(result, base_url: str) -> bool:
        if result.content_type in CSS_CONTENT_TYPES:
            return True
        return base_url.rsplit("?", 1)[0].lower().endswith(".css")

    def _on_failure(self, task: Task, result) -> None:
        if task.kind == PAGE:
            self.stats.pages_failed += 1
        else:
            self.stats.assets_failed += 1
        LOG.warning("Falha ao baixar %s: %s", task.url, result.error or result.status)
        self._record(task, status=result.status, error=result.error or "erro")

    # ------------------------------------------------------------------ registro
    def _record(self, task: Task, **extra) -> None:
        record = {
            "url": task.url,
            "kind": task.kind,
            "depth": task.depth,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        for key, value in extra.items():
            record[key] = str(value) if key == "path" and value is not None else value
        self.manifest.append(record)

    # ------------------------------------------------------------------ execução
    def run(self) -> Stats:
        """Executa o crawl até esvaziar a fila (ou o limite de páginas)."""
        self.store.ensure_dirs()
        self._prepare_frontier()

        futures: dict[Future, Task] = {}
        try:
            with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
                while True:
                    self._fill_pool(pool, futures)
                    if not futures:
                        break
                    done, _ = wait(list(futures), return_when=FIRST_COMPLETED)
                    for future in done:
                        task = futures.pop(future)
                        try:
                            new_tasks = future.result()
                        except Exception as exc:  # pragma: no cover - defensivo
                            LOG.error("Erro inesperado em %s: %s", task.url, exc)
                            self._on_failure(task, type("R", (), {"error": str(exc), "status": None})())
                            new_tasks = []
                        self._enqueue(new_tasks)
            self._save_state()
        except KeyboardInterrupt:
            LOG.warning("Interrompido pelo usuário. Salvando estado para retomada...")
            self._save_state()
            raise
        finally:
            self.stats.finished_at = time.time()
            self._write_summary()
            self.manifest.close()
            self.fetcher.close()
        return self.stats

    def _write_summary(self) -> None:
        summary = self.stats.as_dict()
        summary["config"] = {
            "start_urls": self.config.start_urls,
            "output_dir": str(self.config.output_dir),
            "allowed_hosts": sorted(self.hosts),
            "include_assets": self.config.include_assets,
            "max_depth": self.config.max_depth,
            "max_pages": self.config.max_pages,
            "workers": self.config.workers,
            "delay": self.config.delay,
            "exclude_patterns": self.config.exclude_patterns,
        }
        try:
            self.summary_path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:  # pragma: no cover - defensivo
            LOG.error("Não foi possível gravar o resumo: %s", exc)
