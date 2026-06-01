import { useState, useCallback, useEffect } from 'react'
import TabletFrame from '../tablet/TabletFrame.jsx'
import VisitTypeScreen from './VisitTypeScreen.jsx'
import VoiceScreen from './VoiceScreen.jsx'
import VerifyScreen from './VerifyScreen.jsx'
import SafetyAlertScreen from './SafetyAlertScreen.jsx'
import StaffCallScreen from './StaffCallScreen.jsx'
import DoneScreen from './DoneScreen.jsx'
import { QUESTIONS } from '../../config/questions.js'
import { detectSafetyKeyword } from '../../config/safetyKeywords.js'
import { uploadAudio, getTranscript, processTranscript, createSession, isRemoteApiEnabled, isMockApiEnabled } from '../../services/api.js'

// v4 변경:
// - STAFF_CALL 단계 추가 (직원 도움 호출 후 안내 화면)
// - "다시 말할게요" 시 voice 화면 복귀 + 자동 녹음 재시작 (VoiceScreen이 useEffect로 자동 시작)
// - forceFlagAtQ prop 추가 — 시연 메뉴에서 특정 Q에서 flag 강제 트리거
// - 직원 도움 핸들러 모든 화면에 전달

const MOCK_PATIENT = {
  name: '김*자',
  honorific: '어르신',
  age: 74,
  gender: '여성',
  receiptId: 'A-0427'
}

const EMPTY_PATIENT = {
  name: '환자',
  honorific: '',
  age: '-',
  gender: '-',
  receiptId: '-'
}

const STEPS = {
  VISIT_TYPE: 'visit_type',
  Q_VOICE: 'q_voice',
  Q_VERIFY: 'q_verify',
  SAFETY_ALERT: 'safety_alert',
  STAFF_CALL: 'staff_call',
  DONE: 'done'
}


export default function PatientFlow({
  initialVisitType = null,
  forceFlagAtQ = null,
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
  const [session] = useState(() => sessionId ? { sessionId, startedAt: new Date().toISOString() } : createSession())
  const [prevStep, setPrevStep] = useState(null)  // 직원 도움 복귀용
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [safetyReturnMode, setSafetyReturnMode] = useState('verify')
  const [pendingSafetyResult, setPendingSafetyResult] = useState(null)
  const [safetyAcknowledged, setSafetyAcknowledged] = useState(false)
  const [isEndingIntake, setIsEndingIntake] = useState(false)
  const [intakeStopped, setIntakeStopped] = useState(false)

  const questions = visitType ? QUESTIONS[visitType] : []
  const currentQuestion = questions[questionIndex]
  const displayPatient = patient || (isMockApiEnabled() ? MOCK_PATIENT : EMPTY_PATIENT)


  // 직원 도움 호출 — 모든 화면에서 사용
  const handleStaffCall = useCallback(() => {
    onStaffCallRequest?.({
      sessionId: session.sessionId,
      questionId: currentQuestion?.id || null,
      step,
    })
    setPrevStep(step)
    setStep(STEPS.STAFF_CALL)
  }, [currentQuestion, onStaffCallRequest, session.sessionId, step])

  // 직원 도움 화면에서 복귀
  const handleStaffCallReturn = useCallback(() => {
    setStep(prevStep || STEPS.VISIT_TYPE)
    setPrevStep(null)
  }, [prevStep])


  const handleVisitTypeConfirm = useCallback((path) => {
    setVisitType(path)
    setStep(STEPS.Q_VOICE)
    setQuestionIndex(0)
  }, [])


  const handleVoiceFinish = useCallback(async (audioBlob) => {
    setIsTranscribing(true)
    try {
      const { transcribeJobName } = await uploadAudio(
        audioBlob,
        session.sessionId,
        currentQuestion.id,
        visitType
      )

      let jobName = transcribeJobName
      if (!isRemoteApiEnabled()) {
        jobName = `mock-${currentQuestion.id}_${visitType}`
        if (forceFlagAtQ && currentQuestion.id === forceFlagAtQ) {
          jobName = `mock-flag-trigger-${currentQuestion.id}`
        }
      }

      const { transcript: stt } = await getTranscript(jobName)
      if (!stt?.trim()) {
        throw new Error('empty_transcript')
      }
      setTranscript(stt)

      // 클라이언트 1차 위험 키워드 검사
      const safety = detectSafetyKeyword(stt)
      if (safety && safety.severity === 'high') {
        setSafetyKeyword(safety)
        setSafetyReturnMode('verify')
        setPendingSafetyResult(null)
        setSafetyAcknowledged(false)
        onStaffCallRequest?.({
          sessionId: session.sessionId,
          questionId: currentQuestion?.id || null,
          step: STEPS.SAFETY_ALERT,
          reason: 'safety_keyword',
        })
        setStep(STEPS.SAFETY_ALERT)
        return
      }

      setStep(STEPS.Q_VERIFY)
    } catch (err) {
      console.error('STT 실패:', err)
      setTranscript(err?.message === 'empty_transcript'
        ? '음성 인식 결과가 비어 있습니다. 다시 말씀해 주세요.'
        : '네트워크 오류 - 다시 말씀해 주세요')
      setStep(STEPS.Q_VERIFY)
    } finally {
      setIsTranscribing(false)
    }
  }, [session.sessionId, currentQuestion, visitType, forceFlagAtQ, onStaffCallRequest])


  const advanceWithConfirmedAnswer = useCallback((result) => {
    const confirmedAnswer = {
      id: currentQuestion.id,
      questionId: currentQuestion.id,
      transcript,
      question_type: currentQuestion.question_type,
      result
    }
    const nextAnswers = [...answers, confirmedAnswer]

    onTranscriptConfirmed?.(confirmedAnswer)
    setAnswers(nextAnswers)
    setTranscript('')
    setPendingSafetyResult(null)
    setSafetyKeyword(null)
    setSafetyAcknowledged(false)

    if (questionIndex >= 3) {
      onComplete?.({
        sessionId: session.sessionId,
        visitType,
        answers: nextAnswers,
      })
      setStep(STEPS.DONE)
    } else {
      setQuestionIndex(questionIndex + 1)
      setStep(STEPS.Q_VOICE)
    }
  }, [answers, currentQuestion, onComplete, onTranscriptConfirmed, questionIndex, session.sessionId, transcript, visitType])


  const handleVerifyConfirm = useCallback(async () => {
    try {
      const result = await processTranscript({
        sessionId: session.sessionId,
        questionId: currentQuestion.id,
        questionType: currentQuestion.question_type,
        visitType,
        transcript
      })

      if (result.safety_flag && result.safety_flag.severity === 'high' && !safetyAcknowledged) {
        setSafetyKeyword(result.safety_flag)
        setSafetyReturnMode('continue')
        setPendingSafetyResult(result)
        setStep(STEPS.SAFETY_ALERT)
        return
      }

      advanceWithConfirmedAnswer(result)
    } catch (err) {
      console.error('process 실패:', err)
      setTranscript('')
      if (questionIndex >= 3) {
        setStep(STEPS.DONE)
      } else {
        setQuestionIndex(questionIndex + 1)
        setStep(STEPS.Q_VOICE)
      }
    }
  }, [advanceWithConfirmedAnswer, currentQuestion, safetyAcknowledged, transcript, questionIndex])


  const handleVerifyRetry = useCallback(() => {
    setTranscript('')
    setSafetyAcknowledged(false)
    setPendingSafetyResult(null)
    setStep(STEPS.Q_VOICE)
    // VoiceScreen이 useEffect로 자동 녹음 재시작
  }, [])


  const handleSafetyContinue = useCallback(() => {
    setSafetyAcknowledged(true)
    if (safetyReturnMode === 'continue' && pendingSafetyResult) {
      advanceWithConfirmedAnswer(pendingSafetyResult)
      return
    }
    setStep(STEPS.Q_VERIFY)
  }, [advanceWithConfirmedAnswer, pendingSafetyResult, safetyReturnMode])


  const handleSafetyEnd = useCallback(async () => {
    setIsEndingIntake(true)
    let nextAnswers = answers
    try {
      let result = pendingSafetyResult
      if (!result && transcript?.trim() && currentQuestion) {
        result = await processTranscript({
          sessionId: session.sessionId,
          questionId: currentQuestion.id,
          questionType: currentQuestion.question_type,
          visitType,
          transcript
        })
      }
      if (result && currentQuestion && transcript?.trim()) {
        const confirmedAnswer = {
          id: currentQuestion.id,
          questionId: currentQuestion.id,
          transcript,
          question_type: currentQuestion.question_type,
          result
        }
        nextAnswers = [...answers, confirmedAnswer]
        onTranscriptConfirmed?.(confirmedAnswer)
        setAnswers(nextAnswers)
      }
    } catch (err) {
      console.error('문진 종료 처리 실패:', err)
    } finally {
      onComplete?.({
        sessionId: session.sessionId,
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
  }, [answers, currentQuestion, onComplete, onTranscriptConfirmed, pendingSafetyResult, session.sessionId, transcript, visitType])


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
            patient={displayPatient}
            visitType={visitType}
            question={currentQuestion}
            stepIndex={questionIndex + 1}
            isProcessing={isTranscribing}
            onFinish={handleVoiceFinish}
            onStaffCall={handleStaffCall}
          />
        )

      case STEPS.Q_VERIFY:
        return (
          <VerifyScreen
            patient={displayPatient}
            visitType={visitType}
            question={currentQuestion}
            transcript={transcript}
            stepIndex={questionIndex + 1}
            onConfirm={handleVerifyConfirm}
            onRetry={handleVerifyRetry}
            onStaffCall={handleStaffCall}
          />
        )

      case STEPS.SAFETY_ALERT:
        return (
          <SafetyAlertScreen
            patient={displayPatient}
            visitType={visitType}
            stepIndex={questionIndex + 1}
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

  return (
    <TabletFrame visitType={visitType} variant={frameVariant}>
      {renderScreen()}
    </TabletFrame>
  )
}
