import { useState, useEffect, useMemo } from 'react'
import { getOnePager, isMockApiEnabled } from '../../services/api.js'
import { normalizeOnePager } from '../../services/onepagerAdapter.js'
import './DoctorOnePager.css'

// v4 변경:
// - "진단명 추천 없음" / "검증 완료" 자잘한 chips 제거
// - 의료진 확인 항목 체크박스 실제 작동 (클릭 시 체크 + 파란 테두리)
// - 재진의 변화 추적 카드를 "오늘 말한 불편함" 디자인으로 변경
//   (EMR 연동 안 되므로 이전 진료 추적 불가, 환자가 새로 말한 증상 그대로 표시)
// - 좌우 패널 길이 차이로 무너지지 않도록 균형 조정
// - "위험 — 우선 평가 필요" amber 배지는 유지 (재진 객혈 시연용)

const CopyIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <rect x="8" y="8" width="12" height="12" rx="2" stroke="currentColor" strokeWidth="2"/>
    <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" stroke="currentColor" strokeWidth="2"/>
  </svg>
)

const CheckIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
    <path d="M5 12l5 5L20 7" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

const SYMPTOM_CONTEXT_CATEGORIES = ['증상맥락', '재진경과']
const STANDALONE_CONTEXT_CATEGORIES = ['증상맥락', '재진경과', '복약정보', '복약순응도', '약물반응']

function clueKey(clue) {
  return clue.id || `${clue.category || ''}-${clue.source_question || ''}-${clue.source_quote || clue.summary || ''}`
}

function getCluesForSlot(slot, clues = []) {
  return (clues || []).filter((clue) => {
    const relatedSymptoms = clue.related_symptoms || []
    const sameSymptom = relatedSymptoms.length === 1 && relatedSymptoms.includes(slot.name)
    const sameQuestion = clue.source_question && slot.sourceQuestion && clue.source_question === slot.sourceQuestion
    const clueQuote = clue.source_quote || clue.summary || ''
    const slotQuote = slot.sourceQuote || slot.normalizedText || ''
    const sameQuote = Boolean(clueQuote && slotQuote && (slotQuote.includes(clueQuote) || clueQuote.includes(slotQuote)))
    const isSymptomContext = SYMPTOM_CONTEXT_CATEGORIES.includes(clue.category)
    return isSymptomContext && (sameQuote || sameSymptom || (!relatedSymptoms.length && sameQuestion))
  }).slice(0, 4)
}

function getUnlinkedClues(slots = [], clues = []) {
  const linkedKeys = new Set()

  ;(slots || []).forEach((slot) => {
    getCluesForSlot(slot, clues).forEach((clue) => linkedKeys.add(clueKey(clue)))
  })

  return (clues || []).filter((clue) => {
    if (linkedKeys.has(clueKey(clue))) return false
    return STANDALONE_CONTEXT_CATEGORIES.includes(clue.category)
  }).slice(0, 8)
}

function ClueChip({ clue }) {
  const isPriority = clue.priority === '우선'
  const text = clue.summary || clue.source_quote || ''
  if (!text) return null

  return (
    <span className={`slot-clue-chip ${isPriority ? 'priority' : ''}`}>
      <b>{clue.label || clue.category}</b>
      <span>{text}</span>
    </span>
  )
}

// Mock — 초진
const MOCK_INITIAL = {
  patient: {
    name: '김*자', age: 74, gender: '여성', department: '이비인후과',
    visit_type: 'initial', receivedAt: '10:30', audioDuration: 58
  },
  agenda: [
    { type: 'drug_drug_interaction', type_label: '복약 상호작용',
      summary: '혈압약-감기약 병용 가능 여부 문의',
      original_quote: '혈압약이랑 감기약을 같이 먹어도 되는지 궁금해요' },
    { type: 'food_drug_interaction', type_label: '음식-약 상호작용',
      summary: '양파즙 병용 가능 여부 문의',
      original_quote: '양파즙도 같이 먹어도 되나요' }
  ],
  full_q4_transcript: '혈압약이랑 감기약을 같이 먹어도 되는지 궁금해요. 양파즙도 같이 먹어도 되나요?',
  symptomSlots: [
    { name: '목 불편감', sub: '인후 자극', sourceQuote: '목이 칼칼하고', score: 0.91 },
    { name: '코막힘', sub: '비폐색', sourceQuote: '코가 맥혀요 (사투리 자동 매칭)', score: 0.88 },
    { name: '기침', sub: 'cough', sourceQuote: '기침도 조금 나요', score: 0.84 }
  ],
  clinicalClues: [
    {
      id: 'mock-c1', category: '증상맥락', label: '시작시점', summary: '어제부터',
      source_question: 'Q1', source_quote: '어제부터', priority: '일반',
      related_symptoms: ['목 불편감', '코막힘', '기침']
    },
    {
      id: 'mock-c2', category: '복약정보', label: '복용중', summary: '혈압약 복용 중',
      source_question: 'Q3', source_quote: '혈압약 먹고 있어요', priority: '일반',
      related_symptoms: []
    },
    {
      id: 'mock-c3', category: '증상맥락', label: '동반', summary: '기침도 동반',
      source_question: 'Q1', source_quote: '기침도 조금 나요', priority: '일반',
      related_symptoms: ['기침']
    }
  ],
  reviewItems: [
    '발열 여부와 실제 체온 확인',
    '가래 동반 여부와 색깔',
    '혈압약 ↔ 일반 감기약 병용 가능 여부 안내',
    '양파즙 병용 가능 여부 답변',
    '흡연력 및 알레르기 이력 (음성에서 미수집)'
  ],
  transferText: '74세 여성 환자. 어제부터 목 불편감과 코막힘 호소. 발열은 없다고 말함. 혈압약 복용 중 감기약 병용 가능 여부 문의.',
  safety_flag: null
}

// Mock — 재진 (위험 분기 시연용)
// v4: 변화 추적 카드 대신 "오늘 말한 불편함"으로 통일 (EMR 미연동)
const MOCK_FOLLOWUP = {
  patient: {
    name: '김*자', age: 74, gender: '여성', department: '이비인후과',
    visit_type: 'followup', receivedAt: '11:15', audioDuration: 42
  },
  agenda: [
    { type: 'treatment_duration', type_label: '복약 기간',
      summary: '복약 기간 문의',
      original_quote: '이 약을 언제까지 먹어야 되나요' }
  ],
  full_q4_transcript: '이 약을 언제까지 먹어야 되나요?',
  uncategorized_remnant: '',
  symptomSlots: [
    { name: '기침', sub: 'cough · 악화', sourceQuote: '기침이 더 심해졌고', score: 0.89 },
    { name: '객혈', sub: 'hemoptysis · 신규 ⚠', sourceQuote: '어제는 피가 살짝 묻어 나왔어요', score: 0.93, alert: true },
  ],
  clinicalClues: [
    {
      id: 'mock-f1', category: '재진경과', label: '악화', summary: '기침이 더 심해짐',
      source_question: 'Q1', source_quote: '기침이 더 심해졌고', priority: '일반',
      related_symptoms: ['기침']
    },
    {
      id: 'mock-f2', category: '재진경과', label: '새 증상', summary: '객혈 새로 발생',
      source_question: 'Q1', source_quote: '피가 살짝 묻어 나왔어요', priority: '우선',
      related_symptoms: ['객혈']
    }
  ],
  reviewItems: [
    '[우선] 객혈 평가 (X-ray·객담 검사 고려)',
    '[우선] 객혈량과 시작 시점 확인',
    '기침 악화 패턴 평가',
    '복약 순응도 (저녁 누락) 영향 평가',
    '흡연력 재확인'
  ],
  transferText: '재진 환자. 환자 호소: 기침 악화 + 객혈 신규 발생 ("피가 살짝 묻어 나왔다"). 환자 미해결 질문: 복약 기간 문의.',
  safety_flag: {
    category: 'hemoptysis', label: '객혈 의증',
    severity: 'high', matched_pattern: '피가 살짝'
  }
}


export default function DoctorOnePager({ sessionId, sessionData, sidePanel, renderAgenda = true }) {
  const [apiData, setApiData] = useState(null)
  const [copied, setCopied] = useState(false)
  const [mockOverride, setMockOverride] = useState(null)
  const [checked, setChecked] = useState({})  // {0: true, 2: true} 형태

  useEffect(() => {
    if (sessionData || !sessionId) return
    getOnePager(sessionId).then(setApiData)
  }, [sessionId, sessionData])

  const data = useMemo(() => {
    const fallback = isMockApiEnabled() ? (mockOverride === 'followup' ? MOCK_FOLLOWUP : MOCK_INITIAL) : null
    const source = sessionData || apiData || fallback
    return source ? normalizeOnePager(source, fallback) : null
  }, [sessionData, apiData, mockOverride])

  // mock 변경 시 체크 초기화
  useEffect(() => {
    setChecked({})
  }, [mockOverride])

  if (!data) {
    return (
      <div className="onepaper-v4 onepaper-empty">
        <div className="op-card">
          <div className="op-card-title">
            <h4>원페이퍼를 표시할 세션이 없습니다</h4>
          </div>
          <p>직원 접수에서 문진 세션을 생성하고 환자 문진을 완료하면 이 화면에 내용이 표시됩니다.</p>
        </div>
      </div>
    )
  }

  const isFollowup = data.patient.visit_type === 'followup'
  const themeClass = isFollowup ? 'theme-followup' : 'theme-initial'
  const symptomSlots = data.symptomSlots || []
  const clinicalClues = data.clinicalClues || []
  const unlinkedClues = getUnlinkedClues(symptomSlots, clinicalClues)

  const handleCopy = () => {
    navigator.clipboard?.writeText(data.transferText)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const toggleCheck = (idx) => {
    setChecked(prev => ({ ...prev, [idx]: !prev[idx] }))
  }

  return (
    <div className={`onepaper-v4 ${themeClass}`}>

      {/* 데모용 토글 (실시연 시 제거) */}
      {isMockApiEnabled() && !sessionData && !apiData && (
        <div className="onepaper-demo-toggle">
          <button
            className={!mockOverride || mockOverride === 'initial' ? 'active' : ''}
            onClick={() => setMockOverride('initial')}
          >Mock: 초진</button>
          <button
            className={mockOverride === 'followup' ? 'active' : ''}
            onClick={() => setMockOverride('followup')}
          >Mock: 재진 (위험 분기)</button>
        </div>
      )}

      {/* 위험 플래그 */}
      {data.safety_flag && data.safety_flag.severity === 'high' && (
        <div className="op-safety-alert">
          <span className="osa-icon">⚠</span>
          <div>
            <b>{data.safety_flag.label} — 우선 평가 필요</b>
            <p>{data.safety_flag.message || `감지: "${data.safety_flag.matched_pattern}" (${data.safety_flag.category})`}</p>
          </div>
        </div>
      )}

      {/* 환자 정보 바 — "진단명 추천 없음" / "검증 완료" 제거 */}
      <div className="op-patient-bar">
        <div className="op-patient-info">
          <h4>
            {data.patient.name} · {data.patient.age}세 {data.patient.gender} · {data.patient.department}
          </h4>
          <p>
            <span className={`op-visit-badge ${data.patient.visit_type}`}>
              {isFollowup ? '재진' : '초진'}
            </span>
            <span>접수 {data.patient.receivedAt}</span>
            <span className="op-dot" />
            <span>음성 {data.patient.audioDuration}초</span>
          </p>
        </div>
        {/* "진단명 추천 없음" / "검증 완료" chips 제거됨 */}
      </div>

      {/* 좌우 분할 */}
      <div className="op-split">

        {/* 좌측 3카드 */}
        <div className="op-left">

          {/* 카드 1: 증상 슬롯 + 증상별 맥락 단서 */}
          <section className="op-card symptom-card">
            <div className="op-card-title">
              <h4>오늘 말한 불편함</h4>
              <span className={`op-chip ${isFollowup ? 'teal' : 'blue'}`}>
                {isFollowup ? '재진' : '초진'}
              </span>
            </div>

            {symptomSlots.length > 0 ? (
              <div className="slot-rows">
                {symptomSlots.map((slot, i) => {
                  const slotClues = getCluesForSlot(slot, clinicalClues)
                  return (
                    <div key={i} className={`slot-row ${slot.alert ? 'slot-row-alert' : ''}`}>
                      <div className="slot-name">
                        {slot.name} <small>({slot.sub})</small>
                      </div>
                      <div className={`slot-score ${slot.alert ? 'slot-score-alert' : ''}`}>
                        {Number(slot.score || 0).toFixed(2)}
                      </div>
                      {slot.sourceQuote && <div className="slot-quote">"{slot.sourceQuote}"</div>}
                      {slotClues.length > 0 && (
                        <div className="slot-clues">
                          {slotClues.map((clue) => (
                            <ClueChip key={clueKey(clue)} clue={clue} />
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ) : (
              <div className="slot-empty">직접 매칭된 증상 슬롯은 없습니다.</div>
            )}

            {unlinkedClues.length > 0 && (
              <div className="context-strip">
                <div className="context-strip-title">문진 맥락</div>
                <div className="context-strip-items">
                  {unlinkedClues.map((clue) => (
                    <ClueChip key={clueKey(clue)} clue={clue} />
                  ))}
                </div>
              </div>
            )}
          </section>

          {/* 카드 2: 의료진 확인 항목 — 체크박스 실제 작동 */}
          <section className="op-card review-card">
            <div className="op-card-title">
              <h4>{isFollowup ? '재진 확인 항목' : '의료진 확인 항목'}</h4>
              <span className="op-chip gray">체크용</span>
            </div>
            <ul className="check-list-v4">
              {data.reviewItems.map((item, i) => {
                const isPriority = item.startsWith('[우선]')
                const isChecked = !!checked[i]
                return (
                  <li
                    key={i}
                    className={[
                      'check-item-v4',
                      isPriority && 'check-priority',
                      isChecked && 'check-checked'
                    ].filter(Boolean).join(' ')}
                    onClick={() => toggleCheck(i)}
                  >
                    <span className={`check-box-v4 ${isChecked ? 'checked' : ''}`}>
                      {isChecked && <CheckIcon />}
                    </span>
                    <span className="check-text-v4">{item}</span>
                  </li>
                )
              })}
            </ul>
          </section>

          {/* 카드 3: 기록용 문장 */}
          <section className="op-card transfer-card">
            <div className="op-card-title">
              <h4>기록용 문장</h4>
              <span className="op-chip teal">EMR 복사</span>
            </div>
            <p className="transfer-text">{data.transferText}</p>
            <button className="copy-btn" onClick={handleCopy}>
              <CopyIcon />
              {copied ? '복사됨!' : 'EMR로 복사'}
            </button>
          </section>
        </div>

        {/* 우측 패널 */}
        <aside className="op-right">
          {sidePanel}
        </aside>
      </div>
    </div>
  )
}
