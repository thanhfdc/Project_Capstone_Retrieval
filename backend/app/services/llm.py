"""Optional LLM fallback that turns a query into mentions + relation phrases.

Used only when the rule parser sees a relation phrase but cannot find its seed entity.
The model never answers facts and never sees the corpus: it returns entity mentions,
which are resolved by the normal alias index, and relation phrases from a fixed list.
Off unless ANTHROPIC_API_KEY is set; at most one call per query with a hard timeout.
"""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field

from .query_parser import RELATION_PHRASES

log = logging.getLogger(__name__)

RelationName = Literal[tuple(sorted({v.label for v in RELATION_PHRASES.values()}))]  # type: ignore[valid-type]


class LlmIntent(BaseModel):
    entity_mentions: list[str] = Field(default_factory=list, max_length=3)
    relation_chain: list[str] = Field(default_factory=list, max_length=2,
                                      description="relation phrases, outermost first")
    visual_text: str = ""


class LlmPlan(BaseModel):
    intents: list[LlmIntent] = Field(min_length=1, max_length=3)
    needs_clarification: bool = False


SYSTEM = (
    "Bạn chuyển câu tìm ảnh tiếng Việt thành kế hoạch tìm kiếm. Không trả lời sự thật về người hay "
    "quan hệ, không đoán tên người con/vợ/chồng. entity_mentions là tên riêng xuất hiện trong câu "
    "(người, tổ chức, địa điểm), viết lại đúng chính tả nếu bị sai. relation_chain chỉ dùng các cụm: "
    + ", ".join(sorted({v.label for v in RELATION_PHRASES.values()}))
    + ". visual_text là phần mô tả cảnh/hành động còn lại. Nếu câu không rõ, đặt needs_clarification."
)


class LlmPlanner:
    def __init__(self, api_key: str, model: str, timeout_s: float):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=0)
        self.model = model

    def plan(self, query: str) -> tuple[LlmPlan | None, dict]:
        usage = {"llm_calls": 1, "input_tokens": 0, "output_tokens": 0}
        try:
            response = self.client.messages.parse(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM,
                messages=[{"role": "user", "content": query}],
                output_format=LlmPlan,
                output_config={"effort": "low"},
            )
            usage["input_tokens"] = response.usage.input_tokens
            usage["output_tokens"] = response.usage.output_tokens
            if response.stop_reason == "refusal":
                return None, usage
            return response.parsed_output, usage
        except Exception as exc:  # noqa: BLE001 - fallback must never break search
            log.warning("llm fallback failed: %s", exc)
            usage["error"] = type(exc).__name__
            return None, usage


def label_to_step(label: str):
    for step in RELATION_PHRASES.values():
        if step.label == label:
            return step
    return None
