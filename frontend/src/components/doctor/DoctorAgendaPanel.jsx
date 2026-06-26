import { useState, useEffect } from 'react'
import { normalizeAgendaSource } from '../../services/onepagerAdapter.js'
import './DoctorAgendaPanel.css'

// 원페이퍼 우측 패널입니다.
// Q4 환자 질문을 의사가 확인하고 답변/강조사항을 작성하면 submitDoctorResponse로 저장됩니다.

// 우측 통합 패널 — UI 개선안 2의 핵심
// ────────────────────────────────────────
// 한 카드 안에 다음을 모두 묶음:
//   1. 환자 질문 요약 (LLM 분류 결과)
//   2. 환자 원문 (Q4 누락 시 의사가 즉시 감지 가능)
//   3. 답변 입력 textarea (각 질문 인라인)
//   4. 잔여 텍스트 경고 (uncategorized_remnant)
//   5. 환자 안내 강조사항 + 전송 버튼

const CATEGORY_LABEL = {
  drug_drug_interaction: '복약 상호작용',
  food_drug_interaction: '음식-약 상호작용',
  treatment_duration:    '복약 기간',
  prognosis:             '예후·회복',
  general_health_info:   '일반 건강정보',
  prognosis_concern:     '심각성 우려',
  other:                 '기타'
}

function isNoQuestionTranscript(text) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim()
  if (!normalized) return false
  return (
    /^(따로\s*)?(없어요|없습니다|없음|없어|없다|아니요|아뇨|괜찮아요|괜찮습니다)/.test(normalized) ||
    /(궁금한\s*(건|거|것)?|질문)\s*(은|는|이|가)?\s*(따로\s*)?(없어요|없습니다|없음|없어|없다)/.test(normalized) ||
    /(딱히|별로)\s*(궁금한\s*(건|거|것)?|질문)?\s*(없어요|없습니다|없음|없어|없다)/.test(normalized)
  )
}

export default function DoctorAgendaPanel({ sessionData, submitStatus, onSubmit }) {
  // 백엔드 onepager에서 validator를 통과한 Q4 agenda만 사용합니다.
  // 프론트에서 질문을 임의 생성하지 않아야 저장된 JSON과 화면이 어긋나지 않습니다.
  const normalized = normalizeAgendaSource(sessionData, [])
  const fullTranscript = normalized.full_q4_transcript || ''
  const agenda = normalized.agenda || []
  const uncategorizedRemnant = normalized.uncategorized_remnant || ''

  // agenda 항목 수만큼 의사 답변 textarea 상태를 생성합니다.

  // 각 질문에 대한 답변
  const [answers, setAnswers] = useState(() =>
    agenda.map(item => ({
      question_summary: item.summary,
      original_quote: item.original_quote,
      answer_text: ''
    }))
  )
  const [patientInstruction, setPatientInstruction] = useState('')

  // 새 세션을 열거나 Q4 분류 결과가 갱신되면 이전 답변 상태가 섞이지 않게 초기화합니다.
  useEffect(() => {
    setAnswers(agenda.map(item => ({
      question_summary: item.summary,
      original_quote: item.original_quote,
      answer_text: ''
    })))
  }, [JSON.stringify(agenda)])

  const handleAnswerChange = (idx, value) => {
    setAnswers(prev => prev.map((a, i) => i === idx ? { ...a, answer_text: value } : a))
  }

  const filledCount = answers.filter(a => a.answer_text.trim().length > 0).length
  const noPatientQuestion = answers.length === 0 && isNoQuestionTranscript(fullTranscript)
  const hasPatientInstruction = patientInstruction.trim().length > 0
  const canSubmit = filledCount > 0 || hasPatientInstruction || noPatientQuestion
  const submitButtonLabel = noPatientQuestion && !hasPatientInstruction
    ? '문진 완료 처리'
    : '환자 안내문 생성'

  const handleSubmit = () => {
    if (!canSubmit) return
    // 빈 답변은 제외하고 전송
    // 비어 있는 답변은 제외하고, 의사가 실제 작성한 답변과 강조사항만 백엔드로 보냅니다.
    const filled = answers.filter(a => a.answer_text.trim().length > 0)
    onSubmit({ answers: filled, additionalNotes: patientInstruction })
  }

  return (
    <div className="doctor-agenda-panel">
      <header className="dap-header">
        <h3>환자 질문 + 답변 입력</h3>
        {/* Phase B 배지 제거됨 */}
      </header>

      {/* "답변을 입력하면 LLM이..." 긴 설명 제거됨 */}

      {/* ─── 환자 발화 원문 (디자인 고도화) ─── */}
      <section className="dap-full-quote dap-full-quote-v4">
        <div className="dap-quote-head-v4">
          <span className="dap-quote-icon-v4">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
              <path d="M3 12a9 9 0 1 1 18 0 9 9 0 0 1-18 0z" stroke="#0c4a6e" strokeWidth="2"/>
              <path d="M12 7v5l3 2" stroke="#0c4a6e" strokeWidth="2" strokeLinecap="round"/>
            </svg>
          </span>
          <div className="dap-quote-meta-v4">
            <b>환자 발화 원문</b>
            <small>Q4 전체 — AI 분류 확인</small>
          </div>
        </div>
        <p className="dap-quote-content-v4">
          {fullTranscript ? `"${fullTranscript}"` : '환자 질문 발화가 아직 입력되지 않았습니다.'}
        </p>
      </section>

      {/* ─── 잔여 텍스트 경고 (Q4 누락 방지 묘수 ①) ─── */}
      {uncategorizedRemnant && (
        <section className="dap-remnant-alert">
          <span className="dap-icon">⚠</span>
          <div>
            <b>자동 분류 미적용 발화</b>
            <p>"{uncategorizedRemnant}"</p>
            <small>→ 의사 직접 확인 권장 (LLM이 카테고리화하지 못한 내용)</small>
          </div>
        </section>
      )}

      {/* ─── 환자 질문 + 답변 입력 인라인 ─── */}
      <section className="dap-questions">
        {answers.length === 0 && (
          <div className="dap-empty-state">
            {noPatientQuestion
              ? '환자가 별도 질문이 없다고 답했습니다. 안내문 없이 문진 완료 처리가 가능합니다.'
              : '환자 질문이 아직 없습니다. 문진 완료 후 답변 입력 항목이 표시됩니다.'}
          </div>
        )}
        {answers.map((answer, idx) => {
          const item = agenda[idx]
          return (
            <article key={idx} className="dap-question-block">
              <div className="dap-question-head">
                <span className="dap-q-num">Q{idx + 1}</span>
                <div className="dap-q-meta">
                  <span className="dap-q-category">
                    {item.type_label || CATEGORY_LABEL[item.category] || '환자 질문'}
                  </span>
                  <strong>{answer.question_summary}</strong>
                </div>
              </div>

              <div className="dap-q-quote">
                <span className="dap-label">원문</span>
                <p>"{answer.original_quote}"</p>
              </div>

              <textarea
                className="dap-textarea"
                placeholder="환자에게 전달할 답변 (의미 유지 — 존댓말만 정리)"
                value={answer.answer_text}
                onChange={(e) => handleAnswerChange(idx, e.target.value)}
                rows={4}
              />
              <div className="dap-char-count">{answer.answer_text.length}자</div>
            </article>
          )
        })}
      </section>

      {/* ─── 환자 안내 강조사항 ─── */}
      <section className="dap-notes-block dap-patient-instruction-block">
        <label className="dap-label">환자 안내 강조사항 (선택 · 안내문에 표시)</label>
        <textarea
          className="dap-textarea dap-notes"
          placeholder="예: 다음 주 X-ray 검진이 필요합니다. / 약은 중단하지 말고 꼭 복용해 주세요."
          value={patientInstruction}
          onChange={(e) => setPatientInstruction(e.target.value)}
          rows={3}
        />
        <p className="dap-instruction-help">
          의사가 환자에게 꼭 남기고 싶은 일정, 검사, 복약, 생활관리 안내를 적습니다.
        </p>
      </section>

      {/* ─── 액션 ─── */}
      <div className="dap-action-bar">
        <div className="dap-status">
          {submitStatus === 'submitting' && '안내문 생성 중...'}
          {submitStatus === 'success' && '✓ 안내문 생성 완료. 안내문 출력 화면에서 확인할 수 있습니다.'}
          {submitStatus === 'completed_no_guide' && '✓ 별도 안내문 없이 문진 완료 처리되었습니다.'}
          {submitStatus === 'invalid' && '⚠ 안내문 문장 생성에 실패했습니다. 답변을 조금 더 구체적으로 작성해 주세요.'}
          {submitStatus === 'error' && '⚠ 전송 실패. 다시 시도해 주세요'}
          {!submitStatus && (noPatientQuestion ? '환자 질문 없음 · 안내문 없이 완료 가능' : `${filledCount}/${answers.length} 답변 입력됨`)}
        </div>
        <button
          className="dap-submit"
          disabled={!canSubmit || submitStatus === 'submitting'}
          onClick={handleSubmit}
        >
          {submitStatus === 'submitting' ? '처리 중...' : submitButtonLabel}
        </button>
      </div>
    </div>
  )
}
