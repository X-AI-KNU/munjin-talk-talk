"""LangChain 기반 Bedrock JSON 호출 체인.

이 모듈은 LangChain을 단순 프롬프트 문자열 조립에만 쓰지 않고,
`PromptTemplate -> Bedrock 호출 Runnable -> JSON parser` 흐름으로 사용합니다.

의도적으로 `langchain-aws` 대신 `langchain-core`만 사용합니다. Lambda package를
작게 유지하면서도 LangChain의 Runnable/Parser 구조를 실제 호출 경로에 넣기
위함입니다. 실제 AWS 호출은 boto3 Bedrock Runtime client가 수행하고, 그 호출을
LangChain `RunnableLambda`로 감싸 체인의 한 노드로 편입합니다.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from settings import bedrock_runtime


def call_bedrock_json_chain(prompt: str, model_id: str, max_tokens: int) -> dict[str, Any]:
    """LangChain Runnable chain으로 Bedrock JSON 호출을 실행합니다.

    반환값은 기존 코드가 필요로 하는 `parsed`와 `raw_text`뿐 아니라,
    어떤 LangChain parser 경로를 탔는지 알 수 있는 `meta`도 포함합니다.
    이 meta는 CloudWatch/S3 trace에서 "LangChain이 실제 어느 단계에 쓰였는지"를
    확인하는 근거가 됩니다.
    """
    chain = _bedrock_json_chain(model_id, int(max_tokens))
    return chain.invoke({"prompt": prompt or ""})


@lru_cache(maxsize=16)
def _bedrock_json_chain(model_id: str, max_tokens: int):
    """동일 모델/토큰 설정의 Runnable chain을 Lambda warm runtime에서 재사용합니다."""
    prompt_template = ChatPromptTemplate.from_messages([("human", "{prompt}")])
    invoke_bedrock = RunnableLambda(lambda prompt_value: _invoke_bedrock(prompt_value, model_id, max_tokens))
    parse_json = RunnableLambda(_parse_bedrock_json_response)
    return prompt_template | invoke_bedrock | parse_json


def _invoke_bedrock(prompt_value, model_id: str, max_tokens: int) -> dict[str, Any]:
    """LangChain prompt value를 Bedrock Converse request로 변환해 호출합니다."""
    messages = [_to_bedrock_message(message) for message in prompt_value.to_messages()]
    response = bedrock_runtime.converse(
        modelId=model_id,
        messages=messages,
        inferenceConfig={"temperature": 0, "maxTokens": max_tokens},
    )
    raw_text = "".join(
        block.get("text", "")
        for block in response.get("output", {}).get("message", {}).get("content", [])
    )
    return {
        "raw_text": raw_text,
        "model_id": model_id,
        "max_tokens": max_tokens,
        "message_count": len(messages),
    }


def _parse_bedrock_json_response(payload: dict[str, Any]) -> dict[str, Any]:
    """LangChain JsonOutputParser로 먼저 파싱하고, 실패 시 보수적 parser를 사용합니다."""
    raw_text = payload.get("raw_text") or ""
    parse_method = "langchain_json_output_parser"
    try:
        parsed = JsonOutputParser().parse(raw_text)
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception:
        # Nova가 드물게 markdown fence나 설명 문장을 섞으면 LangChain parser가
        # 실패할 수 있습니다. 이때도 rule-base extraction으로 대체하지 않고,
        # 응답 안의 첫 JSON object만 꺼내 schema validator로 넘깁니다.
        parsed = extract_first_json_object(raw_text)
        parse_method = "backup_first_json_object"

    payload["parsed"] = parsed if isinstance(parsed, dict) else {}
    payload["meta"] = {
        "chain": "langchain_core_prompt_bedrock_json",
        "prompt_adapter": "ChatPromptTemplate",
        "bedrock_runnable": "RunnableLambda",
        "output_parser": parse_method,
        "model_id": payload.get("model_id"),
        "max_tokens": payload.get("max_tokens"),
        "message_count": payload.get("message_count"),
        "raw_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    }
    return payload


def build_bedrock_messages(prompt: str) -> list[dict[str, Any]]:
    """Bedrock Converse message만 필요한 보조 경로에서 재사용하는 함수입니다."""
    chat_prompt = ChatPromptTemplate.from_messages([("human", "{prompt}")])
    prompt_value = chat_prompt.invoke({"prompt": prompt or ""})
    return [_to_bedrock_message(message) for message in prompt_value.to_messages()]


def _to_bedrock_message(message) -> dict[str, Any]:
    """LangChain message 객체를 Bedrock Converse message 형식으로 변환합니다."""
    role = "user" if isinstance(message, HumanMessage) else "assistant"
    return {"role": role, "content": [{"text": _message_text(message.content)}]}


def _message_text(content: Any) -> str:
    """LangChain message content가 list/dict로 들어와도 안전하게 문자열화합니다."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    return str(content or "")


def extract_first_json_object(text: str) -> dict[str, Any]:
    """LLM 응답 텍스트에서 가장 바깥 JSON object를 찾아 파싱합니다."""
    raw = str(text or "").strip()
    raw = re.sub(r"^```(?:json)?", "", raw, flags=re.I).strip()
    raw = re.sub(r"```$", "", raw).strip()
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    start = raw.find("{")
    if start < 0:
        return {}
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(raw)):
        char = raw[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(raw[start:idx + 1])
                    return parsed if isinstance(parsed, dict) else {}
                except Exception:
                    return {}
    return {}
