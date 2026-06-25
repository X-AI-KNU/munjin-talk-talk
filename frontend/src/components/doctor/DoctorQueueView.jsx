import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { getDoctorQueue } from '../../services/api.js'
import { sortDoctorQueue } from '../../services/queueOrder.js'
import { useDragScroll } from '../../hooks/useDragScroll.js'
import './DoctorQueueView.css'

// 의사 대기열 화면입니다.
// 환자 문진 완료 직후에는 analysis_pending으로 올라오고,
// 백그라운드 분석이 끝나면 waiting_doctor 상태로 전환됩니다.
const statusLabel = {
  waiting_tablet: '문진 대기',
  in_progress: '문진 진행 중',
  staff_help: '직원 도움 요청',
  analysis_pending: 'AI 분석 중',
  waiting_doctor: '의사 확인 대기',
  analysis_failed: '분석 재실행 필요',
  completed: '의사 확인 대기',
  needs_priority: '우선 확인 필요',
  reviewed: '응답·안내 완료',
}

const COMPLETED_QUEUE_STATUSES = new Set(['reviewed'])

export default function DoctorQueueView() {
  const [sessions, setSessions] = useState([])
  const [notice, setNotice] = useState(null)
  const [showCompleted, setShowCompleted] = useState(false)
  const boardRef = useDragScroll()
  const completedRef = useDragScroll()

  useEffect(() => {
    const refresh = async () => {
      try {
        setSessions(await getDoctorQueue())
      } catch (error) {
        console.error('doctor queue refresh failed:', error)
        setSessions([])
      }
    }
    refresh()
    const timer = setInterval(refresh, 4000)
    return () => clearInterval(timer)
  }, [])

  const sorted = useMemo(() => {
    return sortDoctorQueue(sessions)
  }, [sessions])

  const activeSessions = useMemo(
    () => sorted.filter((session) => !COMPLETED_QUEUE_STATUSES.has(session.status)),
    [sorted]
  )
  const completedSessions = useMemo(
    () => sorted.filter((session) => COMPLETED_QUEUE_STATUSES.has(session.status)),
    [sorted]
  )

  const renderSessionRow = (session, index, { completed = false } = {}) => {
    const isGenerating = session.status === 'analysis_pending'
      || ['pending', 'running'].includes(session.analysisStatus || session.analysis_status || '')
    const openGeneratingNotice = () => {
      setNotice({
        title: '원페이퍼 생성 중입니다',
        body: `${session.patient.name} 환자의 문진은 완료되었지만 AI 분석이 아직 끝나지 않았습니다. 잠시 후 새로고침해서 다시 확인해 주세요.`,
      })
    }

    return (
      <article
        key={session.sessionId}
        className={[
          'dq-row',
          !completed && session.risk === 'high' && 'risk',
          completed && 'completed-archive',
        ].filter(Boolean).join(' ')}
      >
        <div
          className={`dq-num ${completed ? 'dq-num-complete' : ''}`}
          title={completed ? '완료된 문진' : (session.queueNumber ? `접수 번호 ${session.queueNumber}` : '현재 대기 순서')}
        >
          {completed ? '✓' : index + 1}
        </div>
        <div className="dq-main">
          <div className="dq-name">
            <strong>{session.patient.name}</strong>
            <span>{session.visitType === 'initial' ? '초진' : '재진'}</span>
            {!completed && session.risk === 'high' && <mark>우선</mark>}
          </div>
          <p>
            {session.patient.age}세 {session.patient.gender} · {session.patient.department} · #{session.patient.receiptId}
          </p>
        </div>
        <span className={`dq-status ${session.status}`}>{statusLabel[session.status] || session.status}</span>
        <div className="dq-actions">
          {isGenerating ? (
            <>
              <button type="button" onClick={openGeneratingNotice}>원페이퍼</button>
              <button type="button" onClick={openGeneratingNotice}>안내문</button>
            </>
          ) : (
            <>
              <Link to={`/doctor/${session.sessionId}`}>원페이퍼</Link>
              <Link to={`/guide/${session.sessionId}`}>안내문</Link>
            </>
          )}
        </div>
      </article>
    )
  }

  return (
    <div className="doctor-queue-page">
      <header className="dq-header">
        <div>
          <p>의사 대기열</p>
          <h1>오늘 문진 환자 대기열</h1>
        </div>
        <Link to="/staff">접수 화면</Link>
      </header>

      <div className="dq-section-title">
        <span>진료 대기</span>
        <small>{activeSessions.length}명</small>
      </div>
      <div className="dq-board drag-scroll-region" ref={boardRef}>
        {activeSessions.length ? (
          activeSessions.map((session, index) => renderSessionRow(session, index))
        ) : (
          <div className="dq-empty">현재 진료 대기 중인 문진이 없습니다.</div>
        )}
      </div>

      {completedSessions.length > 0 && (
        <section className="dq-completed">
          <button
            type="button"
            className="dq-completed-toggle"
            onClick={() => setShowCompleted((prev) => !prev)}
            aria-expanded={showCompleted}
          >
            <span>완료된 문진 {completedSessions.length}건 {showCompleted ? '닫기' : '보기'}</span>
            <b aria-hidden="true">{showCompleted ? '▲' : '▼'}</b>
          </button>
          {showCompleted && (
            <div className="dq-completed-list drag-scroll-region" ref={completedRef}>
              {completedSessions.map((session) => renderSessionRow(session, 0, { completed: true }))}
            </div>
          )}
        </section>
      )}

      {notice && (
        <div className="dq-notice-backdrop" role="presentation" onClick={() => setNotice(null)}>
          <div className="dq-notice-modal" role="dialog" aria-modal="true" aria-labelledby="dq-notice-title" onClick={(event) => event.stopPropagation()}>
            <h2 id="dq-notice-title">{notice.title}</h2>
            <p>{notice.body}</p>
            <button type="button" onClick={() => setNotice(null)}>확인</button>
          </div>
        </div>
      )}
    </div>
  )
}
