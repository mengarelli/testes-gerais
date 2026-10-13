"""Testes de extração e reescrita de links (``amatra_crawler.parser``)."""

from __future__ import annotations

import unittest

from amatra_crawler.parser import (
    classify_link,
    ensure_utf8_charset,
    extract_links,
    parse_html,
    rewrite_css,
    rewrite_link,
)

HOSTS = {"www.amatra9.org.br"}
BASE = "https://www.amatra9.org.br/"

HTML = """<!DOCTYPE html>
<html lang="pt-br">
<head>
  <meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">
  <link rel="stylesheet" href="/wp-content/themes/x/style.css">
  <script src="https://www.amatra9.org.br/js/app.js"></script>
</head>
<body>
  <a href="/noticias/">Notícias</a>
  <a href="https://exemplo.com/ext">Externo</a>
  <a href="mailto:contato@amatra9.org.br">E-mail</a>
  <img src="/wp-content/uploads/2024/foto.jpg"
       srcset="/wp-content/uploads/2024/foto-300.jpg 300w,
               /wp-content/uploads/2024/foto-600.jpg 600w">
  <a href="/wp-content/uploads/2024/edital.pdf">Edital</a>
</body>
</html>
"""


class ExtractLinksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.soup, self.links = extract_links(HTML, BASE)

    def test_encontra_todos_os_links_relevantes(self) -> None:
        urls = {url for link in self.links for url in link.urls}
        self.assertIn("https://www.amatra9.org.br/noticias/", urls)
        self.assertIn("https://www.amatra9.org.br/wp-content/themes/x/style.css", urls)
        self.assertIn("https://www.amatra9.org.br/js/app.js", urls)
        self.assertIn("https://www.amatra9.org.br/wp-content/uploads/2024/foto.jpg", urls)
        self.assertIn("https://www.amatra9.org.br/wp-content/uploads/2024/foto-600.jpg", urls)

    def test_ignora_esquemas_nao_http(self) -> None:
        urls = {url for link in self.links for url in link.urls}
        self.assertNotIn("mailto:contato@amatra9.org.br", urls)

    def test_classificacao(self) -> None:
        self.assertEqual(classify_link(BASE + "noticias/", HOSTS), "page")
        self.assertEqual(
            classify_link(BASE + "wp-content/uploads/2024/edital.pdf", HOSTS), "asset"
        )
        self.assertIsNone(classify_link("https://exemplo.com/ext", HOSTS))


class RewriteLinkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.page_rel = "www.amatra9.org.br/index.html"

    def test_reescreve_link_interno_e_preserva_externo(self) -> None:
        soup, links = extract_links(HTML, BASE)
        for link in links:
            rewrite_link(link, BASE, self.page_rel, HOSTS)

        ancora_interna = soup.find("a", string="Notícias")
        ancora_externa = soup.find("a", string="Externo")
        self.assertEqual(ancora_interna["href"], "noticias/index.html")
        self.assertEqual(ancora_externa["href"], "https://exemplo.com/ext")

    def test_reescreve_srcset_preservando_descritores(self) -> None:
        soup, links = extract_links(HTML, BASE)
        for link in links:
            rewrite_link(link, BASE, self.page_rel, HOSTS)

        imagem = soup.find("img")
        self.assertEqual(imagem["src"], "wp-content/uploads/2024/foto.jpg")
        self.assertEqual(
            imagem["srcset"],
            "wp-content/uploads/2024/foto-300.jpg 300w, "
            "wp-content/uploads/2024/foto-600.jpg 600w",
        )

    def test_reescrita_e_idempotente(self) -> None:
        soup, links = extract_links(HTML, BASE)
        for link in links:
            rewrite_link(link, BASE, self.page_rel, HOSTS)
        primeira = str(soup)
        for link in links:
            rewrite_link(link, BASE, self.page_rel, HOSTS)
        self.assertEqual(primeira, str(soup))

    def test_sem_assets_nao_reescreve_recursos(self) -> None:
        soup, links = extract_links(HTML, BASE)
        for link in links:
            rewrite_link(link, BASE, self.page_rel, HOSTS, include_assets=False)

        self.assertEqual(
            soup.find("img")["src"], "/wp-content/uploads/2024/foto.jpg"
        )
        self.assertEqual(soup.find("a", string="Notícias")["href"], "noticias/index.html")


class CharsetTests(unittest.TestCase):
    def test_ajusta_meta_charset_para_utf8(self) -> None:
        soup = parse_html(HTML)
        ensure_utf8_charset(soup)
        meta = soup.find("meta", attrs={"http-equiv": "Content-Type"})
        self.assertEqual(meta["content"], "text/html; charset=utf-8")

    def test_insere_meta_quando_ausente(self) -> None:
        soup = parse_html("<html><head><title>t</title></head><body></body></html>")
        ensure_utf8_charset(soup)
        self.assertEqual(soup.head.find("meta")["charset"], "utf-8")


class RewriteCssTests(unittest.TestCase):
    def test_reescreve_url_e_import(self) -> None:
        css = '@import url("base.css");\n.classe { background: url(../img/bg.png); }'
        css_rel = "www.amatra9.org.br/wp-content/themes/x/style.css"
        novo_css, descobertos = rewrite_css(css, BASE + "wp-content/themes/x/style.css", css_rel)

        self.assertIn('@import "base.css"', novo_css)
        self.assertIn("url(../img/bg.png)", novo_css)
        self.assertEqual(
            descobertos,
            {
                "https://www.amatra9.org.br/wp-content/themes/x/base.css",
                "https://www.amatra9.org.br/wp-content/themes/img/bg.png",
            },
        )

    def test_preserva_data_uri(self) -> None:
        css = ".x { background: url(data:image/png;base64,AAA); }"
        novo_css, descobertos = rewrite_css(css, BASE + "a.css", "h/a.css")
        self.assertEqual(novo_css, css)
        self.assertFalse(descobertos)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
