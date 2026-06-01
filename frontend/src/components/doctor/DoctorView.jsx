import { useState, useEffect, useMemo } from 'react'
import { useParams } from 'react-router-dom'
import {
  getOnePager, submitDoctorResponse
} from '../../services/api.js'
import DoctorOnePager from './DoctorOnePager.jsx'
import DoctorAgendaPanel from './DoctorAgendaPanel.jsx'
import './DoctorView.css'

// UI 개선안 2 적용
// ────────────────────────────────────────
// 좌측 (visit_type 분기):
//   - 카드 1: 증상 / 변화 추적 카드 (초진/재진별 다른 형태)
//   - 카드 2: 의료진 확인 항목 (초진/재진별 추가 항목)
//   - 카드 3: 기록용 문장 (EMR 복사)
//
// 우측 (visit_type 무관 공통):
//   - 환자 질문 + 답변 입력 인라인 (agenda + textarea per question)
//   - 환자 발화 원문 카드 상시 표시 (Q4 누락 방지 4중 묘수 ④)
//
// 상단 가로 띠 (전체 폭):
//   - 위험 플래그 amber 배지 (재진 객혈 시연)
//   - 환자 정보 (이름·나이·진료과·visit_type)

export default function DoctorView() {
  const { sessionId } = useParams()
  const [sessionData, setSessionData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitStatus, setSubmitStatus] = useState(null)

  useEffect(() => {
    setLoading(true)
    getOnePager(sessionId).then(data => {
      setSessionData(data)
      setLoading(false)
    })
  }, [sessionId])

  const handleSubmitResponse = async ({ answers, additionalNotes }) => {
    if (!sessionId) {
      setSubmitStatus('error')
      return
    }
    setSubmitStatus('submitting')
    try {
      const result = await submitDoctorResponse({
        sessionId,
        reviewerId: 'DR-DEMO',
        answers,
        additionalNotes
      })
      if (result.validator_passed !== false) {
        setSubmitStatus('success')
      } else {
        setSubmitStatus('partial_fallback')
      }
    } catch (err) {
      console.error('의사 답변 전송 실패:', err)
      setSubmitStatus('error')
    }
  }

  if (loading) {
    return <div className="doctor-loading">원페이퍼를 불러오는 중...</div>
  }

  return (
    <div className="doctor-view-v3">
      <DoctorOnePager
        sessionId={sessionId}
        sessionData={sessionData}
        // Agenda + 답변 입력은 별도 우측 패널로 분리
        renderAgenda={false}
        // 우측 영역에 답변 입력 함께 표시
        sidePanel={
          <DoctorAgendaPanel
            sessionData={sessionData}
            submitStatus={submitStatus}
            onSubmit={handleSubmitResponse}
          />
        }
      />
    </div>
  )
}
