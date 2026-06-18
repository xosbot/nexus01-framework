from agents.base import BaseAgent, AgentStatus
from core.bus import Message
from tools.web_scraper import scrape_url, search_web
from core.memory import Memory
from core.llm import OllamaClient

class OSINTAgent(BaseAgent):
    def __init__(self, llm: OllamaClient, memory: Memory):
        super().__init__("osint", llm, memory)
        self.tools = {
            "web_search": search_web,
            "scrape_url": scrape_url,
        }

    async def on_message(self, message: Message) -> dict:
        task = message.payload.get("task", "")
        query = message.payload.get("query", task)

        self.memory.save_conversation(self.name, "user", task)

        search_results = await self.act("web_search", query=query)

        scraped_content = []
        if search_results:
            for result in search_results[:3]:
                url = result.get("url", "")
                if url:
                    try:
                        content = await self.act("scrape_url", url=url)
                        scraped_content.append(content)
                    except Exception:
                        continue

        synthesis_prompt = f"""Analyze these search results about: {query}
        
Search results: {search_results}
Scraped content: {scraped_content}

Provide a structured intelligence report with:
1. Key findings
2. Sources used
3. Confidence level (0-1)
4. Recommended actions"""

        analysis = await self.think(synthesis_prompt)

        report = {
            "query": query,
            "sources": len(search_results or []),
            "analysis": analysis,
            "status": "complete"
        }

        self.memory.save_conversation(self.name, "assistant", analysis)
        self.memory.save_knowledge(f"osint_{query}", str(report), {"agent": self.name})

        return report
