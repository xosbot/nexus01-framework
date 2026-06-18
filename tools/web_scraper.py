import httpx
from bs4 import BeautifulSoup

async def scrape_url(url: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.string.strip() if soup.title else ""
            text = soup.get_text(separator="\n", strip=True)[:5000]
            links = [a.get("href", "") for a in soup.find_all("a", href=True)[:50]]
            return {"title": title, "text": text, "links": links, "url": url, "status": "success"}
        except Exception as e:
            return {"error": str(e), "url": url, "status": "failed"}

async def search_web(query: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": "Mozilla/5.0"}
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for r in soup.select(".result")[:10]:
                title_el = r.select_one(".result__title")
                snippet_el = r.select_one(".result__snippet")
                link_el = r.select_one(".result__url")
                if title_el:
                    results.append({
                        "title": title_el.get_text(strip=True),
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                        "url": link_el.get_text(strip=True) if link_el else "",
                    })
            return results
    except Exception as e:
        return [{"error": str(e)}]
