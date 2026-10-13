# amatra-site — espelhamento do conteúdo do site da AMATRA 9

Crawler em Python para baixar **todo o conteúdo publicamente acessível** de
<https://www.amatra9.org.br/> (um site WordPress) com o objetivo de subsidiar o
**redesenho do site** com base no conteúdo atual.

O crawler gera um **espelho navegável offline**: além de gravar arquivos, ele
reescreve os links internos para que HTML e CSS apontem para os arquivos locais.

---

## Estrutura do projeto

```
amatra-site/
├── crawler.py                  # CLI (ponto de entrada)
├── requirements.txt
├── amatra_crawler/
│   ├── __init__.py
│   ├── config.py               # CrawlConfig (parâmetros)
│   ├── urls.py                 # normalização de URL e URL -> caminho local
│   ├── parser.py               # extração/reescrita de links (HTML e CSS)
│   ├── fetcher.py              # HTTP com retries, rate limit e robots.txt
│   ├── storage.py              # gravação atômica + manifesto
│   └── crawler.py              # motor: fila, workers, estado e resumo
├── tests/
│   ├── test_urls.py
│   ├── test_parser.py
│   └── test_crawler.py         # integração com servidor HTTP local
└── site/                       # saída do crawl (não versionada)
```

## Requisitos

- Python 3.10+
- Dependências: `requests`, `beautifulsoup4` (ver `requirements.txt`)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso

```bash
# Espelha o site inteiro (HTML + assets) em ./site
python crawler.py --output site

# Apenas HTML, limite de 300 páginas, 4 workers
python crawler.py --no-assets --max-pages 300 --workers 4

# Profundidade máxima de 2 níveis a partir da home, hosts extras permitidos
python crawler.py --max-depth 2 --extra-host cdn.amatra9.org.br

# Ignora estado anterior e rebaixa tudo
python crawler.py --overwrite
```

### Principais opções

| Opção | Padrão | Descrição |
| --- | --- | --- |
| `--start-url URL` | `https://www.amatra9.org.br/` | URL semente (pode repetir) |
| `--output DIR` | `site` | Diretório do espelho |
| `--workers N` | `8` | Threads simultâneas |
| `--delay S` | `0.2` | Intervalo mínimo entre requisições |
| `--timeout S` | `30` | Timeout por requisição |
| `--retries N` | `3` | Tentativas adicionais com backoff |
| `--max-pages N` | ilimitado | Limite de páginas HTML |
| `--max-depth N` | ilimitado | Profundidade máxima de páginas |
| `--extra-host HOST` | — | Host interno adicional (CDN etc.) |
| `--no-assets` | — | Não baixar imagens/CSS/JS/PDF |
| `--no-sitemaps` | — | Não usar sitemaps XML para descobrir URLs |
| `--no-robots` | — | Ignorar `robots.txt` |
| `--overwrite` | — | Ignorar estado anterior e rebaixar |
| `-v` | — | Log em nível DEBUG |

## Saída gerada

```
site/
├── www.amatra9.org.br/
│   ├── index.html                       # home (links reescritos)
│   ├── noticias/index.html
│   └── wp-content/uploads/2024/foto.jpg
└── _crawl/
    ├── manifest.jsonl                   # 1 registro JSON por URL processada
    ├── summary.json                     # estatísticas da execução
    └── state.json                       # estado para retomada
```

O caminho local de cada URL é **determinístico** (`urls.local_path_for`):
o host vira o primeiro diretório, URLs com `/` final ou sem extensão viram
`index.html` e *query strings* geram o sufixo `__q<sha1>` para evitar colisões.

## Como funciona

1. **Descoberta**: as URLs sementes são enfileiradas e, opcionalmente,
   `sitemap_index.xml` / `sitemap.xml` são percorridos (seguindo índices
   aninhados) para obter todas as páginas publicadas.
2. **Fila + workers**: um dispatcher alimenta um `ThreadPoolExecutor`;
   cada página é baixada, tem os links extraídos e reescreve-os para caminhos
   relativos locais. Páginas e recursos descobertos entram na fila.
3. **Assets**: imagens, CSS, JS, PDFs e mídias são baixados; em arquivos CSS,
   as referências `url(...)` e `@import` são reescritas e seus destinos também
   são enfileirados.
4. **Cortesia com o servidor**: `robots.txt` é respeitado, há *rate limiting*
   global, *retries* com backoff exponencial e um User-Agent identificável.
5. **Resiliência**: o estado (URLs vistas + fila pendente) é persistido em
   `_crawl/state.json`, permitindo **retomar** um crawl interrompido —
   recursos já baixados não são repetidos.

## Testes

```bash
python -m unittest discover -s tests -t . -v
```

A suíte cobre normalização de URLs, mapeamento de caminhos, extração/reescrita
de links (incluindo `srcset` e CSS) e um teste de integração que sobe um
servidor HTTP local e valida o espelho ponta a ponta, sem depender de rede.

## Boas práticas e limites

- O crawl é **somente leitura** (métodos GET) e respeita as diretivas do
  `robots.txt` do site.
- Recomenda-se rodar com `--delay 0.2` ou maior para não impactar o servidor
  de produção.
- O conteúdo baixado é material de referência para o redesenho; verifique
  licenças/uso de imagens e textos antes de redistribuí-los.
