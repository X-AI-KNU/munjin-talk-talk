"""문진 도메인 설정 로더.

증상 slot, alias, 안전 플래그, 기본 질문 문구는 코드 로직이 아니라
`data/domain_pack_*.json`에 정의합니다. 이렇게 두면 호흡기계 MVP 이후
타 진료계로 확장할 때 검증 로직은 유지하고 도메인 데이터만 바꿔 끼울 수 있습니다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from utils import load_json_file


DEFAULT_DOMAIN_PACK = "domain_pack_respiratory.json"
DOMAIN_DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=1)
def get_domain_pack() -> dict[str, Any]:
    """현재 배포에서 사용할 도메인팩 JSON을 읽어 캐시합니다."""
    path = DOMAIN_DATA_DIR / DEFAULT_DOMAIN_PACK
    pack = load_json_file(path)
    if not isinstance(pack, dict):
        raise RuntimeError(f"Invalid domain pack: {path}")
    return pack


def question_text_for(visit_type: str, question_id: str) -> str:
    """백엔드 fallback용 기본 질문 문구를 반환합니다.

    프론트엔드가 `question_text`를 보내면 그 값을 우선 사용합니다. 이 함수는
    오래된 프론트나 직원 직접 입력 경로처럼 질문 문구가 누락된 요청을 위한
    안전한 fallback입니다.
    """
    questions = get_domain_pack().get("questions") or {}
    visit_questions = questions.get(str(visit_type or "")) or {}
    return str(visit_questions.get(str(question_id or "")) or "")


def symptom_slot_ids() -> set[str]:
    """LLM extraction schema에서 허용할 증상 slot_ref 집합입니다."""
    pack = get_domain_pack()
    ids = {
        str(item.get("slot_id"))
        for item in pack.get("symptom_rules", [])
        if isinstance(item, dict) and item.get("slot_id")
    }
    ids.update(str(item) for item in (pack.get("ir_slot_to_canonical_name") or {}).keys())
    ids.add("other")
    return ids
