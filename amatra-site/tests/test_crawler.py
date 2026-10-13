"""Teste de integração do crawler contra um servidor HTTP local.

O teste sobe um ``http.server`` servindo um site fictício em um diretório
temporário e valida que o crawler baixa páginas, recursos, reescreve links
e grava o manifesto/estado sem depender de rede externa.
"""

from __future__ import annotations

import functools
import http.server
import json
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path

from amatra_crawler import CrawlConfig, SiteCrawler

INDEX_HTML = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<link rel="stylesheet" href="/assets/style.css">
</head><body>
<h1>Home</h1>
<a href="/sobre/">Sobre</a>
<a href="https://exemplo.com/">Externo</a>
<img src="/assets/logo.png">
</body></html>
"""

SOBRE_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body><a href="/">Voltar</a><img src="/assets/logo.png"></body></html>
"""

STYLE_CSS = '@import url("base.css");\nbody { background: url(logo.png); }'
BASE_CSS = "h1 { color: #123; }"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args, **kwargs) -> None:  # pragma: no cover
        pass


def _make_site(root: Path) -> None:
    (root / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (root / "sobre").mkdir(parents=True, exist_ok=True)
    (root / "sobre" / "index.html").write_text(SOBRE_HTML, encoding="utf-8")
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "style.css").write_text(STYLE_CSS, encoding="utf-8")
    (root / "assets" / "base.css").write_text(BASE_CSS, encoding="utf-8")
    (root / "assets" / "logo.png").write_bytes(PNG_BYTES)
    (root / "robots.txt").write_text("User-agent: *\nDisallow:\n", encoding="utf-8")


class CrawlerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._site_dir = tempfile.TemporaryDirectory()
        cls._out_dir = tempfile.TemporaryDirectory()
        site_root = Path(cls._site_dir.name)
        _make_site(site_root)

        handler = functools.partial(_SilentHandler, directory=str(site_root))
        cls._server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
        cls._server.daemon_threads = True
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()

        cls.port = cls._server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}/"
        cls.out = Path(cls._out_dir.name) / "site"
        cls.host_dir = cls.out / f"127.0.0.1_{cls.port}"

        config = CrawlConfig(
            start_urls=[cls.base_url],
            output_dir=cls.out,
            use_sitemaps=False,
            delay=0.0,
            workers=4,
            timeout=10.0,
            retries=1,
        )
        cls.stats = SiteCrawler(config).run()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.shutdown()
        cls._server.server_close()
        cls._site_dir.cleanup()
        cls._out_dir.cleanup()

    def test_baixa_pagina_inicial(self) -> None:
        self.assertTrue((self.host_dir / "index.html").is_file())

    def test_baixa_pagina_descoberta(self) -> None:
        self.assertTrue((self.host_dir / "sobre" / "index.html").is_file())

    def test_baixa_assets(self) -> None:
        self.assertTrue((self.host_dir / "assets" / "logo.png").is_file())
        self.assertTrue((self.host_dir / "assets" / "base.css").is_file())

    def test_reescreve_links_internos(self) -> None:
        html = (self.host_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="sobre/index.html"', html)
        self.assertIn('href="assets/style.css"', html)
        self.assertIn('src="assets/logo.png"', html)

    def test_preserva_link_externo(self) -> None:
        html = (self.host_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="https://exemplo.com/"', html)

    def test_reescreve_css_e_baixa_dependencias(self) -> None:
        css = (self.host_dir / "assets" / "style.css").read_text(encoding="utf-8")
        self.assertIn('@import "base.css"', css)
        self.assertIn("url(logo.png)", css)

    def test_manifesto_e_resumo(self) -> None:
        manifest = self.out / "_crawl" / "manifest.jsonl"
        summary = self.out / "_crawl" / "summary.json"
        self.assertTrue(manifest.is_file())
        self.assertTrue(summary.is_file())

        registros = [
            json.loads(line)
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertTrue(any(r["kind"] == "page" for r in registros))
        self.assertTrue(any(r["kind"] == "asset" for r in registros))

        dados = json.loads(summary.read_text(encoding="utf-8"))
        self.assertGreaterEqual(dados["pages_saved"], 2)
        self.assertGreaterEqual(dados["assets_saved"], 3)

    def test_estado_permite_retomada(self) -> None:
        state = json.loads((self.out / "_crawl" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["pending"], [])
        self.assertGreaterEqual(len(state["seen"]), 5)

    def test_padrao_de_exclusao_ignora_urls(self) -> None:
        out = Path(self._out_dir.name) / "site_excluido"
        config = CrawlConfig(
            start_urls=[self.base_url],
            output_dir=out,
            use_sitemaps=False,
            delay=0.0,
            workers=2,
            timeout=10.0,
            retries=1,
            exclude_patterns=[r"/sobre/$"],
        )
        SiteCrawler(config).run()
        self.assertTrue((out / f"127.0.0.1_{self.port}" / "index.html").is_file())
        self.assertFalse((out / f"127.0.0.1_{self.port}" / "sobre").exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
