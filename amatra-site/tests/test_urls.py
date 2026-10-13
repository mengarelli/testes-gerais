"""Testes das funções utilitárias de URL (``amatra_crawler.urls``)."""

from __future__ import annotations

import unittest

from amatra_crawler.urls import (
    is_asset_url,
    is_internal_url,
    local_path_for,
    normalize_url,
    path_suffix,
    relative_link,
)


class NormalizeUrlTests(unittest.TestCase):
    def test_remove_fragmento(self) -> None:
        self.assertEqual(
            normalize_url("https://www.amatra9.org.br/#topo"),
            "https://www.amatra9.org.br/",
        )

    def test_normaliza_host_e_scheme(self) -> None:
        self.assertEqual(
            normalize_url("HTTPS://WWW.Amatra9.org.br/Noticias/"),
            "https://www.amatra9.org.br/Noticias/",
        )

    def test_remove_porta_padrao(self) -> None:
        self.assertEqual(
            normalize_url("https://www.amatra9.org.br:443/x"),
            "https://www.amatra9.org.br/x",
        )

    def test_preserva_query_string(self) -> None:
        self.assertEqual(
            normalize_url("https://www.amatra9.org.br/?s=edital#x"),
            "https://www.amatra9.org.br/?s=edital",
        )


class ClassificacaoTests(unittest.TestCase):
    HOSTS = {"www.amatra9.org.br"}

    def test_asset_por_extensao(self) -> None:
        self.assertTrue(is_asset_url("https://www.amatra9.org.br/wp-content/a.pdf"))
        self.assertTrue(is_asset_url("https://www.amatra9.org.br/img/logo.png"))
        self.assertFalse(is_asset_url("https://www.amatra9.org.br/noticias/"))

    def test_pagina_sem_extensao(self) -> None:
        self.assertFalse(is_asset_url("https://www.amatra9.org.br/sobre/"))
        self.assertEqual(path_suffix("https://www.amatra9.org.br/sobre/"), "")

    def test_internal_url(self) -> None:
        self.assertTrue(is_internal_url("https://www.amatra9.org.br/x", self.HOSTS))
        self.assertFalse(is_internal_url("https://exemplo.com/x", self.HOSTS))
        self.assertFalse(is_internal_url("mailto:a@b.com", self.HOSTS))


class LocalPathTests(unittest.TestCase):
    def test_raiz_vira_index(self) -> None:
        self.assertEqual(
            local_path_for("https://www.amatra9.org.br/"),
            "www.amatra9.org.br/index.html",
        )

    def test_diretorio_vira_index(self) -> None:
        self.assertEqual(
            local_path_for("https://www.amatra9.org.br/noticias/"),
            "www.amatra9.org.br/noticias/index.html",
        )

    def test_arquivo_preserva_extensao(self) -> None:
        self.assertEqual(
            local_path_for("https://www.amatra9.org.br/img/logo.png"),
            "www.amatra9.org.br/img/logo.png",
        )

    def test_porta_nao_padrao_no_host(self) -> None:
        self.assertEqual(
            local_path_for("http://127.0.0.1:8080/sobre/"),
            "127.0.0.1_8080/sobre/index.html",
        )

    def test_query_gera_sufixo_unico(self) -> None:
        um = local_path_for("https://www.amatra9.org.br/?s=edital")
        dois = local_path_for("https://www.amatra9.org.br/?s=nota")
        self.assertNotEqual(um, dois)
        self.assertTrue(um.endswith(".html"))

    def test_segmento_inseguro_sanitizado(self) -> None:
        self.assertNotIn("..", local_path_for("https://www.amatra9.org.br/a/../b"))


class RelativeLinkTests(unittest.TestCase):
    def test_arquivo_na_raiz(self) -> None:
        self.assertEqual(
            relative_link("www.amatra9.org.br/index.html", "www.amatra9.org.br/logo.png"),
            "logo.png",
        )

    def test_pagina_para_subdiretorio(self) -> None:
        self.assertEqual(
            relative_link(
                "www.amatra9.org.br/index.html",
                "www.amatra9.org.br/noticias/index.html",
            ),
            "noticias/index.html",
        )

    def test_subdiretorio_para_raiz(self) -> None:
        self.assertEqual(
            relative_link(
                "www.amatra9.org.br/noticias/index.html",
                "www.amatra9.org.br/index.html",
            ),
            "../index.html",
        )

    def test_entre_subdiretorios(self) -> None:
        self.assertEqual(
            relative_link(
                "www.amatra9.org.br/a/index.html",
                "www.amatra9.org.br/b/c/index.html",
            ),
            "../b/c/index.html",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
