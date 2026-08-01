import os
from abc import ABC, abstractmethod
from openai import AsyncAzureOpenAI
from core.db import DuckDBWorldModelStore, ChromaVectorStore

class BaseAgent(ABC):
    """
    Agents have read-only access to the World Model.
    They observe the graph and vector stores to form context,
    then take actions or generate insights.
    """
    def __init__(self, db_store: DuckDBWorldModelStore, vector_store: ChromaVectorStore):
        self.db = db_store
        self.vector_store = vector_store
        
        api_key = os.environ.get("AZURE_AI_API_KEY")
        endpoint = os.environ.get("AZURE_AI_ENDPOINT")
        self.deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        api_version = os.environ.get("AZURE_AI_API_VERSION", "2024-12-01-preview")
        
        if not all([api_key, endpoint, self.deployment]):
            print("[Warning] Azure OpenAI credentials missing. Agent LLM capabilities disabled.")
            self.llm = None
        else:
            self.llm = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=api_version
            )

    @abstractmethod
    async def run(self, interval_seconds: int = 3600):
        """Execute the agent's primary loop or trigger."""
        pass
