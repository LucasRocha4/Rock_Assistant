"""Integração real de pesquisa na web utilizando DuckDuckGo Search (DDGS) e APIs complementares."""

import re
import concurrent.futures
import threading
import time
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import requests

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from rock_assistant import config
except ImportError:
    config = None

# Suprime avisos de depreciação/renomeação de pacote duckduckgo_search
warnings.filterwarnings("ignore", message=".*duckduckgo_search.*")
warnings.filterwarnings("ignore", message=".*renamed to.*")
warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from duckduckgo_search import DDGS
except ImportError:
    try:
        from ddgs import DDGS
    except ImportError:
        DDGS = None


@dataclass(frozen=True)
class SearchRequest:
    """Parâmetros normalizados de uma solicitação de busca."""

    query: str
    mode: str = "general"
    max_results: int = 5
    enrich: bool = False


def classify_search_mode(query: str) -> str:
    """Classifica marcadores explícitos sem tentar adivinhar demais."""
    normalized = (query or "").strip().lower()
    if re.search(r"\b(busca|pesquisa)\s+em\s+massa\b|\bvarrer\s+(vários|varios|muitos)\s+sites?\b", normalized):
        return "bulk"
    if re.search(r"\b(alvo\s+específico|alvo\s+especifico|site\s+específico|site\s+especifico)\b", normalized):
        return "target"
    return "general"


def _normalise_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Converte respostas de fontes diferentes para o contrato comum."""
    normalized: List[Dict[str, str]] = []
    seen = set()
    for item in items:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or item.get("href") or "").strip()
        snippet = str(item.get("snippet") or item.get("body") or "").strip()
        key = url.rstrip("/").lower()
        if title and url and key not in seen:
            normalized.append({"title": title, "url": url, "snippet": snippet})
            seen.add(key)
    return normalized


def _ddgs_search(query: str, max_results: int) -> List[Dict[str, str]]:
    if DDGS is None:
        return []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with DDGS() as ddgs:
                raw_items = list(ddgs.text(query, max_results=max_results))
        return _normalise_items(raw_items)
    except Exception:
        return []


def _fetch_html(url: str, timeout: float) -> Dict[str, Any]:
    """Baixa e extrai conteúdo estático; não executa JavaScript."""
    if BeautifulSoup is None:
        return {"url": url, "error": "beautifulsoup4 não está instalado"}
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "RockAssistant/1.0"},
            timeout=timeout,
        )
        if response.status_code != 200:
            return {"url": url, "status_code": response.status_code}
        soup = BeautifulSoup(response.text, "html.parser")
        table_count = len(soup.find_all("table"))
        for element in soup(["script", "style", "noscript"]):
            element.decompose()
        text = " ".join(soup.get_text(" ").split())
        page: Dict[str, Any] = {"url": url, "status_code": 200, "text": text[:12000]}
        if table_count and pd is not None:
            try:
                tables = pd.read_html(response.text)
                page["tables"] = [table.head(50).to_dict(orient="records") for table in tables]
            except (ValueError, ImportError):
                page["tables"] = []
        return page
    except requests.RequestException as exc:
        return {"url": url, "error": str(exc)}


def _query_variants(query: str) -> List[str]:
    stopwords = {
        "a", "à", "ao", "as", "com", "como", "da", "das", "de", "do", "dos",
        "e", "em", "foi", "há", "na", "nas", "no", "nos", "o", "os",
        "para", "por", "que", "qual", "quando", "quem", "se", "sobre", "um", "uma",
    }
    simplified = re.sub(
        r"\b(?:e|sobre|da|do|de|em|para|com|por|noticias|notícias|carreira)\b",
        " ",
        query,
        flags=re.IGNORECASE,
    )
    simplified = " ".join(simplified.split()).strip()
    focused_terms = [
        word for word in re.findall(r"[\wÀ-ÿ]+", query.lower())
        if len(word) > 2 and word not in stopwords
    ]
    focused = " ".join(dict.fromkeys(focused_terms))
    variants = [query]
    for candidate in (simplified, focused):
        if candidate and candidate.lower() not in {item.lower() for item in variants}:
            variants.append(candidate)
    return variants


def _relevance_score(query: str, item: Dict[str, str]) -> int:
    """Pontua cobertura lexical do resultado sem fingir compreensão semântica."""
    stopwords = {
        "a", "à", "ao", "as", "com", "como", "da", "das", "de", "do", "dos", "e",
        "em", "foi", "há", "na", "nas", "no", "nos", "o", "os", "para", "por", "que",
        "qual", "quando", "quem", "se", "sobre", "um", "uma",
    }
    terms = {
        word for word in re.findall(r"[\wÀ-ÿ]+", query.lower())
        if len(word) > 2 and word not in stopwords
    }
    haystack = f"{item.get('title', '')} {item.get('snippet', '')}".lower()
    return sum(1 for term in terms if term in haystack)


def _relevant_results(query: str, items: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized = _normalise_items(items)
    terms = {
        word for word in re.findall(r"[\wÀ-ÿ]+", query.lower())
        if len(word) > 2 and word not in {"a", "com", "da", "de", "do", "e", "em", "foi", "na", "no", "o", "os", "para", "por", "que", "qual", "quando", "quem", "sobre", "um", "uma"}
    }
    if len(terms) < 2:
        return normalized
    minimum = 1 if len(terms) == 1 else 2
    ranked = [(item, _relevance_score(query, item)) for item in normalized]
    return [item for item, score in sorted(ranked, key=lambda pair: pair[1], reverse=True) if score >= minimum]


def _worker_search(query: str, max_results: int) -> List[Dict[str, str]]:
    """Worker independente; cada tarefa tem uma fonte/variante limitada."""
    return _relevant_results(query, _ddgs_search(query, max_results))


def search_web_structured(
    query: str,
    *,
    mode: Optional[str] = None,
    max_results: int = 5,
    enrich: Optional[bool] = None,
) -> Dict[str, Any]:
    """Executa a busca com deadline e concorrência controlados.

    O retorno inclui ``results`` e metadados de operação para diagnóstico.
    ``bulk`` fica explicitamente reservado para o adaptador Scrapy futuro.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return {"results": [], "mode": mode or "general", "status": "empty"}

    search_mode = mode or classify_search_mode(cleaned_query)
    initial_timeout = float(getattr(config, "SEARCH_INITIAL_TIMEOUT", 7)) if config else 7.0
    deadline_seconds = float(getattr(config, "SEARCH_DEADLINE", 200)) if config else 200.0
    scale_interval = float(getattr(config, "SEARCH_SCALE_INTERVAL", 15)) if config else 15.0
    max_workers = int(getattr(config, "SEARCH_MAX_WORKERS", 20)) if config else 20
    initial_workers = int(getattr(config, "SEARCH_TARGET_INITIAL_WORKERS", 5)) if config else 5
    target_workers = max(1, min(initial_workers, max_workers))
    started = time.monotonic()
    results: List[Dict[str, str]] = []
    attempts = 0
    initial_status = "empty"

    # DDGS é bloqueante: isolamos a primeira tentativa para honrar os 7 segundos.
    initial_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = initial_pool.submit(_ddgs_search, cleaned_query, max_results)
    try:
        results = _relevant_results(cleaned_query, future.result(timeout=min(initial_timeout, deadline_seconds)))
        initial_status = "success" if results else "empty"
    except concurrent.futures.TimeoutError:
        initial_status = "timeout"
        future.cancel()
    finally:
        initial_pool.shutdown(wait=False, cancel_futures=True)

    if search_mode == "bulk":
        try:
            from .bulk_search import crawl_urls

            bulk_results = crawl_urls(
                [item["url"] for item in results],
                max_workers=int(getattr(config, "SEARCH_BULK_WORKERS", 10)) if config else 10,
                deadline=deadline_seconds,
            )
            return {
                "results": _normalise_items(bulk_results)[:max_results],
                "mode": "bulk",
                "status": "success" if bulk_results else initial_status,
                "workers": int(getattr(config, "SEARCH_BULK_WORKERS", 10)) if config else 10,
                "attempts": 1,
            }
        except RuntimeError as exc:
            return {"results": results[:max_results], "mode": "bulk", "status": "unavailable", "message": str(exc)}

    if results:
        return {"results": results[:max_results], "mode": search_mode, "status": initial_status, "workers": 1, "attempts": 1}

    variants = _query_variants(cleaned_query)
    deadline = started + deadline_seconds
    next_scale = started + scale_interval
    workers = target_workers
    lock = threading.Lock()
    pending_queries = iter(variants * max(1, max_workers))

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    active: Dict[concurrent.futures.Future[List[Dict[str, str]]], int] = {}
    try:
        while time.monotonic() < deadline and not results:
            while len(active) < workers:
                try:
                    variant = next(pending_queries)
                except StopIteration:
                    pending_queries = iter(variants * max(1, max_workers))
                    variant = next(pending_queries)
                active[pool.submit(_worker_search, variant, max_results)] = attempts
                attempts += 1

            remaining = max(0.01, min(deadline - time.monotonic(), next_scale - time.monotonic()))
            done, _ = concurrent.futures.wait(active, timeout=remaining, return_when=concurrent.futures.FIRST_COMPLETED)
            for completed in done:
                active.pop(completed, None)
                try:
                    candidate = completed.result()
                except Exception:
                    candidate = []
                if candidate:
                    results = _relevant_results(cleaned_query, candidate)
                    break

            if time.monotonic() >= next_scale:
                workers = min(max_workers, workers * 2 if search_mode == "target" else max(workers, 5) * 2)
                next_scale += scale_interval
            elif done and not results:
                time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    finally:
        for future in active:
            future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)

    output: Dict[str, Any] = {
        "results": results[:max_results],
        "mode": search_mode,
        "status": "success" if results else "timeout",
        "workers": workers,
        "attempts": attempts,
        "elapsed": round(time.monotonic() - started, 3),
    }
    if enrich and results:
        http_timeout = float(getattr(config, "SEARCH_HTTP_TIMEOUT", 8)) if config else 8.0
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(5, len(results))) as pool:
            output["pages"] = list(pool.map(lambda item: _fetch_html(item["url"], http_timeout), results))
    return output



def search_web_raw(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Executa a busca na web utilizando DuckDuckGo (DDGS) com estratégias resilientes de fallback.

    Retorna uma lista de dicionários contendo 'title', 'url' e 'snippet'.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return []

    results: List[Dict[str, str]] = []

    def add_results(items: List[Dict[str, str]]) -> None:
        """Normaliza e deduplica respostas de fontes diferentes."""
        seen = {item.get("url", "").rstrip("/").lower() for item in results}
        for item in items:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            snippet = (item.get("snippet") or "").strip()
            normalized_url = url.rstrip("/").lower()
            if title and url and normalized_url not in seen:
                results.append({"title": title, "url": url, "snippet": snippet})
                seen.add(normalized_url)

    # 1. Tentativa via DDGS text search
    if DDGS is not None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with DDGS() as ddgs:
                    raw_items = list(ddgs.text(cleaned_query, max_results=max_results))
                    if raw_items:
                        add_results([{
                                "title": item.get("title", "Sem título").strip(),
                                "url": item.get("href", item.get("url", "")).strip(),
                                "snippet": item.get("body", item.get("snippet", "")).strip(),
                            } for item in raw_items])
                        return results
        except Exception:
            pass

    # 2. Refinamento de termos para queries descritivas
    simplified = re.sub(
        r"\b(?:e|\d+\s+fatos\s+marcantes|fatos\s+marcantes|de\s+sua|sobre|da|do|de|em|para|com|por|noticias|notícias|carreira)\b",
        " ",
        cleaned_query,
        flags=re.IGNORECASE,
    )
    simplified = " ".join(simplified.split()).strip()

    if DDGS is not None and simplified and simplified.lower() != cleaned_query.lower():
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                with DDGS() as ddgs:
                    raw_items = list(ddgs.text(simplified, max_results=max_results))
                    if raw_items:
                        add_results([{
                                "title": item.get("title", "Sem título").strip(),
                                "url": item.get("href", item.get("url", "")).strip(),
                                "snippet": item.get("body", item.get("snippet", "")).strip(),
                            } for item in raw_items])
                        return results
        except Exception:
            pass

    # 3. Fallback via DuckDuckGo Instant Answer / Topics API
    for q_term in [cleaned_query, simplified]:
        if not q_term:
            continue
        try:
            resp = requests.get(
                "https://api.duckduckgo.com/",
                params={"q": q_term, "format": "json", "no_html": 1},
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                abstract = data.get("AbstractText") or data.get("Abstract")
                heading = data.get("Heading")
                url = data.get("AbstractURL")
                if abstract and heading:
                    results.append({
                        "title": heading,
                        "url": url or "https://duckduckgo.com",
                        "snippet": abstract,
                    })

                for topic in data.get("RelatedTopics", []):
                    if len(results) >= max_results:
                        break
                    if isinstance(topic, dict) and "Text" in topic:
                        results.append({
                            "title": topic.get("Text", "")[:60] + "...",
                            "url": topic.get("FirstURL", "https://duckduckgo.com"),
                            "snippet": topic.get("Text", ""),
                        })

                if results:
                    return results
        except Exception:
            pass

    # 4. Fallback via Wikipedia API (para entidades/biografias)
    for q_term in [simplified, cleaned_query]:
        if not q_term:
            continue
        try:
            wiki_url = f"https://pt.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(q_term)}"
            resp = requests.get(wiki_url, headers={"User-Agent": "RockAssistant/1.0"}, timeout=5)
            if resp.status_code == 200:
                wiki_data = resp.json()
                extract = wiki_data.get("extract")
                title = wiki_data.get("title")
                page_url = wiki_data.get("content_urls", {}).get("desktop", {}).get("page")
                if extract:
                    results.append({
                        "title": title or q_term,
                        "url": page_url or "https://pt.wikipedia.org",
                        "snippet": extract,
                    })
                    return results
        except Exception:
            pass

    return results


def search_web(
    query: str,
    max_results: int = 5,
    mode: Optional[str] = None,
    enrich: Optional[bool] = None,
) -> str:
    """Realiza a busca na web, extrai os principais resultados e retorna uma síntese formatada em texto.

    Args:
        query: Termo de pesquisa na web.
        max_results: Número máximo de resultados (padrão: 5).

    Returns:
        Síntese textual formatada com título, link e resumo dos resultados encontrados.
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return "Nenhum termo de busca fornecido."

    try:
        operation = search_web_structured(
            cleaned_query,
            mode=mode,
            max_results=max_results,
            enrich=enrich if enrich is not None else bool(getattr(config, "SEARCH_ENRICH_RESULTS", False)),
        )
        results = operation.get("results", [])
        if not results:
            return f"Nenhum resultado encontrado para a busca: '{cleaned_query}'."

        lines = [
            f"🔍 Resultados da busca na web para: '{cleaned_query}'\n",
            "=" * 60,
        ]

        if operation.get("status") == "timeout":
            lines.append("⚠️ A busca atingiu o limite de tempo; exibindo os resultados encontrados.")
        if operation.get("mode") == "bulk":
            lines.append("ℹ️ Busca em massa requer o crawler Scrapy e ainda não está habilitada.")

        for i, item in enumerate(results, 1):
            title = item.get("title", "Sem título")
            url = item.get("url", "Sem link")
            snippet = item.get("snippet", "Sem descrição")

            lines.append(f"\n[{i}] {title}")
            lines.append(f"    🔗 Link: {url}")
            lines.append(f"    📝 Resumo: {snippet}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    except Exception as exc:
        return f"Erro ao realizar pesquisa na web para '{cleaned_query}': {exc}"


class WebSearchTool:
    """Wrapper orientado a objetos para buscas na web."""

    def __init__(self) -> None:
        self.name = "web_search"

    def search(self, query: str, max_results: int = 5, mode: Optional[str] = None) -> str:
        """Realiza a busca e retorna a síntese formatada em texto."""
        return search_web(query=query, max_results=max_results, mode=mode)

    def search_structured(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """Realiza a busca e retorna a lista estruturada de resultados."""
        return search_web_raw(query=query, max_results=max_results)



