import { API_BASE_URL, apiHeaders, ensureApiConfigured } from './client.js'

// 이미 스트리밍으로 확보한 전사 텍스트를 백엔드 orchestration graph에 전달합니다.
// 백엔드는 Bedrock extraction, schema validation, 증상 IR, 세션 저장,
// 원페이퍼 갱신을 하나의 서버 측 파이프라인에서 처리합니다.
export async function processTranscript({
  sessionId,
  questionId,
  questionType,
  questionText = '',
  questionSetId = 'default',
  visitType,
  transcript,
  role = '',
}) {
  ensureApiConfigured()

  const res = await fetch(`${API_BASE_URL}/process-answer`, {
    method: 'POST',
    headers: await apiHeaders({ role, sessionId, json: true }),
    body: JSON.stringify({
      session_id: sessionId,
      question_id: questionId,
      question_type: questionType,
      question_text: questionText,
      question_set_id: questionSetId,
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

// 환자 태블릿은 각 문항의 STT 결과를 먼저 화면에서 확인받습니다.
// Q1~Q4가 모두 확정되면 이 함수가 한 번만 호출되고,
// 서버는 같은 LangGraph 문항 파이프라인을 Q 순서대로 실행합니다.
export async function processTranscriptsBatch({
  sessionId,
  questionSetId = 'default',
  visitType,
  answers,
  role = '',
}) {
  ensureApiConfigured()

  const res = await fetch(`${API_BASE_URL}/process-answers`, {
    method: 'POST',
    headers: await apiHeaders({ role, sessionId, json: true }),
    body: JSON.stringify({
      session_id: sessionId,
      question_set_id: questionSetId,
      visit_type: visitType,
      answers,
    }),
  })

  const payload = await res.json().catch(() => ({}))
  if (!res.ok) {
    const message = payload?.message || payload?.error || '문진 일괄 처리에 실패했습니다.'
    const error = new Error(message)
    error.payload = payload
    throw error
  }
  const criticalFailures = (payload.failed_results || []).some((item) =>
    ['chief_complaint', 'progress', 'new_symptoms', 'patient_questions', 'unresolved_questions'].includes(
      item?.question_type,
    ),
  )
  // 일괄 처리에서는 Q2/Q3 같은 보조 맥락 문항이 일부 실패하더라도,
  // 핵심 증상/질문 문항과 원페이퍼가 준비되었다면 환자 화면을 오류로 되돌리지 않습니다.
  // 반대로 Q1/Q4처럼 의사 확인에 필수인 문항이 실패하면 기존처럼 다시 확인시킵니다.
  if (payload.validator_passed === false && (!payload.onepager_ready || criticalFailures)) {
    const error = new Error('문진 결과 검증에 실패했습니다. 다시 확인해 주세요.')
    error.payload = payload
    throw error
  }
  return payload
}
