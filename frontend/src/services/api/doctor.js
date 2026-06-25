import { API_BASE_URL, apiHeaders, ensureApiConfigured, getPatientToken } from './client.js'

// 원페이퍼 JSON을 조회합니다. 직원 미리보기와 의료진 화면 모두 내부 접근 코드가 필요합니다.
export async function getOnePager(sessionId, { role = 'doctor' } = {}) {
  if (!sessionId) return null
  ensureApiConfigured()

  const res = await fetch(`${API_BASE_URL}/onepager/${sessionId}`, {
    headers: await apiHeaders({ role }),
  })
  if (!res.ok) return null
  return res.json()
}

// 저장된 Q1~Q4 원문/표준화 결과로 onepaper를 재조립한 뒤 최종 AI 검토를 다시 실행합니다.
export async function rerunOnePagerReview(sessionId) {
  if (!sessionId) return null
  ensureApiConfigured()

  const res = await fetch(`${API_BASE_URL}/onepager/${sessionId}/review`, {
    method: 'POST',
    headers: await apiHeaders({ role: 'doctor', json: true }),
  })
  if (!res.ok) throw new Error('원페이퍼 AI 재검토 실패')
  return res.json()
}

// 저장된 Q1~Q4 원문을 기준으로 백그라운드 분석 전체를 다시 큐에 넣습니다.
export async function retryAnswerAnalysis(sessionId) {
  if (!sessionId) return null
  ensureApiConfigured()

  const res = await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/analysis/retry`, {
    method: 'POST',
    headers: await apiHeaders({ role: 'doctor', json: true }),
  })
  const payload = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(payload?.message || payload?.error || '문진 분석 재실행에 실패했습니다.')
  }
  return payload
}

// 의료진이 환자 질문에 답변하고 강조사항을 저장합니다.
export async function submitDoctorResponse({
  sessionId,
  reviewerId,
  answers,
  additionalNotes,
}) {
  ensureApiConfigured()

  const res = await fetch(`${API_BASE_URL}/doctor-response`, {
    method: 'POST',
    headers: await apiHeaders({ role: 'doctor', json: true }),
    body: JSON.stringify({
      session_id: sessionId,
      reviewer_id: reviewerId || 'unknown',
      answers,
      patient_instruction: additionalNotes || '',
      additional_notes: additionalNotes || '',
    }),
  })
  if (!res.ok) throw new Error('의사 답변 저장 실패')
  return res.json()
}

// 진료 후 환자에게 보여줄 안내문 JSON을 조회합니다.
export async function getPatientGuide(sessionId, { role = 'doctor', patientToken = '' } = {}) {
  if (!sessionId) return null
  ensureApiConfigured()

  const token = patientToken || getPatientToken(sessionId)
  const res = await fetch(`${API_BASE_URL}/guide/${sessionId}`, {
    headers: await apiHeaders({ role: token ? '' : role, sessionId, patientToken: token }),
  })
  if (!res.ok) return null
  return res.json()
}
