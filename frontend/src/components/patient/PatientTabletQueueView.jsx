import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import logoUrl from '../../assets/munjin-logo.svg'
import { getDoctorQueue } from '../../services/api.js'
import './PatientKioskView.css'

const TABLET_QUEUE_STATUSES = new Set([
  'waiting_tablet',
  'in_progress',
  'staff_help',
  'consent_rejected',
])

const TABLET_STATUS_LABEL = {
  waiting_tablet: '문진 대기',
  in_progress: '문진 진행 중',
  staff_help: '직원 도움 요청',
  consent_rejected: '수기 문진 필요',
}

function actionLabel(status) {
  if (status === 'in_progress') return '문진 이어하기'
  if (status === 'staff_help') return '도움 화면 열기'
  if (status === 'consent_rejected') return '수기 문진 확인'
  return '문진 시작'
}

// 여러 태블릿이 같은 주소(/patient)에 접속해도 오늘 문진 대기 환자를 고를 수 있는 화면입니다.
// 실제 문진은 환자별 URL(/patient/:sessionId)로 들어가고, 이 화면은 태블릿용 대기열 역할만 합니다.
export default function PatientTabletQueueView() {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const loadSessions = useCallback(async () => {
    try {
      const next = await getDoctorQueue()
      setSessions(next)
      setError('')
    } catch (err) {
      console.error('patient tablet queue refresh failed:', err)
      setError('문진 대기열을 불러오지 못했습니다. 네트워크 상태를 확인해 주세요.')
      setSessions([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadSessions()
    const timer = setInterval(loadSessions, 5000)
    return () => clearInterval(timer)
  }, [loadSessions])

  const waitingSessions = useMemo(
    () => sessions.filter((session) => TABLET_QUEUE_STATUSES.has(session.status)),
    [sessions]
  )

  return (
    <section className="tablet-queue-page">
      <header className="tablet-queue-header">
        <div className="tablet-queue-brand">
          <img src={logoUrl} alt="" aria-hidden="true" />
          <div>
            <p>환자 태블릿</p>
            <h1>문진 대기열</h1>
          </div>
        </div>
        <button type="button" onClick={loadSessions}>새로고침</button>
      </header>

      <div className="tablet-queue-panel">
        <div className="tablet-queue-title">
          <h2>문진할 환자를 선택해 주세요</h2>
          <span>{waitingSessions.length}명 대기</span>
        </div>

        {error && <p className="tablet-queue-error">{error}</p>}
        {loading && <p className="tablet-queue-empty">문진 대기열을 불러오는 중입니다.</p>}

        {!loading && !waitingSessions.length && (
          <div className="tablet-queue-empty">
            <strong>현재 문진 대기 환자가 없습니다</strong>
            <p>접수 데스크에서 문진 세션을 생성하면 이곳에 표시됩니다.</p>
            <Link to="/staff">접수 화면으로 이동</Link>
          </div>
        )}

        <div className="tablet-queue-list">
          {waitingSessions.map((session) => (
            <article key={session.sessionId} className={`tablet-queue-card ${session.status}`}>
              <div>
                <span className="tablet-queue-badge">
                  {TABLET_STATUS_LABEL[session.status] || session.status}
                </span>
                <h3>{session.patient.name} 어르신</h3>
                <p>
                  #{session.patient.receiptId} · {session.patient.age}세 {session.patient.gender}
                  {' · '}
                  {session.visitType === 'followup' ? '재진' : '초진'}
                </p>
              </div>
              <Link to={`/patient/${encodeURIComponent(session.sessionId)}`}>
                {actionLabel(session.status)}
              </Link>
            </article>
          ))}
        </div>
      </div>
    </section>
  )
}
