"""
Ollama LLM and Embedding Service
"""
import httpx
from typing import Optional, List, Dict, Any, AsyncGenerator
import json

from app.core.config import settings


class OllamaService:
    """Service for interacting with Ollama API"""

    def __init__(self):
        self.base_url = settings.ollama_host
        self.default_model = settings.ollama_model
        self.embed_model = settings.ollama_embed_model

    async def check_connection(self) -> Dict[str, Any]:
        """Check Ollama connection status"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/api/tags", timeout=5.0)
                if response.status_code == 200:
                    return {"connected": True, "models": response.json().get("models", [])}
                return {"connected": False, "error": f"Status code: {response.status_code}"}
        except Exception as e:
            return {"connected": False, "error": str(e)}

    async def list_models(self) -> List[Dict[str, Any]]:
        """List available models"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/api/tags", timeout=10.0)
                if response.status_code == 200:
                    return response.json().get("models", [])
                return []
        except Exception:
            return []

    async def get_embedding(self, text: str, model: Optional[str] = None) -> List[float]:
        """Get embedding for a single text"""
        model = model or self.embed_model

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/embeddings",
                json={"model": model, "prompt": text},
                timeout=30.0
            )

            if response.status_code == 200:
                return response.json().get("embedding", [])
            raise Exception(f"Embedding failed: {response.text}")

    async def get_embeddings_batch(
        self,
        texts: List[str],
        model: Optional[str] = None,
        batch_size: int = 32
    ) -> List[List[float]]:
        """Get embeddings for multiple texts in batches"""
        model = model or self.embed_model
        embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = []

            for text in batch:
                embedding = await self.get_embedding(text, model)
                batch_embeddings.append(embedding)

            embeddings.extend(batch_embeddings)

        return embeddings

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        max_tokens: int = 4096,
        stream: bool = False
    ) -> str:
        """Generate text using Ollama"""
        model = model or self.default_model

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "num_predict": max_tokens
            }
        }

        if system:
            payload["system"] = system

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=300.0  # 5 minutes for long generations
            )

            if response.status_code == 200:
                return response.json().get("response", "")
            raise Exception(f"Generation failed: {response.text}")

    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        max_tokens: int = 4096
    ) -> AsyncGenerator[str, None]:
        """Generate text with streaming response"""
        model = model or self.default_model

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": top_k,
                "num_predict": max_tokens
            }
        }

        if system:
            payload["system"] = system

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=300.0
            ) as response:
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            if "response" in data:
                                yield data["response"]
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue


# Singleton instance
ollama_service = OllamaService()


def get_ollama() -> OllamaService:
    """Dependency to get Ollama service"""
    return ollama_service
