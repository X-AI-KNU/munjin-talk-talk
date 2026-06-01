import {
  createDemoSession,
  getDemoGuide,
  getDemoOnePager,
  getDemoSession,
  listDemoSessions,
  markStaffRequested,
  saveDoctorResponse,
} from './demoSessions.js'

// AWS Lambda 백엔드와의 통신 레이어
//
// 엔드포인트 (총 9개):
//   POST /upload-url          → S3 presigned PUT URL 발급
//   GET  /transcribe-result   → Transcribe 결과 폴링
//   POST /extract             → Span 추출 (Claude or 규칙 기반)
//   POST /match               → BM25 + Titan hybrid 증상 매칭 (Q1/Q3)
//   POST /validate            → 4단 검증 + DDB 저장
//   GET  /onepager/{id}       → 의사 원페이퍼 조회
//   POST /doctor-response     → 의사 답변 수신 + Patient Guide 생성
//   GET  /guide/{id}          → 환자 안내문 조회
//
// VITE_ENABLE_MOCKS=true일 때만 mock 응답을 사용합니다.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''
const ENABLE_MOCKS = import.meta.env.VITE_ENABLE_MOCKS === 'true'
const useMockApi = () => !API_BASE_URL && ENABLE_MOCKS

export function isMockApiEnabled() {
  return useMockApi()
}

export function isRemoteApiEnabled() {
  return Boolean(API_BASE_URL)
}

// ─────────────────────────────────
// 세션 ID 생성
// ─────────────────────────────────
export function createSession() {
  const sessionId = `s-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
  return { sessionId, startedAt: new Date().toISOString() }
}

export async function createIntakeSession(form) {
  if (useMockApi()) {
    return createDemoSession(form)
  }
  if (!API_BASE_URL) throw new Error('API endpoint is not configured.')

  const res = await fetch(`${API_BASE_URL}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      visit_type: form.visitType,
      patient: {
        full_name: form.fullName,
        birth_date: form.birthDate,
        gender: form.gender,
        receipt_id: form.receiptId,
        department: form.department,
        doctor: form.doctor,
        phone: form.phone,
      },
    }),
  })
  if (!res.ok) throw new Error('문진 세션 생성 실패')
  return normalizeSession(await res.json())
}

export async function getDoctorQueue() {
  if (useMockApi()) {
    return listDemoSessions()
  }
  if (!API_BASE_URL) return []

  const res = await fetch(`${API_BASE_URL}/doctor/queue`)
  if (!res.ok) return []
  const data = await res.json()
  return (data.sessions || []).map(normalizeSession)
}

export async function getIntakeSession(sessionId) {
  if (!sessionId) return null
  if (useMockApi()) return getDemoSession(sessionId)
  if (!API_BASE_URL) return null

  const res = await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}`)
  if (!res.ok) return null
  return normalizeSession(await res.json())
}

export async function requestStaffHelp(sessionId) {
  if (useMockApi()) {
    return markStaffRequested(sessionId)
  }
  if (!API_BASE_URL) return null

  const res = await fetch(`${API_BASE_URL}/sessions/${encodeURIComponent(sessionId)}/staff-help`, {
    method: 'POST',
  })
  if (!res.ok) return null
  return normalizeSession(await res.json())
}

// ─────────────────────────────────
// Phase A: 음성 업로드 + Transcribe
// ─────────────────────────────────
export async function uploadAudio(audioBlob, sessionId, questionId, visitType = 'initial') {
  if (useMockApi()) {
    await new Promise(r => setTimeout(r, 800))
    return { transcribeJobName: `mock-${sessionId}-${questionId}`, s3Key: `sessions/${sessionId}/${questionId}.webm` }
  }
  if (!API_BASE_URL) throw new Error('API endpoint is not configured.')

  const contentType = audioBlob?.type || 'audio/wav'

  // 1) Presigned URL 발급
  const presignRes = await fetch(`${API_BASE_URL}/upload-url`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      question_id: questionId,
      visit_type: visitType,
      content_type: contentType
    })
  })
  const {
    upload_url,
    s3_key,
    transcribeJobName,
    transcribe_job_name: transcribeJobNameSnake,
  } = await presignRes.json()

  // 2) S3에 직접 PUT
  await fetch(upload_url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: audioBlob
  })

  return {
    transcribeJobName: transcribeJobName || transcribeJobNameSnake || `${sessionId}-${questionId}`,
    s3Key: s3_key,
  }
}

export async function getTranscript(jobName) {
  if (useMockApi()) {
    await new Promise(r => setTimeout(r, 1200))

    // v4: flag 강제 트리거 시 객혈 발화로 응답
    if (jobName.startsWith('mock-flag-trigger-')) {
      const qId = jobName.replace('mock-flag-trigger-', '')
      const flagTexts = {
        'Q1': '기침이 너무 심하고 어제 가래에 피가 좀 묻어 나왔어요. 가슴도 아파요.',
        'Q2': '한 일주일 됐는데 갈수록 더 심해지고 객혈도 시작됐어요.',
        'Q3': '기침이 더 심해졌고 어제는 피가 살짝 묻어 나왔어요.',
        'Q4': '혹시 결핵이나 폐암이 아닐까 걱정돼요. 피가 나오는 게 무섭습니다.'
      }
      return { transcript: flagTexts[qId] || flagTexts['Q3'], confidence: 0.91 }
    }

    // Mock 발화 (정상 시연용)
    const mockTexts = {
      // 초진
      'Q1_initial': '어제부터 목이 칼칼하고 코가 맥혀요. 기침도 조금 나요.',
      'Q2_initial': '그저께 저녁부터요. 손주 보러 갔다가 좀 추웠던 것 같아요.',
      'Q3_initial': '혈압약을 매일 아침에 먹어요. 다른 약은 안 먹고요.',
      'Q4_initial': '혈압약이랑 감기약을 같이 먹어도 되는지 궁금해요. 양파즙도 같이 먹어도 되나요?',
      // 재진 (정상 — 객혈 없음)
      'Q1_followup': '약 먹고 목은 좀 나아졌는데 코는 그대로예요. 기침은 더 심해졌어요.',
      'Q2_followup': '잘 먹었는데 한 번씩 깜빡해서 저녁에 못 먹기도 했어요.',
      'Q3_followup': '새로 생긴 증상은 없어요. 기침만 좀 심해진 거 같아요.',
      'Q4_followup': '이 약을 언제까지 먹어야 되나요?'
    }
    const qId = jobName.split('-').pop()
    return {
      transcript: mockTexts[qId] || mockTexts['Q1_initial'],
      confidence: 0.93
    }
  }
  if (!API_BASE_URL) throw new Error('API endpoint is not configured.')

  let latest = null
  for (let i = 0; i < 30; i += 1) {
    const res = await fetch(`${API_BASE_URL}/transcribe-result?jobName=${encodeURIComponent(jobName)}`)
    if (!res.ok) throw new Error('Transcribe 조회 실패')
    latest = await res.json()
    if (latest.status === 'COMPLETED' || latest.transcript) return latest
    if (latest.status === 'FAILED') throw new Error('Transcribe 작업 실패')
    await sleep(i < 3 ? 1000 : 2000)
  }
  return latest || { status: 'TIMEOUT', transcript: '', confidence: null }
}

// ─────────────────────────────────
// Phase A: Span 추출 + 매칭 + 검증 (한 번의 호출로 통합)
// ─────────────────────────────────
export async function processTranscript({
  sessionId, questionId, questionType, visitType, transcript
}) {
  if (useMockApi()) {
    await new Promise(r => setTimeout(r, 600))
    return mockProcessResponse(questionType, visitType, transcript)
  }
  if (!API_BASE_URL) throw new Error('API endpoint is not configured.')

  // 1) extract
  const extractRes = await fetch(`${API_BASE_URL}/extract`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId, question_id: questionId,
      question_type: questionType, visit_type: visitType,
      transcript
    })
  })
  const extracted = await extractRes.json()

  // 2) match (Q1만)
  let matched = { matched_slots: [], unmatched_spans: [] }
  if (questionType === 'chief_complaint' || questionType === 'progress' || questionType === 'new_symptoms') {
    const matchRes = await fetch(`${API_BASE_URL}/match`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId, question_id: questionId,
        visit_type: visitType,
        spans: extracted.spans
      })
    })
    matched = await matchRes.json()
  }

  // 3) validate + save
  const validateRes = await fetch(`${API_BASE_URL}/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId, question_id: questionId,
      question_type: questionType, visit_type: visitType,
      transcript,
      spans: extracted.spans,
      matched_slots: matched.matched_slots,
      structured: extracted.structured,
      method: extracted.method,
      llm_meta: extracted.llm_meta
    })
  })
  const validated = await validateRes.json()

  return {
    spans: extracted.spans,
    structured: extracted.structured,
    matched_slots: matched.matched_slots,
    unmatched_spans: matched.unmatched_spans,
    validator_passed: validated.validator_passed,
    safety_flag: validated.safety_flag,
    errors: validated.errors
  }
}

// ─────────────────────────────────
// 의사 원페이퍼 조회 (Doctor View)
// ─────────────────────────────────
export async function getOnePager(sessionId) {
  if (!sessionId) return null
  if (useMockApi()) return getDemoOnePager(sessionId)
  if (!API_BASE_URL) return null
  const res = await fetch(`${API_BASE_URL}/onepager/${sessionId}`)
  if (!res.ok) return null
  return res.json()
}

// ─────────────────────────────────
// Phase B: 의사 답변 전송 + Patient Guide 생성
// ─────────────────────────────────
export async function submitDoctorResponse({
  sessionId, reviewerId, answers, additionalNotes
}) {
  if (useMockApi()) {
    await new Promise(r => setTimeout(r, 1500))
    saveDoctorResponse(sessionId, {
      reviewerId,
      answers,
      additionalNotes,
      savedAt: new Date().toISOString(),
    })
    return {
      doctor_review_saved: true,
      patient_guide_generated: true,
      validator_passed: true,
      patient_guide: mockPatientGuide(answers)
    }
  }
  if (!API_BASE_URL) throw new Error('API endpoint is not configured.')

  const res = await fetch(`${API_BASE_URL}/doctor-response`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      reviewer_id: reviewerId || 'unknown',
      answers,
      patient_instruction: additionalNotes || '',
      additional_notes: additionalNotes || ''
    })
  })
  return res.json()
}

// ─────────────────────────────────
// Phase B: 환자 안내문 조회
// ─────────────────────────────────
export async function getPatientGuide(sessionId) {
  if (!sessionId) return null
  if (useMockApi()) return getDemoGuide(sessionId)
  if (!API_BASE_URL) return null
  const res = await fetch(`${API_BASE_URL}/guide/${sessionId}`)
  if (!res.ok) return null
  return res.json()
}

// ─────────────────────────────────
// Mock 응답 생성기
// ─────────────────────────────────
function mockProcessResponse(questionType, visitType, transcript) {
  if (questionType === 'chief_complaint') {
    return {
      spans: [
        { source_quote: '목이 칼칼하고', type: 'symptom' },
        { source_quote: '코가 맥혀요', type: 'symptom' },
        { source_quote: '기침도 조금 나요', type: 'symptom' }
      ],
      matched_slots: [
        { slot_id: 'throat_irritation', name: '목 불편감', score: 0.91, source_quote: '목이 칼칼하고' },
        { slot_id: 'nasal_obstruction', name: '코막힘', score: 0.88, source_quote: '코가 맥혀요' },
        { slot_id: 'cough', name: '기침', score: 0.84, source_quote: '기침도 조금 나요' }
      ],
      validator_passed: true,
      safety_flag: null
    }
  }
  if (questionType === 'progress') {
    return {
      spans: [
        { source_quote: '목은 좀 나아졌', type: 'progress_improved', slot_ref: 'throat_irritation' },
        { source_quote: '코는 그대로', type: 'progress_unchanged', slot_ref: 'nasal_obstruction' },
        { source_quote: '기침은 더 심해졌', type: 'progress_worsened', slot_ref: 'cough' }
      ],
      matched_slots: [
        { slot_id: 'throat_irritation', name: '목 불편감', source_quote: '목은 좀 나아졌', span_type: 'progress_improved' },
        { slot_id: 'nasal_obstruction', name: '코막힘', source_quote: '코는 그대로', span_type: 'progress_unchanged' },
        { slot_id: 'cough', name: '기침', source_quote: '기침은 더 심해졌', span_type: 'progress_worsened' }
      ],
      validator_passed: true,
      safety_flag: null
    }
  }
  if (questionType === 'new_symptoms' && transcript.includes('피')) {
    return {
      spans: [
        { source_quote: '기침이 더 심해졌', type: 'worsening', slot_ref: 'cough' },
        { source_quote: '피가 살짝 묻어 나왔어요', type: 'new', slot_ref: 'hemoptysis' }
      ],
      matched_slots: [
        { slot_id: 'hemoptysis', name: '객혈', source_quote: '피가 살짝 묻어 나왔어요', span_type: 'new' }
      ],
      validator_passed: true,
      safety_flag: {
        category: 'hemoptysis',
        label: '객혈 의증',
        severity: 'high',
        matched_pattern: '피가 살짝',
        action: 'safety_alert'
      }
    }
  }
  if (questionType === 'onset') {
    return {
      spans: [{ source_quote: '그저께 저녁부터', type: 'onset' }, { source_quote: '추웠던', type: 'context' }],
      structured: { estimated_onset_relative: '2일 전', context_hints: ['한기 노출'] },
      validator_passed: true, safety_flag: null
    }
  }
  if (questionType === 'adherence') {
    return {
      spans: [
        { source_quote: '잘 먹었는데', type: 'adherence_positive' },
        { source_quote: '한 번씩 깜빡', type: 'adherence_gap' }
      ],
      structured: { adherence_level: 'mostly_adherent_with_gaps', side_effects_reported: false },
      validator_passed: true, safety_flag: null
    }
  }
  if (questionType === 'current_medications') {
    return {
      spans: [],
      structured: {
        extracted_medications: [{ category: 'antihypertensive', patient_term: '혈압약', frequency: '매일 아침' }],
        denied_categories: ['others']
      },
      validator_passed: true, safety_flag: null
    }
  }
  if (questionType === 'patient_questions' || questionType === 'unresolved_questions') {
    return {
      spans: [],
      structured: {
        questions: transcript.includes('양파') ? [
          { category: 'drug_drug_interaction', summary: '혈압약-감기약 병용 가능 여부 문의', original_quote: '혈압약이랑 감기약을 같이 먹어도 되는지 궁금해요' },
          { category: 'food_drug_interaction', summary: '양파즙 병용 가능 여부 문의', original_quote: '양파즙도 같이 먹어도 되나요' }
        ] : [
          { category: 'treatment_duration', summary: '복약 기간 문의', original_quote: '이 약을 언제까지 먹어야 되나요' }
        ]
      },
      validator_passed: true, safety_flag: null
    }
  }
  return { spans: [], structured: {}, validator_passed: true, safety_flag: null }
}

function mockPatientGuide(answers) {
  return {
    generated_at: new Date().toISOString(),
    items: answers.map(a => ({
      question: a.question_summary,
      answer_simple: [
        '혈압약은 평소처럼 계속 드세요.',
        '일반 감기약은 5일까지 같이 드셔도 괜찮아요.',
        '약 사실 때 약사님께 "혈압약 먹는데 같이 먹을 수 있는 거 주세요"라고 꼭 말씀하세요.'
      ],
      tts_emphasis_words: ['혈압약', '5일', '약사님']
    })),
    delivery_options: ['screen', 'tts', 'sms_caregiver', 'print']
  }
}

function normalizeSession(session) {
  if (!session) return null
  const patient = session.patient || {}
  return {
    ...session,
    sessionId: session.sessionId || session.session_id,
    queueNumber: Number(session.queueNumber || session.queue_number || 0),
    visitType: session.visitType || session.visit_type || 'initial',
    patient: {
      ...patient,
      fullName: patient.fullName || patient.full_name || '',
      birthDate: patient.birthDate || patient.birth_date || '',
      receiptId: patient.receiptId || patient.receipt_id || '',
      name: patient.name || '환자',
      gender: patient.gender || '-',
      department: patient.department || '이비인후과',
      doctor: patient.doctor || '',
      honorific: patient.honorific || '어르신',
    },
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
