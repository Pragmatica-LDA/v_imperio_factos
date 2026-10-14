"""Os 3 parsers através do adaptador, sobre as amostras reais (offline)."""

import pytest

from parsers import registry
from tests.conftest import fixture_text


@pytest.mark.parametrize("site,fixture,minimum", [
    ("observador", "observador_homepage.html", 100),
    ("jn", "jn_homrpage.html", 50),
    ("publico", "publico_homepage.html", 50),
])
def test_homepage(site, fixture, minimum):
    items = registry.discover(site, "homepage", fixture_text(fixture), "x")
    assert len(items) >= minimum
    assert all(i.url.startswith("http") for i in items)


def test_homepage_include_excluded_marks_reason():
    items = registry.discover("jn", "homepage", fixture_text("jn_homrpage.html"), "x", include_excluded=True)
    assert any(i.excluded_reason for i in items)


@pytest.mark.parametrize("site,fixture", [
    ("observador", "observador_sitemap_post-243.xml"),
    ("jn", "jn_sitemap_news.xml"),
    ("jn", "jn_sitemap_day_2026-10-13.xml"),
])
def test_sitemaps(site, fixture):
    items = registry.discover(site, "sitemap", fixture_text(fixture), "x")
    assert items


def test_feed_observador():
    assert registry.discover("observador", "feed", fixture_text("observador_feed.xml"), "x")


def test_jn_has_no_feed():
    with pytest.raises(registry.ParserNotAvailable):
        registry.discover("jn", "feed", "<rss/>", "x")


def test_observador_index_latest_page_per_type():
    urls = registry.sitemap_index("observador", fixture_text("observador_sitemap_index.xml"),
                                  {"post_types": ["post", "obs_opinion"], "latest_per_type": 1})
    assert len(urls) == 2
    assert any("posts-post-" in u for u in urls) and any("obs_opinion" in u for u in urls)


@pytest.mark.parametrize("site,fixture,url,oos", [
    ("observador", "observador_noticia.html", "https://observador.pt/x/", None),
    ("jn", "jn_noticias.html", "https://www.jn.pt/x", None),
    ("publico", "publico_noticia.html", "https://www.publico.pt/x", None),
    ("jn", "jn_article_18135966_premium.html", "https://www.jn.pt/x", "premium_sem_texto_integral"),
    ("publico", "publico_article_2190775_premium.html", "https://www.publico.pt/x", "premium_sem_texto_integral"),
])
def test_articles(site, fixture, url, oos):
    a = registry.article(site, fixture_text(fixture), url)
    assert a.title
    assert a.out_of_scope == oos
    if oos is None:
        assert a.body


def test_jn_inflated_wordcount_is_still_complete():
    """O WordCount do JN conta markup e embeds: um artigo free com corpo não pode sair incompleto."""
    a = registry.article("jn", fixture_text("jn_article_18136675_wordcount_inflado.html"), "https://www.jn.pt/x")
    assert a.access == "free" and a.body_complete is True and a.out_of_scope is None
    assert a.word_count > 200


def test_strip_html_in_text_fields():
    """O JSON-LD headline do Público traz <em>: o contrato exige texto simples em todos os sites."""
    from parsers.base import Article, Block, strip_html, clean_article

    assert strip_html("<em>Football Leaks</em>: PJ reconhece") == "Football Leaks: PJ reconhece"
    assert strip_html("Robô <em class='x'>Perseverance</em> &amp; <br/>Marte&nbsp;hoje") == "Robô Perseverance & Marte hoje"
    assert strip_html("se a < b e c > d") == "se a < b e c > d"
    a = clean_article(Article(title="<em>X</em> y", lead="<strong>L</strong>", tags=["<i>t</i>"],
                              body=[Block(kind="p", text="um <b>dois</b>")]))
    assert (a.title, a.lead, a.tags, a.body[0].text) == ("X y", "L", ["t"], "um dois")
