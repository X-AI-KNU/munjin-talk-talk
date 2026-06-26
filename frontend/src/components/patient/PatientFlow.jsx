import { useCallback, useEffect, useState } from 'react'
import TabletFrame from '../tablet/TabletFrame.jsx'
import VisitTypeScreen from './VisitTypeScreen.jsx'
import VoiceScreen from './VoiceScreen.jsx'
import ConfirmTranscriptScreen from './ConfirmTranscriptScreen.jsx'
import SafetyAlertScreen from './SafetyAlertScreen.jsx'
import StaffCallScreen from './StaffCallScreen.jsx'
import DoneScreen from './DoneScreen.jsx'
import ManualIntakeScreen from './ManualIntakeScreen.jsx'
import PrivacyConsentModal, {
  PRIVACY_CONSENT_VERSION,
  PRIVACY_NOTICE_ITEMS,
  RETENTION_NOTICE,
  SENSITIVE_NOTICE_ITEMS,
} from './PrivacyConsentModal.jsx'
import { QUESTIONS } from '../../config/questions.js'
import { questionTextForBackend } from '../../config/questionText.js'
import { detectSafetyKeyword } from '../../config/safetyKeywords.js'
import { getQuestionSet, processTranscriptsBatch, recordPatientConsent } from '../../services/api.js'

const EMPTY_PATIENT = {
  name: '환자',
  honorific: '',
  age: '-',
  gender: '-',
  receiptId: '-',
}

const STEPS = {
  VISIT_TYPE: 'visit_type',
  Q_VOICE: 'q_voice',
  Q_CONFIRM: 'q_confirm',
  SAFETY_ALERT: 'safety_alert',
  STAFF_CALL: 'staff_call',
  DONE: 'done',
}

function consentStorageKey(sessionId) {
  return `munjin:privacy-consent:${sessionId || 'unknown'}`
}

// 환자 태블릿 문진의 상태 머신입니다.
// 환자는 각 문항의 STT 결과를 직접 확인하고, LLM/LangGraph 처리는 Q1~Q4가
// 모두 모인 뒤 한 번에 실행합니다. 문항마다 LLM 대기 시간을 만들지 않기 위함입니다.
export default function PatientFlow({
  initialVisitType = null,
  patient = null,
  sessionId = null,
  questionSetId = 'default',
  frameVariant = 'preview',
  skipVisitTypeWhenPreset = true,
  onTranscriptConfirmed,
  onComplete,
  onStaffCallRequest,
  onExitToQueue,
}) {
  const [step, setStep] = useState(initialVisitType && skipVisitTypeWhenPreset ? STEPS.Q_VOICE : STEPS.VISIT_TYPE)
  const [visitType, setVisitType] = useState(initialVisitType)
  const [questionIndex, setQuestionIndex] = useState(0)
  const [transcript, setTranscript] = useState('')
  const [safetyKeyword, setSafetyKeyword] = useState(null)
  const [answers, setAnswers] = useState([])
  const [prevStep, setPrevStep] = useState(null)
  const [isEndingIntake, setIsEndingIntake] = useState(false)
  const [intakeStopped, setIntakeStopped] = useState(false)
  const [consentAccepted, setConsentAccepted] = useState(false)
  const [consentRejected, setConsentRejected] = useState(false)
  const [consentSaving, setConsentSaving] = useState(false)
  const [consentError, setConsentError] = useState('')
  const [questionSet, setQuestionSet] = useState(null)

  const questionVisits = questionSet?.visits || QUESTIONS
  const questions = visitType ? (questionVisits[visitType] || QUESTIONS[visitType] || []) : []
  const currentQuestion = questions[questionIndex]
  const activeSessionId = sessionId || ''
  const displayPatient = patient || EMPTY_PATIENT

  const notifyStaff = useCallback((payload) => {
    try {
      const result = onStaffCallRequest?.(payload)
      if (result && typeof result.catch === 'function') {
        result.catch((error) => {
          console.warn('staff call request failed:', error)
        })
      }
    } catch (error) {
      console.warn('staff call request failed:', error)
    }
  }, [onStaffCallRequest])

  useEffect(() => {
    if (!activeSessionId) {
      setConsentAccepted(false)
      return
    }
    setConsentAccepted(window.sessionStorage.getItem(consentStorageKey(activeSessionId)) === PRIVACY_CONSENT_VERSION)
    setConsentRejected(false)
    setConsentError('')
  }, [activeSessionId])

  useEffect(() => {
    let active = true
    getQuestionSet(questionSetId || 'default')
      .then((next) => {
        if (active) setQuestionSet(next)
      })
      .catch((error) => {
        console.warn('bundled question set used:', error)
        if (active) setQuestionSet(null)
      })
    return () => {
      active = false
    }
  }, [questionSetId])

  const saveConsent = useCallback(async (accepted) => {
    if (!activeSessionId) {
      setConsentError('문진 세션을 찾을 수 없습니다. 접수 직원에게 말씀해 주세요.')
      return
    }
    setConsentSaving(true)
    setConsentError('')
    try {
      await recordPatientConsent(activeSessionId, {
        accepted,
        version: PRIVACY_CONSENT_VERSION,
        privacy_items: PRIVACY_NOTICE_ITEMS,
        sensitive_items: SENSITIVE_NOTICE_ITEMS,
        retention_notice: RETENTION_NOTICE,
      })
      if (accepted) {
        window.sessionStorage.setItem(consentStorageKey(activeSessionId), PRIVACY_CONSENT_VERSION)
        setConsentAccepted(true)
        setConsentRejected(false)
      } else {
        window.sessionStorage.removeItem(consentStorageKey(activeSessionId))
        setConsentRejected(true)
        setIntakeStopped(true)
      }
    } catch (error) {
      console.error('privacy consent save failed:', error)
      setConsentError('동의 이력을 저장하지 못했습니다. 네트워크 상태를 확인하거나 직원에게 말씀해 주세요.')
    } finally {
      setConsentSaving(false)
    }
  }, [activeSessionId])

  const handleConsentStaffHelp = useCallback(() => {
    notifyStaff({
      sessionId: activeSessionId,
      questionId: currentQuestion?.id || null,
      step: 'privacy_consent',
      reason: 'privacy_consent_help',
    })
    setPrevStep('privacy_consent')
    setStep(STEPS.STAFF_CALL)
  }, [activeSessionId, currentQuestion, notifyStaff])

  const handleConsentStaffCallReturn = useCallback(() => {
    setPrevStep(null)
    setStep(initialVisitType && skipVisitTypeWhenPreset ? STEPS.Q_VOICE : STEPS.VISIT_TYPE)
  }, [initialVisitType, skipVisitTypeWhenPreset])

  const handleReturnToConsent = useCallback(() => {
    setConsentRejected(false)
    setConsentError('')
    setIntakeStopped(false)
  }, [])

  const handleStaffCall = useCallback(() => {
    notifyStaff({
      sessionId: activeSessionId,
      questionId: currentQuestion?.id || null,
      step,
    })
    setPrevStep(step)
    setStep(STEPS.STAFF_CALL)
  }, [activeSessionId, currentQuestion, notifyStaff, step])

  const handleVisitTypeConfirm = useCallback((path) => {
    setVisitType(path)
    setQuestionIndex(0)
    setTranscript('')
    setStep(STEPS.Q_VOICE)
  }, [])

  const submitBatchAndComplete = useCallback((pendingAnswers, { stopped = false } = {}) => {
    if (!activeSessionId) throw new Error('missing_session')

    const completedAnswers = pendingAnswers.map((answer) => ({
      ...answer,
      result: answer.result || {
        analysis_status: 'pending',
        analysis_queued: true,
      },
    }))

    // 환자 경험은 "답변 확인 완료"를 기준으로 즉시 종료한다.
    // 저장과 LangGraph 분석 큐 등록은 뒤에서 진행하고, 실패 시 직원에게만 알린다.
    setAnswers(completedAnswers)
    completedAnswers.forEach((answer) => onTranscriptConfirmed?.(answer))
    onComplete?.({
      sessionId: activeSessionId,
      visitType,
      answers: completedAnswers,
      stopped,
    })
    setTranscript('')
    setSafetyKeyword(null)
    setIntakeStopped(stopped)
    setStep(STEPS.DONE)

    processTranscriptsBatch({
        sessionId: activeSessionId,
        questionSetId: questionSetId || 'default',
        visitType,
        answers: pendingAnswers.map(toBatchPayloadAnswer),
      })
      .catch((err) => {
        console.error('batch intake processing failed:', err)
        const failedIndex = Math.max(0, Number(err?.payload?.batch_index || pendingAnswers.length) - 1)
        notifyStaff({
          sessionId: activeSessionId,
          questionId: pendingAnswers[failedIndex]?.questionId || pendingAnswers[failedIndex]?.id || null,
          step: 'batch_processing_failed',
          reason: 'batch_processing_failed',
          batchIndex: failedIndex + 1,
        })
      })
  }, [
    activeSessionId,
    notifyStaff,
    onComplete,
    onTranscriptConfirmed,
    questionSetId,
    visitType,
  ])

  const advanceWithConfirmedAnswer = useCallback(async (answerText) => {
    if (!currentQuestion) return
    const confirmedAnswer = {
      id: currentQuestion.id,
      questionId: currentQuestion.id,
      transcript: answerText,
      question_type: currentQuestion.question_type,
      questionText: questionTextForBackend(currentQuestion),
      result: null,
    }
    const nextAnswers = [...answers, confirmedAnswer]

    setAnswers(nextAnswers)
    setTranscript('')
    setSafetyKeyword(null)

    if (questionIndex >= questions.length - 1) {
      await submitBatchAndComplete(nextAnswers)
      return
    }

    setQuestionIndex(questionIndex + 1)
    setStep(STEPS.Q_VOICE)
  }, [
    answers,
    currentQuestion,
    questionIndex,
    questions.length,
    submitBatchAndComplete,
  ])

  const handleVoiceFinish = useCallback((sttText) => {
    const answerText = String(sttText || '').trim()
    if (!answerText) {
      setTranscript('음성 인식 결과가 비어 있습니다. 다시 말씀해 주세요.')
      return
    }
    setTranscript(answerText)
    setStep(STEPS.Q_CONFIRM)
  }, [])

  const handleRetryTranscript = useCallback(() => {
    setTranscript('')
    setStep(STEPS.Q_VOICE)
  }, [])

  const handleConfirmTranscript = useCallback(async (confirmedText = transcript) => {
    const answerText = String(confirmedText || transcript || '').trim()
    if (!answerText || answerText.includes('음성 인식 결과가 비어 있습니다')) {
      setStep(STEPS.Q_VOICE)
      return
    }
    setTranscript(answerText)

    try {
      const safety = detectSafetyKeyword(answerText)
      if (safety && safety.severity === 'high') {
        setSafetyKeyword(safety)
        notifyStaff({
          sessionId: activeSessionId,
          questionId: currentQuestion?.id || null,
          step: STEPS.SAFETY_ALERT,
          reason: 'safety_keyword',
        })
        setStep(STEPS.SAFETY_ALERT)
        return
      }

      await advanceWithConfirmedAnswer(answerText)
    } catch (err) {
      console.error('STT/process failed:', err)
      setTranscript('문진 처리 중 오류가 발생했습니다. 다시 말씀해 주세요.')
      setStep(STEPS.Q_VOICE)
    }
  }, [activeSessionId, advanceWithConfirmedAnswer, currentQuestion, notifyStaff, transcript])

  const handleSafetyContinue = useCallback(async () => {
    const answerText = transcript.trim()
    try {
      if (!answerText) {
        setStep(STEPS.Q_VOICE)
        return
      }
      await advanceWithConfirmedAnswer(answerText)
    } catch (err) {
      console.error('Safety continue failed:', err)
      setStep(STEPS.Q_VOICE)
    }
  }, [advanceWithConfirmedAnswer, transcript])

  const handleStaffCallReturn = useCallback(() => {
    // 안전 플래그 화면에서 직원 도움을 받은 뒤에는 같은 경고 화면으로 되돌리지 않는다.
    // 현재 답변을 확정하고 다음 문항으로 넘겨야 태블릿 흐름이 막히지 않는다.
    if (prevStep === STEPS.SAFETY_ALERT) {
      setPrevStep(null)
      handleSafetyContinue()
      return
    }
    setStep(prevStep || STEPS.VISIT_TYPE)
    setPrevStep(null)
  }, [handleSafetyContinue, prevStep])

  const handleSafetyEnd = useCallback(async () => {
    setIsEndingIntake(true)
    const answerText = transcript.trim()
    let nextAnswers = answers

    try {
      if (currentQuestion && answerText) {
        const confirmedAnswer = {
          id: currentQuestion.id,
          questionId: currentQuestion.id,
          transcript: answerText,
          question_type: currentQuestion.question_type,
          questionText: questionTextForBackend(currentQuestion),
          result: null,
        }
        nextAnswers = [...answers, confirmedAnswer]
        setAnswers(nextAnswers)
      }
      if (nextAnswers.length) {
        await submitBatchAndComplete(nextAnswers, { stopped: true })
        return
      }
    } catch (err) {
      console.error('Safety end failed:', err)
    } finally {
      setTranscript('')
      setSafetyKeyword(null)
      setIntakeStopped(true)
      setIsEndingIntake(false)
      if (!nextAnswers.length) {
        onComplete?.({
          sessionId: activeSessionId,
          visitType,
          answers: nextAnswers,
          stopped: true,
        })
        setStep(STEPS.DONE)
      }
    }
  }, [
    answers,
    currentQuestion,
    onComplete,
    activeSessionId,
    submitBatchAndComplete,
    transcript,
    visitType,
  ])

  const renderScreen = () => {
    switch (step) {
      case STEPS.VISIT_TYPE:
        return (
          <VisitTypeScreen
            patient={displayPatient}
            defaultVisitType={visitType}
            onConfirm={handleVisitTypeConfirm}
            onStaffCall={handleStaffCall}
          />
        )

      case STEPS.Q_VOICE:
        return (
          <VoiceScreen
            sessionId={activeSessionId}
            patient={displayPatient}
            visitType={visitType}
            question={currentQuestion}
            stepIndex={questionIndex + 1}
            partialText={transcript}
            isProcessing={false}
            onFinish={handleVoiceFinish}
            onStaffCall={handleStaffCall}
          />
        )

      case STEPS.Q_CONFIRM:
        return (
          <ConfirmTranscriptScreen
            patient={displayPatient}
            visitType={visitType}
            question={currentQuestion}
            stepIndex={questionIndex + 1}
            transcript={transcript}
            isProcessing={false}
            onConfirm={handleConfirmTranscript}
            onRetry={handleRetryTranscript}
            onStaffCall={handleStaffCall}
          />
        )

      case STEPS.SAFETY_ALERT:
        return (
          <SafetyAlertScreen
            patient={displayPatient}
            visitType={visitType}
            stepIndex={questionIndex + 1}
            safetyKeyword={safetyKeyword}
            onContinue={handleSafetyContinue}
            onEnd={handleSafetyEnd}
            isEnding={isEndingIntake}
          />
        )

      case STEPS.STAFF_CALL:
        return (
          <StaffCallScreen
            patient={displayPatient}
            onReturn={handleStaffCallReturn}
            onExitToQueue={onExitToQueue}
            returnLabel={prevStep === STEPS.VISIT_TYPE ? '진료 화면으로 돌아가기' : '문진 계속하기'}
          />
        )

      case STEPS.DONE:
        return (
          <DoneScreen
            patient={displayPatient}
            visitType={visitType}
            stopped={intakeStopped}
            onExitToQueue={onExitToQueue}
          />
        )

      default:
        return null
    }
  }

  const renderConsentGate = () => {
    if (step === STEPS.STAFF_CALL) {
      return (
        <StaffCallScreen
          patient={displayPatient}
          onReturn={handleConsentStaffCallReturn}
          onExitToQueue={onExitToQueue}
          returnLabel="동의 화면으로 돌아가기"
        />
      )
    }

    if (consentRejected) {
      return (
        <ManualIntakeScreen
          patient={displayPatient}
          visitType={visitType}
          onReturnToConsent={handleReturnToConsent}
          onExitToQueue={onExitToQueue}
        />
      )
    }

    return (
      <PrivacyConsentModal
        patientName={`${displayPatient.name || '환자'} ${displayPatient.honorific || ''}`.trim()}
        isSaving={consentSaving}
        error={consentError}
        rejected={consentRejected}
        onAccept={() => saveConsent(true)}
        onReject={() => saveConsent(false)}
        onStaffHelp={handleConsentStaffHelp}
      />
    )
  }

  return (
    <TabletFrame visitType={visitType} variant={frameVariant}>
      {consentAccepted && renderScreen()}
      {!consentAccepted && renderConsentGate()}
    </TabletFrame>
  )
}

function toBatchPayloadAnswer(answer) {
  return {
    question_id: answer.questionId || answer.id,
    question_type: answer.question_type || answer.questionType,
    question_text: answer.questionText || '',
    transcript: answer.transcript || '',
  }
}
