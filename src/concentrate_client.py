"""HTTP client for Concentrate AI /v1/responses endpoint."""

import httpx


class ConcentrateClient:
    """Sync client for Concentrate AI's OpenAI-compatible /v1/responses API."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.concentrate.ai",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def create_response(
        self,
        model: str,
        input_text: str,
        extra: dict | None = None,
    ) -> dict:
        """
        POST to /v1/responses and return the raw JSON response.

        Args:
            model: Model identifier (e.g. openai/gpt-5.2, anthropic/claude-opus-4-6).
            input_text: User/assistant input text for the request.
            extra: Optional dict merged into the JSON body (e.g. max_tokens, temperature).

        Returns:
            Parsed JSON response as dict.

        Raises:
            httpx.HTTPStatusError: On non-2xx response (caller should handle and inspect
                response.status_code and response.text / .json()).
        """
        url = f"{self.base_url}/v1/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body: dict = {"model": model, "input": input_text}
        if extra:
            body = {**body, **extra}

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()
