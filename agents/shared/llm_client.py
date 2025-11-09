"""
Project Chimera - LLM Client Wrapper

OpenAI-compatible client for DeepSeek (and other providers).
Includes retry logic and error handling.
"""

import os
import time
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI, APIError, APITimeoutError, RateLimitError

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Wrapper for LLM API calls with retry logic and error handling.
    Compatible with OpenAI and DeepSeek APIs.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "deepseek-chat",
        max_retries: int = 3,
        timeout: int = 30
    ):
        """
        Initialize LLM client.

        Args:
            api_key: API key (defaults to DEEPSEEK_API_KEY env var)
            base_url: Base URL (defaults to DEEPSEEK_BASE_URL env var)
            model: Model name (defaults to DEEPSEEK_MODEL env var or "deepseek-chat")
            max_retries: Maximum retry attempts for failed calls
            timeout: Timeout in seconds for API calls
        """
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.max_retries = max_retries
        self.timeout = timeout

        if not self.api_key:
            raise ValueError("API key is required. Set DEEPSEEK_API_KEY environment variable.")

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=self.timeout
        )

        logger.info(f"LLM Client initialized: model={self.model}, base_url={self.base_url}")

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Make a chat completion request with retry logic.

        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens to generate
            tools: Optional list of tools for function calling
            tool_choice: Optional tool choice strategy

        Returns:
            Dict containing the API response

        Raises:
            Exception: If all retries fail
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                logger.debug(f"LLM API call attempt {attempt + 1}/{self.max_retries}")

                kwargs = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": temperature
                }

                if max_tokens:
                    kwargs["max_tokens"] = max_tokens

                if tools:
                    kwargs["tools"] = tools
                    if tool_choice:
                        kwargs["tool_choice"] = tool_choice

                response = self.client.chat.completions.create(**kwargs)

                logger.debug(f"LLM API call successful on attempt {attempt + 1}")

                # Convert to dict for easier handling
                return {
                    "id": response.id,
                    "model": response.model,
                    "choices": [
                        {
                            "index": choice.index,
                            "message": {
                                "role": choice.message.role,
                                "content": choice.message.content,
                                "tool_calls": [
                                    {
                                        "id": tc.id,
                                        "type": tc.type,
                                        "function": {
                                            "name": tc.function.name,
                                            "arguments": tc.function.arguments
                                        }
                                    } for tc in (choice.message.tool_calls or [])
                                ] if choice.message.tool_calls else None
                            },
                            "finish_reason": choice.finish_reason
                        } for choice in response.choices
                    ],
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens
                    }
                }

            except RateLimitError as e:
                last_error = e
                wait_time = 2 ** attempt  # Exponential backoff
                logger.warning(f"Rate limit hit, waiting {wait_time}s before retry {attempt + 1}/{self.max_retries}")
                time.sleep(wait_time)

            except APITimeoutError as e:
                last_error = e
                logger.warning(f"API timeout on attempt {attempt + 1}/{self.max_retries}: {e}")
                time.sleep(1)

            except APIError as e:
                last_error = e
                logger.error(f"API error on attempt {attempt + 1}/{self.max_retries}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    raise

            except Exception as e:
                last_error = e
                logger.error(f"Unexpected error on attempt {attempt + 1}/{self.max_retries}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                else:
                    raise

        # All retries failed
        error_msg = f"LLM API call failed after {self.max_retries} attempts: {last_error}"
        logger.error(error_msg)
        raise Exception(error_msg)

    def simple_completion(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Simple text completion helper.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt

        Returns:
            Generated text content
        """
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        messages.append({"role": "user", "content": prompt})

        response = self.chat_completion(messages)
        return response["choices"][0]["message"]["content"]
