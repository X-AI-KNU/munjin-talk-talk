import { API_BASE_URL, ensureApiConfigured } from './client.js'

// 백엔드가 제공하는 질문 세트를 가져옵니다.
// 실패 시 호출부에서 번들 질문을 보조 경로로 사용하므로 여기서는 오류를 그대로 던집니다.
export async function getQuestionSet(questionSetId = 'default') {
  ensureApiConfigured()

  const res = await fetch(`${API_BASE_URL}/question-sets/${encodeURIComponent(questionSetId || 'default')}`)
  if (!res.ok) throw new Error('질문 세트 조회 실패')
  return res.json()
}
