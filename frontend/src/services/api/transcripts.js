import { API_BASE_URL, ensureApiConfigured } from './client.js'

// 이미 스트리밍으로 확보한 전사 텍스트를 백엔드 orchestration graph에 전달합니다.
// 백엔드는 Bedrock extraction, schema validation, 증상 IR, 세션 저장,
// 원페이퍼 갱신을 하나의 서버 측 파이프라인에서 처리합니다.
export async function processTranscript({
  sessionId,
  questionId,
  questionType,
  questionText = '',
  visitType,
  transcript,
}) {
  ensureApiConfigured()

  const res = await fetch(`${API_BASE_URL}/process-answer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      question_id: questionId,
      question_type: questionType,
      question_text: questionText,
      visit_type: visitType,
      transcript,
    }),
  })

  const payload = await res.json().catch(() => ({}))
  if (!res.ok) {
    const message = payload?.message || payload?.error || '문진 처리에 실패했습니다'
    throw new Error(message)
  }
  if (payload.validator_passed === false) {
    throw new Error('문진 결과 검증에 실패했습니다. 다시 말씀해 주세요.')
  }
  return payload
}
