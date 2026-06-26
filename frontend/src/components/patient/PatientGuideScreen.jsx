import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { getPatientGuide } from '../../services/api.js'
import logoUrl from '../../assets/munjin-logo.svg'
import './PatientGuideScreen.css'

// 진료 후 환자에게 보여주거나 출력할 안내문 화면입니다.
// LLM이 의미를 보존해 존댓말로 정리한 답변과 의사가 직접 적은 강조사항을 함께 보여줍니다.

// 환자 안내 화면 (Phase B - 진료 후 태블릿).
// 의사 답변을 LLM이 어르신 대상 존댓말 문장으로 변환한 결과를 큰 글씨로 표시.
// TTS 음성 안내, 보호자 공유(SMS), 종이 출력 옵션 제공.

function normalizeGuideItems(guide) {
  const baseItems = guide?.patient_guide?.items || []
  const doctorNote = (guide?.doctor_additional_notes || '').trim()
  const patientItems = baseItems.filter((item) =>
    !/의사 안내|선생님|강조사항|진료 안내/.test(item.question || '')
  )
  if (!doctorNote) return patientItems
  return [
    ...patientItems,
    {
      question: '선생님 강조사항',
      answer_simple: [doctorNote],
      tts_emphasis_words: [],
      is_doctor_instruction: true,
    },
  ]
}

// 의사 강조사항은 일반 환자 질문 답변과 다른 스타일로 보이게 라벨을 통일합니다.
function guideQuestionLabel(item) {
  if (item.is_doctor_instruction || /의사 안내|선생님|강조사항|진료 안내/.test(item.question || '')) {
    return '선생님 강조사항'
  }
  return item.question
}

function formatGuideDate(value) {
  const date = value ? new Date(value) : new Date()
  if (Number.isNaN(date.getTime())) {
    return new Date().toLocaleDateString('ko-KR')
  }
  return date.toLocaleDateString('ko-KR')
}

export default function PatientGuideScreen() {
  const { sessionId } = useParams()
  const [guide, setGuide] = useState(null)
  const [loading, setLoading] = useState(Boolean(sessionId))
  const [playingIdx, setPlayingIdx] = useState(null)  // 현재 재생 중 인덱스

  // doctor-response 저장 후 생성된 안내문 JSON을 조회합니다.
  useEffect(() => {
    let alive = true
    if (!sessionId) {
      setGuide(null)
      setLoading(false)
      return () => {
        alive = false
      }
    }
    setLoading(true)
    getPatientGuide(sessionId).then(data => {
      if (!alive) return
      if (data) setGuide(data)
      else setGuide(null)
    }).finally(() => {
      if (alive) setLoading(false)
    })
    return () => {
      alive = false
    }
  }, [sessionId])

  // 컴포넌트 언마운트 시 정지
  useEffect(() => {
    return () => {
      if ('speechSynthesis' in window) speechSynthesis.cancel()
    }
  }, [])

  // v4: 토글 동작 — 같은 항목 다시 누르면 멈춤
  // 브라우저 내장 speechSynthesis로 안내문을 큰 글씨 화면에서 바로 읽어줍니다.
  const handlePlayToggle = (idx) => {
    if (!('speechSynthesis' in window)) {
      alert('이 브라우저는 음성 안내를 지원하지 않습니다.')
      return
    }

    // 이미 재생 중 → 정지
    if (playingIdx === idx) {
      speechSynthesis.cancel()
      setPlayingIdx(null)
      return
    }

    // 다른 항목 재생 중이면 먼저 정지
    speechSynthesis.cancel()

    const item = items[idx]
    const fullText = item.answer_simple.join('. ')
    const utter = new SpeechSynthesisUtterance(fullText)
    utter.lang = 'ko-KR'
    utter.rate = 0.85
    utter.pitch = 1.0

    // 재생 종료 시 상태 초기화
    utter.onend = () => setPlayingIdx(null)
    utter.onerror = () => setPlayingIdx(null)

    setPlayingIdx(idx)
    speechSynthesis.speak(utter)
  }

  const handleShareSMS = async () => {
    const shareUrl = window.location.href
    const shareTitle = guide?.patient_name_masked
      ? `${guide.patient_name_masked} 어르신 안내문`
      : '문진톡톡 환자 안내문'
    if (navigator.share) {
      await navigator.share({ title: shareTitle, url: shareUrl })
      return
    }
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(shareUrl)
      alert('안내문 링크를 복사했습니다. 보호자에게 붙여넣어 공유해 주세요.')
      return
    }
    alert('이 브라우저에서는 공유 기능을 지원하지 않습니다. 종이 출력 기능을 이용해 주세요.')
  }

  // 인쇄 버튼은 별도 PDF 생성 없이 브라우저 print CSS를 사용합니다.
  const handlePrint = () => {
    const cleanupPrintMode = () => {
      document.body.classList.remove('guide-printing')
      window.removeEventListener('afterprint', cleanupPrintMode)
    }

    document.body.classList.add('guide-printing')
    window.addEventListener('afterprint', cleanupPrintMode)

    // 브라우저가 print 전용 클래스를 적용할 시간을 한 프레임 확보합니다.
    window.requestAnimationFrame(() => {
      window.print()
      window.setTimeout(cleanupPrintMode, 500)
    })
  }

  const items = guide ? normalizeGuideItems(guide) : []
  const generatedAt = formatGuideDate(guide?.patient_guide?.generated_at)
  const emptyMessage = loading
    ? '안내문을 불러오는 중입니다.'
    : sessionId
      ? '안내문이 아직 준비되지 않았습니다.\n의료진 답변 저장 후 다시 확인해 주세요.'
      : '선택된 문진 세션이 없습니다.\n직원 접수에서 문진 세션을 생성한 뒤 안내문을 확인해 주세요.'

  return (
    <div className="guide-print-page">
      <div className="patient-guide-screen">
        <header className="pg-header pg-print-header">
          <div>
            <p className="pg-kicker">진료 후 안내문</p>
            <h1>{guide?.patient_name_masked ? `${guide.patient_name_masked} 어르신 안내문` : '환자 안내문'}</h1>
            <p className="pg-sub">오늘 진료에서 안내받은 내용을 집에서도 다시 확인하실 수 있게 정리했습니다</p>
          </div>
          <div className="pg-print-meta">
            <img className="pg-logo-svg" src={logoUrl} alt="" aria-hidden="true" />
            <div className="pg-meta-text">
              <span>문진톡톡</span>
              <small>{generatedAt}</small>
            </div>
          </div>
        </header>

        <div className="pg-items">
          {items.length === 0 && (
            <div className="pg-empty">
              {emptyMessage.split('\n').map((line) => (
                <span key={line}>
                  {line}
                  <br />
                </span>
              ))}
            </div>
          )}

          {items.map((item, idx) => (
            <article
              key={idx}
              className={`pg-card ${guideQuestionLabel(item) === '선생님 강조사항' ? 'pg-card-instruction' : ''} ${playingIdx === idx ? 'pg-card-active' : ''}`}
            >
              <div className="pg-question-tag">{guideQuestionLabel(item)}</div>

              <div className="pg-sentences">
                {item.answer_simple.map((sentence, sidx) => (
                  <p key={sidx} className="pg-sentence">
                    {sentence}
                  </p>
                ))}
              </div>

              <button
                className={`pg-tts-btn ${playingIdx === idx ? 'playing' : ''}`}
                onClick={() => handlePlayToggle(idx)}
              >
                <span className="pg-tts-icon">{playingIdx === idx ? '⏸' : '🔊'}</span>
                {playingIdx === idx ? '재생 멈추기' : '말로 재생하기'}
              </button>
            </article>
          ))}
        </div>

        {items.length > 0 && (
          <div className="pg-action-bar no-print">
            <button className="pg-action-btn pg-action-share" onClick={handleShareSMS}>
              <span>💬</span> 가족에게 보내기
            </button>
            <button className="pg-action-btn pg-action-print" onClick={handlePrint}>
              <span>📄</span> 종이로 출력
            </button>
          </div>
        )}

        <footer className="pg-footer">
          궁금한 점이 더 있으시면 접수처 직원에게 말씀해 주세요.
        </footer>
      </div>
    </div>
  )
}
