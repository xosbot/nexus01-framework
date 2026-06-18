import statistics
from agents.base import BaseAgent, AgentStatus
from core.bus import Message
from core.memory import Memory
from core.llm import OllamaClient

class AnalystAgent(BaseAgent):
    def __init__(self, llm: OllamaClient, memory: Memory):
        super().__init__("analyst", llm, memory)
        self.tools = {
            "analyze_data": self._analyze_data,
            "detect_anomaly": self._detect_anomaly,
            "generate_report": self._generate_report,
        }

    async def on_message(self, message: Message) -> dict:
        data = message.payload.get("data", {})
        query = message.payload.get("query", "analyze")

        self.memory.save_conversation(self.name, "user", str(data))

        analysis_prompt = f"""Analyze this data and provide insights:
Data: {data}

Provide:
1. Pattern analysis
2. Anomaly detection
3. Key insights
4. Recommended actions"""

        analysis = await self.think(analysis_prompt)

        anomalies = self._detect_anomaly(data) if isinstance(data, dict) else {"anomalies": []}

        report = {
            "analysis": analysis,
            "anomalies": anomalies,
            "status": "complete"
        }

        self.memory.save_conversation(self.name, "assistant", analysis)
        self.memory.save_knowledge(f"analysis_{query}", str(report), {"agent": self.name})

        return report

    def _analyze_data(self, data: dict | list) -> dict:
        if isinstance(data, list) and all(isinstance(x, (int, float)) for x in data):
            return {
                "mean": statistics.mean(data),
                "stdev": statistics.stdev(data) if len(data) > 1 else 0,
                "count": len(data),
            }
        return {"type": type(data).__name__, "keys": list(data.keys()) if isinstance(data, dict) else None}

    def _detect_anomaly(self, data: dict | list, threshold: float = 2.0) -> dict:
        if isinstance(data, list) and len(data) > 2 and all(isinstance(x, (int, float)) for x in data):
            mean = statistics.mean(data)
            stdev = statistics.stdev(data) or 1
            anomalies = [i for i, v in enumerate(data) if abs((v - mean) / stdev) > threshold]
            return {"anomalies": anomalies, "count": len(anomalies)}
        return {"anomalies": [], "reason": "insufficient data"}

    async def _generate_report(self, title: str, content: str) -> dict:
        report_prompt = f"Generate a professional intelligence report:\nTitle: {title}\nContent: {content}"
        report = await self.think(report_prompt)
        return {"title": title, "report": report}
