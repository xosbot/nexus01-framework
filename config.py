import os
from pathlib import Path
from dataclasses import dataclass, field

@dataclass
class Config:
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1"))
    telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_TOKEN", ""))
    database_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", "./data/nexus.db"))
    chroma_path: str = field(default_factory=lambda: os.getenv("CHROMA_PATH", "./data/chromadb"))
    cold_mode_enabled: bool = field(default_factory=lambda: os.getenv("COLD_MODE_ENABLED", "true").lower() == "true")

    @classmethod
    def load(cls, path: str = "config.yaml") -> "Config":
        config = cls()
        config_file = Path(path)
        if config_file.exists():
            import yaml
            with open(config_file) as f:
                data = yaml.safe_load(f) or {}
            for k, v in data.items():
                if hasattr(config, k):
                    setattr(config, k, v)
        return config

config = Config.load()
