import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createIntakeSession, getDoctorQueue, getIntakeSession, processTranscript } from '../../services/api.js'
import { QUESTIONS } from '../../config/questions.js'
import { questionTextForBackend } from '../../config/questionText.js'
import logoUrl from '../../assets/munjin-logo.svg'
import ReceptionForm from './ReceptionForm.jsx'
import ReceptionManualInput from './ReceptionManualInput.jsx'
import ReceptionSessionList from './ReceptionSessionList.jsx'
import { formatBirthDate, getBirthDateError, INITIAL_RECEPTION_FORM } from './receptionUtils.js'
import './ReceptionView.css'

// 접수처 화면의 controller 역할만 담당합니다.
// 실제 폼/목록/직원 대리 입력 UI는 하위 컴포넌트로 분리했습니다.
export default function ReceptionView() {
  const navigate = useNavigate()
  const [form, setForm] = useState(INITIAL_RECEPTION_FORM)
  const [sessions, setSessions] = useState([])
  const [created, setCreated] = useState(null)
  const [manualSession, setManualSession] = useState(null)
  const [manualTexts, setManualTexts] = useState({})
  const [manualOriginalTexts, setManualOriginalTexts] = useState({})
  const [manualStatus, setManualStatus] = useState('')
  const [manualSubmitting, setManualSubmitting] = useState(false)
  const [formError, setFormError] = useState('')

  const loadSessions = useCallback(async () => {
    try {
      setSessions(await getDoctorQueue())
    } catch (error) {
      console.error('reception queue refresh failed:', error)
      setSessions([])
    }
  }, [])

  useEffect(() => {
    loadSessions()
    const timer = setInterval(loadSessions, 5000)
    return () => clearInterval(timer)
  }, [loadSessions])

  const waitingCount = useMemo(
    () => sessions.filter((session) => ['waiting_tablet', 'in_progress', 'staff_help'].includes(session.status)).length,
    [sessions]
  )

  const updateField = (key, value) => {
    const nextValue = key === 'birthDate' ? formatBirthDate(value) : value
    setForm((prev) => ({ ...prev, [key]: nextValue }))
    if (key === 'birthDate') setFormError('')
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    const birthError = getBirthDateError(form.birthDate)
    if (birthError) {
      setFormError(birthError)
      return
    }
    setFormError('')
    try {
      const next = await createIntakeSession(form)
      await loadSessions()
      setCreated(next)
    } catch (error) {
      console.error('create session failed:', error)
      setFormError('문진 세션을 생성하지 못했습니다. 네트워크와 백엔드 상태를 확인해 주세요.')
    }
  }

  const openManualInput = async (session) => {
    setManualStatus('문진 내용을 불러오는 중입니다.')
    const detail = await getIntakeSession(session.sessionId)
    const nextSession = detail || session
    const nextTexts = makeManualTextState(nextSession)
    setManualSession(nextSession)
    setManualTexts(nextTexts)
    setManualOriginalTexts(nextTexts)
    setManualStatus('환자가 말한 내용을 직원이 대신 입력할 수 있습니다.')
  }

  const updateManualText = (questionId, value) => {
    setManualTexts((prev) => ({ ...prev, [questionId]: value }))
  }

  const handleManualSubmit = async (event) => {
    event.preventDefault()
    if (!manualSession || manualSubmitting) return

    const filled = getChangedManualAnswers(manualSession, manualTexts, manualOriginalTexts)
    if (!filled.length) {
      setManualStatus('새로 입력하거나 수정한 문진 내용이 없습니다.')
      return
    }

    setManualSubmitting(true)
    setManualStatus('백엔드 LLM 분석과 검증을 진행하고 있습니다.')
    try {
      for (const { question, transcript } of filled) {
        await processTranscript({
          sessionId: manualSession.sessionId,
          questionId: question.id,
          questionType: question.question_type,
          questionText: questionTextForBackend(question),
          questionSetId: manualSession.questionSetId || 'default',
          visitType: manualSession.visitType,
          transcript,
        })
      }
      await loadSessions()
      const refreshed = await getIntakeSession(manualSession.sessionId)
      if (refreshed) setManualSession(refreshed)
      setManualOriginalTexts(manualTexts)
      setManualStatus('직원 입력이 저장되었습니다. 원페이퍼에서 결과를 확인할 수 있습니다.')
    } catch (error) {
      console.error('manual intake failed:', error)
      setManualStatus('저장 중 오류가 발생했습니다. 네트워크와 백엔드 상태를 확인해 주세요.')
    } finally {
      setManualSubmitting(false)
    }
  }

  return (
    <div className="reception-page">
      <header className="reception-header">
        <div>
          <p className="rp-eyebrow">접수 데스크</p>
          <div className="rp-brand-lockup">
            <img className="rp-logo-svg" src={logoUrl} alt="" aria-hidden="true" />
            <h1>문진톡톡</h1>
          </div>
        </div>
        <div className="rp-stats">
          <div>
            <span>{sessions.length}</span>
            <small>오늘 접수</small>
          </div>
          <div>
            <span>{waitingCount}</span>
            <small>문진 대기</small>
          </div>
        </div>
      </header>

      <div className="reception-grid">
        <ReceptionForm
          form={form}
          created={created}
          updateField={updateField}
          onSubmit={handleSubmit}
          onOpenTablet={(sessionId) => navigate(`/patient/${sessionId}`)}
          submitError={formError}
        />
        <ReceptionSessionList sessions={sessions} onOpenManualInput={openManualInput} />
      </div>

      <ReceptionManualInput
        session={manualSession}
        manualTexts={manualTexts}
        manualStatus={manualStatus}
        submitting={manualSubmitting}
        updateManualText={updateManualText}
        onSubmit={handleManualSubmit}
        onClose={() => setManualSession(null)}
      />
    </div>
  )
}

function makeManualTextState(session) {
  const responses = session.responses || {}
  return Object.fromEntries(
    (QUESTIONS[session.visitType] || QUESTIONS.initial).map((question) => [
      question.id,
      responses[question.id]?.text || responses[question.id]?.transcript || '',
    ])
  )
}

function getChangedManualAnswers(session, manualTexts, originalTexts) {
  const questions = QUESTIONS[session.visitType] || QUESTIONS.initial
  return questions
    .map((question) => ({ question, transcript: (manualTexts[question.id] || '').trim() }))
    .filter((item) => item.transcript && item.transcript !== (originalTexts[item.question.id] || '').trim())
}
