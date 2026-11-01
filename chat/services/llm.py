import logging
from typing import Optional
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

class LLMServiceError(Exception):
    """Exception raised when local LLM generation encounters an error."""
    pass


def generate(prompt: str, temperature: float = 0.2, timeout: Optional[int] = None) -> str:
    """
    Sends a prompt to the locally running Ollama instance via its HTTP API.
    Does NOT use any cloud APIs or external LLM services.
    
    Endpoint: POST {OLLAMA_BASE_URL}/api/generate
    Payload: {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}

    CPU-only local inference (no GPU) with a larger context (e.g. the wider
    top_k used for "summarize this document"-style questions) can legitimately
    take longer than a short default timeout. The timeout is configurable via
    OLLAMA_TIMEOUT in .env (default 300s) rather than a hardcoded 120s, and
    "keep_alive" is set so Ollama keeps the model resident in memory between
    requests instead of reloading it (which is itself a common source of
    slow/first-request timeouts).
    """
    base_url = getattr(settings, 'OLLAMA_BASE_URL', 'http://localhost:11434').rstrip('/')
    model_name = getattr(settings, 'OLLAMA_MODEL', 'mistral')
    if timeout is None:
        timeout = getattr(settings, 'OLLAMA_TIMEOUT', 300)
    url = f"{base_url}/api/generate"

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "temperature": temperature,
        }
    }

    logger.info(f"Dispatching generation request to Ollama at {url} (model: '{model_name}')...")

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=timeout
        )
    except requests.exceptions.ConnectionError as e:
        msg = f"Unable to connect to Ollama at '{base_url}'. Please ensure Ollama is running locally ('ollama serve')."
        logger.error(f"Ollama connection error: {e}")
        raise LLMServiceError(msg) from e
    except requests.exceptions.Timeout as e:
        msg = f"Ollama request timed out after {timeout} seconds. The local model may be overloaded."
        logger.error(f"Ollama timeout: {e}")
        raise LLMServiceError(msg) from e
    except requests.exceptions.RequestException as e:
        msg = f"Network error communicating with Ollama: {str(e)}"
        logger.error(f"Ollama request error: {e}")
        raise LLMServiceError(msg) from e

    # Handle HTTP status codes
    if response.status_code == 404:
        msg = f"Ollama model '{model_name}' not found. Please run 'ollama pull {model_name}' in your terminal."
        logger.error(msg)
        raise LLMServiceError(msg)
    elif response.status_code != 200:
        msg = f"Ollama returned HTTP {response.status_code}: {response.text}"
        logger.error(msg)
        raise LLMServiceError(f"Local LLM returned an error (HTTP {response.status_code}).")

    # Parse JSON response
    try:
        data = response.json()
    except ValueError as e:
        logger.error(f"Failed to parse Ollama JSON response: {response.text}")
        raise LLMServiceError("Malformed response received from local LLM.") from e

    answer = data.get("response", "").strip()
    if not answer:
        logger.warning(f"Ollama returned an empty response for model '{model_name}'.")
        raise LLMServiceError("Local LLM returned an empty response.")

    logger.info("Successfully received answer from local Ollama.")
    return answer
