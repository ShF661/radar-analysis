"""Langfuse + OpenAI wrapper for all evolution AI calls."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional


def _extract_json(text: str) -> dict:
    """Parse JSON from model response, stripping markdown code fences if present."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if m:
        text = m.group(1)
    return json.loads(text)


class _NoOpSpan:
    def generation(self, **kwargs):
        return self
    def end(self, **kwargs):
        pass


class LLMClient:
    def __init__(
        self,
        lf_public_key: str,
        lf_secret_key: str,
        lf_host: str,
        llm_api_key: str,
        llm_base_url: str,
        model_fast: str,
        model_pro: str,
    ):
        from langfuse import Langfuse
        from openai import OpenAI

        self._lf = Langfuse(
            public_key=lf_public_key,
            secret_key=lf_secret_key,
            host=lf_host,
        )
        self._openai = OpenAI(
            api_key=llm_api_key,
            base_url=llm_base_url or None,
        )
        self.model_fast = model_fast
        self.model_pro = model_pro

    @classmethod
    def from_settings(cls, settings) -> "LLMClient":
        return cls(
            lf_public_key=settings.langfuse_public_key,
            lf_secret_key=settings.langfuse_secret_key,
            lf_host=settings.langfuse_host,
            llm_api_key=settings.llm_api_key,
            llm_base_url=settings.llm_base_url,
            model_fast=settings.llm_model_fast,
            model_pro=settings.llm_model_pro,
        )

    def _make_trace(self, trace_id: Optional[str], name: str):
        try:
            return self._lf.trace(id=trace_id, name=name)
        except AttributeError:
            return _NoOpSpan()

    def _get_messages(self, prompt_name: str, variables: dict) -> list[dict]:
        from langfuse.model import ChatPromptClient
        prompt = self._lf.get_prompt(prompt_name, type="chat")
        if isinstance(prompt, ChatPromptClient):
            return prompt.compile(**variables)
        text = prompt.compile(**variables)
        return [{"role": "user", "content": str(text)}]

    def call_json(
        self,
        prompt_name: str,
        variables: dict,
        model: str,
        trace_id: Optional[str] = None,
        retries: int = 3,
    ) -> dict:
        """Call LLM expecting JSON output. Retries on decode failure."""
        messages = self._get_messages(prompt_name, variables)
        trace = self._make_trace(trace_id, prompt_name)
        last_err: Exception | None = None

        for attempt in range(retries):
            gen = trace.generation(
                name=prompt_name,
                model=model,
                model_parameters={"temperature": 0.2},
                input=messages,
            )
            text = ""
            try:
                resp = self._openai.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                text = resp.choices[0].message.content
                gen.end(
                    output=text,
                    usage={"input": resp.usage.prompt_tokens,
                           "output": resp.usage.completion_tokens},
                )
                return _extract_json(text)
            except json.JSONDecodeError as e:
                gen.end(output=text, level="WARNING")
                last_err = e
            except Exception as e:
                gen.end(level="ERROR")
                last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

        raise RuntimeError(f"call_json failed after {retries} attempts: {last_err}")

    def call_text(
        self,
        prompt_name: str,
        variables: dict,
        model: str,
        trace_id: Optional[str] = None,
        retries: int = 3,
    ) -> str:
        """Call LLM expecting free-text output."""
        messages = self._get_messages(prompt_name, variables)
        trace = self._make_trace(trace_id, prompt_name)
        last_err: Exception | None = None

        for attempt in range(retries):
            gen = trace.generation(
                name=prompt_name,
                model=model,
                model_parameters={"temperature": 0.3},
                input=messages,
            )
            try:
                resp = self._openai.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=0.3,
                )
                text = resp.choices[0].message.content
                gen.end(
                    output=text,
                    usage={"input": resp.usage.prompt_tokens,
                           "output": resp.usage.completion_tokens},
                )
                return text
            except Exception as e:
                gen.end(level="ERROR")
                last_err = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

        raise RuntimeError(f"call_text failed after {retries} attempts: {last_err}")

    def flush(self) -> None:
        self._lf.flush()
