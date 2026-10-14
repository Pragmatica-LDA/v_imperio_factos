import pytest

from crawl import links


class S:
    def __init__(self, pk, base_url):
        self.pk, self.base_url = pk, base_url


JN, OBS = S(1, "https://www.jn.pt/"), S(2, "https://observador.pt/")
SITES = [JN, OBS]


@pytest.mark.parametrize("url,scope,platform", [
    ("https://www.jn.pt/pais/artigo/x/123", "internal", "site"),
    ("https://observador.pt/2026/10/13/x/", "media", "site"),
    ("https://www.instagram.com/p/ABC/", "external", "instagram"),
    ("https://m.facebook.com/pagina", "external", "facebook"),
    ("https://twitter.com/u/status/1", "external", "x"),
    ("https://youtu.be/xyz", "external", "youtube"),
    ("https://t.co/abc", "external", "encurtador"),
    ("https://www.parlamento.pt/doc.pdf", "external", "documento"),
])
def test_classify(url, scope, platform):
    info = links.classify(url, JN, SITES)
    assert (info["scope"], info["platform"]) == (scope, platform)


def test_normalize_strips_tracking_and_fragment():
    assert links.normalize("https://X.com/a?utm_source=f&id=3#top") == "https://x.com/a?id=3"


def test_iter_links_orders_embeds_by_block():
    content = {"body": [{"links": [{"url": "https://a.pt/1", "text": "a"}]}, {"links": []},
                        {"links": [{"url": "https://b.pt/2", "text": "b"}]}],
               "embeds": [{"url": "https://www.instagram.com/p/Z/", "block_index": 2}]}
    assert [u for _, u, _, _ in links.iter_links(content)] == [
        "https://a.pt/1", "https://www.instagram.com/p/Z/", "https://b.pt/2"]


@pytest.mark.django_db
def test_record_links_internal_target(seeded):
    from crawl.models import Article, ArticleLink, ArticleURL, Fetch, Version
    from sources.models import Site

    jn = Site.objects.get(slug="jn")
    other = Article.objects.create(site=jn, canonical_url="https://www.jn.pt/a/artigo/x/1")
    ArticleURL.objects.create(article=other, url="https://www.jn.pt/a/artigo/x/1")
    a = Article.objects.create(site=jn, canonical_url="https://www.jn.pt/a/artigo/y/2")
    f = Fetch.objects.create(article=a, url=a.canonical_url, reason="new", outcome="ok")
    v = Version.objects.create(article=a, number=1, fetch=f, content_hash="h", text="t", content={
        "body": [{"kind": "p", "text": "t", "links": [{"url": "https://www.jn.pt/a/artigo/x/1", "text": "antes"},
                                                       {"url": "mailto:a@b.pt", "text": "mail"},
                                                       {"url": "https://observador.pt/x/", "text": "obs"}]}],
        "embeds": [{"url": "https://www.instagram.com/p/Q/", "platform": "instagram", "block_index": 1}]})
    assert links.record(v) == 3
    assert links.record(v) == 3   # idempotente
    internal = ArticleLink.objects.get(version=v, scope="internal")
    assert internal.target_article == other
    assert ArticleLink.objects.get(version=v, scope="media").target_site.slug == "observador"
    assert ArticleLink.objects.get(version=v, kind="embed").platform == "instagram"
