"""Adaptador opcional para varredura limitada com Scrapy."""

from typing import Any, Dict, Iterable, List


def crawl_urls(urls: Iterable[str], max_workers: int = 10, deadline: float = 200) -> List[Dict[str, Any]]:
    """Percorre URLs iniciais com Scrapy, retornando links e títulos encontrados.

    A função falha de forma explícita quando Scrapy não está instalado. O limite de
    concorrência é aplicado pelo próprio downloader do Scrapy; não há processos
    adicionais nem crawling sem limite.
    """
    try:
        import scrapy
        from scrapy.crawler import CrawlerProcess
        from scrapy.linkextractors import LinkExtractor
        from scrapy.spiders import CrawlSpider, Rule
    except ImportError as exc:
        raise RuntimeError("Scrapy não está instalado para buscas em massa.") from exc

    collected: List[Dict[str, Any]] = []
    start_urls = [url for url in urls if isinstance(url, str) and url.startswith(("http://", "https://"))]
    if not start_urls:
        return collected

    class LimitedSpider(CrawlSpider):
        name = "rock_bulk_search"
        custom_settings = {
            "CONCURRENT_REQUESTS": max(1, min(max_workers, 10)),
            "ROBOTSTXT_OBEY": True,
            "DOWNLOAD_TIMEOUT": min(float(deadline), 20),
            "CLOSESPIDER_TIMEOUT": float(deadline),
            "LOG_ENABLED": False,
        }
        rules = (Rule(LinkExtractor(deny_extensions=["pdf", "zip", "exe"]), follow=False, callback="parse_item"),)

        def parse_item(self, response: Any, **kwargs: Any) -> None:
            title = response.css("title::text").get(default="").strip()
            collected.append({"title": title or response.url, "url": response.url, "snippet": ""})

    LimitedSpider.start_urls = start_urls
    process = CrawlerProcess(settings=LimitedSpider.custom_settings)
    process.crawl(LimitedSpider)
    process.start(stop_after_crawl=True)
    return collected