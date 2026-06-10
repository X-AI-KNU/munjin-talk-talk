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
import { detectSafetyKeyword } from '../../config/safetyKeywords.js'
import { processTranscript, recordPatientConsent } from '../../services/api.js'

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
// 실시간 Transcribe가 화면에 바로 텍스트를 보여주므로 별도 STT 확인 화면은 두지 않습니다.
export default function PatientFlow({
  initialVisitType = null,
  patient = null,
  sessionId = null,
  queueNumber = null,
  frameVariant = 'preview',
  skipVisitTypeWhenPreset = true,
  onTranscriptConfirmed,
  onComplete,
  onStaffCallRequest,
}) {
  const [step, setStep] = useState(initialVisitType && skipVisitTypeWhenPreset ? STEPS.Q_VOICE : STEPS.VISIT_TYPE)
  const [visitType, setVisitType] = useState(initialVisitType)
  const [questionIndex, setQuestionIndex] = useState(0)
  const [transcript, setTranscript] = useState('')
  const [safetyKeyword, setSafetyKeyword] = useState(null)
  const [answers, setAnswers] = useState([])
  const [prevStep, setPrevStep] = useState(null)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [pendingSafetyResult, setPendingSafetyResult] = useState(null)
  const [isEndingIntake, setIsEndingIntake] = useState(false)
  const [intakeStopped, setIntakeStopped] = useState(false)
  const [consentAccepted, setConsentAccepted] = useState(false)
  const [consentRejected, setConsentRejected] = useState(false)
  const [consentSaving, setConsentSaving] = useState(false)
  const [consentError, setConsentError] = useState('')

  const questions = visitType ? QUESTIONS[visitType] : []
  const currentQuestion = questions[questionIndex]
  const activeSessionId = sessionId || ''
  const displayPatient = patient || EMPTY_PATIENT

  useEffect(() => {
    if (!activeSessionId) {
      setConsentAccepted(false)
      return
    }
    setConsentAccepted(window.sessionStorage.getItem(consentStorageKey(activeSessionId)) === PRIVACY_CONSENT_VERSION)
    setConsentRejected(false)
    setConsentError('')
  }, [activeSessionId])

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
  }, [activeSessionId, currentQuestion, onStaffCallRequest])

  const handleConsentStaffHelp = useCallback(() => {
    onStaffCallRequest?.({
      sessionId: activeSessionId,
      questionId: currentQuestion?.id || null,
      step: 'privacy_consent',
      reason: 'privacy_consent_help',
    })
    setPrevStep('privacy_consent')
    setStep(STEPS.STAFF_CALL)
  }, [activeSessionId, currentQuestion, onStaffCallRequest])

  const handleConsentStaffCallReturn = useCallback(() => {
    setPrevStep(null)
    setStep(initialVisitType && skipVisitTypeWhenPreset ? STEPS.Q_VOICE : STEPS.VISIT_TYPE)
  }, [initialVisitType, skipVisitTypeWhenPreset])

  const handleStaffCall = useCallback(() => {
    onStaffCallRequest?.({
      sessionId: activeSessionId,
      questionId: currentQuestion?.id || null,
      step,
    })
    setPrevStep(step)
    setStep(STEPS.STAFF_CALL)
  }, [activeSessionId, currentQuestion, onStaffCallRequest, step])

  const handleStaffCallReturn = useCallback(() => {
    setStep(prevStep || STEPS.VISIT_TYPE)
    setPrevStep(null)
  }, [prevStep])

  const handleVisitTypeConfirm = useCallback((path) => {
    setVisitType(path)
    setQuestionIndex(0)
    setTranscript('')
    setStep(STEPS.Q_VOICE)
  }, [])

  const advanceWithConfirmedAnswer = useCallback((result, answerText) => {
    if (!currentQuestion) return
    const confirmedAnswer = {
      id: currentQuestion.id,
      questionId: currentQuestion.id,
      transcript: answerText,
      question_type: currentQuestion.question_type,
      result,
    }
    const nextAnswers = [...answers, confirmedAnswer]

    onTranscriptConfirmed?.(confirmedAnswer)
    setAnswers(nextAnswers)
    setTranscript('')
    setPendingSafetyResult(null)
    setSafetyKeyword(null)

    if (questionIndex >= questions.length - 1) {
      onComplete?.({
        sessionId: activeSessionId,
        visitType,
        answers: nextAnswers,
      })
      setStep(STEPS.DONE)
      return
    }

    setQuestionIndex(questionIndex + 1)
    setStep(STEPS.Q_VOICE)
  }, [
    answers,
    currentQuestion,
    onComplete,
    onTranscriptConfirmed,
    questionIndex,
    questions.length,
    activeSessionId,
    visitType,
  ])

  const runBackendPipeline = useCallback(async (answerText) => {
    if (!currentQuestion) throw new Error('missing_question')
    if (!activeSessionId) throw new Error('missing_session')
    return processTranscript({
      sessionId: activeSessionId,
      questionId: currentQuestion.id,
      questionType: currentQuestion.question_type,
      questionText: questionTextForBackend(currentQuestion),
      visitType,
      transcript: answerText,
    })
  }, [activeSessionId, currentQuestion, visitType])

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
    setIsTranscribing(true)

    try {
      const safety = detectSafetyKeyword(answerText)
      if (safety && safety.severity === 'high') {
        setSafetyKeyword(safety)
        setPendingSafetyResult(null)
        onStaffCallRequest?.({
          sessionId: activeSessionId,
          questionId: currentQuestion?.id || null,
          step: STEPS.SAFETY_ALERT,
          reason: 'safety_keyword',
        })
        setStep(STEPS.SAFETY_ALERT)
        return
      }

      const result = await runBackendPipeline(answerText)
      if (result.safety_flag && result.safety_flag.severity === 'high') {
        setSafetyKeyword(result.safety_flag)
        setPendingSafetyResult(result)
        setStep(STEPS.SAFETY_ALERT)
        return
      }

      advanceWithConfirmedAnswer(result, answerText)
    } catch (err) {
      console.error('STT/process failed:', err)
      setTranscript('문진 처리 중 오류가 발생했습니다. 다시 말씀해 주세요.')
      setStep(STEPS.Q_VOICE)
    } finally {
      setIsTranscribing(false)
    }
  }, [activeSessionId, advanceWithConfirmedAnswer, currentQuestion, onStaffCallRequest, runBackendPipeline, transcript])

  const handleSafetyContinue = useCallback(async () => {
    const answerText = transcript.trim()
    setIsTranscribing(true)
    try {
      if (pendingSafetyResult) {
        advanceWithConfirmedAnswer(pendingSafetyResult, answerText)
        return
      }
      if (!answerText) {
        setStep(STEPS.Q_VOICE)
        return
      }
      const result = await runBackendPipeline(answerText)
      advanceWithConfirmedAnswer(result, answerText)
    } catch (err) {
      console.error('Safety continue failed:', err)
      setStep(STEPS.Q_VOICE)
    } finally {
      setIsTranscribing(false)
    }
  }, [advanceWithConfirmedAnswer, pendingSafetyResult, runBackendPipeline, transcript])

  const handleSafetyEnd = useCallback(async () => {
    setIsEndingIntake(true)
    const answerText = transcript.trim()
    let nextAnswers = answers

    try {
      let result = pendingSafetyResult
      if (!result && answerText && currentQuestion) {
        result = await runBackendPipeline(answerText)
      }
      if (result && currentQuestion && answerText) {
        const confirmedAnswer = {
          id: currentQuestion.id,
          questionId: currentQuestion.id,
          transcript: answerText,
          question_type: currentQuestion.question_type,
          result,
        }
        nextAnswers = [...answers, confirmedAnswer]
        onTranscriptConfirmed?.(confirmedAnswer)
        setAnswers(nextAnswers)
      }
    } catch (err) {
      console.error('Safety end failed:', err)
    } finally {
      onComplete?.({
        sessionId: activeSessionId,
        visitType,
        answers: nextAnswers,
        stopped: true,
      })
      setTranscript('')
      setPendingSafetyResult(null)
      setSafetyKeyword(null)
      setIntakeStopped(true)
      setIsEndingIntake(false)
      setStep(STEPS.DONE)
    }
  }, [
    answers,
    currentQuestion,
    onComplete,
    onTranscriptConfirmed,
    pendingSafetyResult,
    runBackendPipeline,
    activeSessionId,
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
            isProcessing={isTranscribing}
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
            isProcessing={isTranscribing}
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
            isEnding={isEndingIntake || isTranscribing}
          />
        )

      case STEPS.STAFF_CALL:
        return (
          <StaffCallScreen
            patient={displayPatient}
            onReturn={handleStaffCallReturn}
            returnLabel={prevStep === STEPS.VISIT_TYPE ? '진료 화면으로 돌아가기' : '문진 계속하기'}
          />
        )

      case STEPS.DONE:
        return (
          <DoneScreen
            patient={displayPatient}
            visitType={visitType}
            stopped={intakeStopped}
            queueNumber={queueNumber}
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
          returnLabel="동의 화면으로 돌아가기"
        />
      )
    }

    if (consentRejected) {
      return (
        <ManualIntakeScreen
          patient={displayPatient}
          visitType={visitType}
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

function questionTextForBackend(question) {
  if (!question) return ''
  return [question.badge, question.title, question.sub]
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim()
}
