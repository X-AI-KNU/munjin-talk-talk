import ScreenHeader from '../tablet/ScreenHeader.jsx'

// 문진 종료 화면입니다.
// 일반 완료와 직원 인계 종료를 구분하고, 환자에게 다음 상태를 알려줍니다.

// v4 변경:
// - 모든 글자 크기 키움

const CheckCircleIcon = () => (
  <svg viewBox="0 0 64 64" fill="none">
    <circle cx="32" cy="32" r="30" fill="#2563EB"/>
    <path d="M20 33l8 8 16-18" stroke="white" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)


export default function DoneScreen({
  patient,
  visitType,
  stopped = false,
  onExitToQueue,
}) {
  const statusText = stopped ? '직원 확인 대기' : '의료진 확인 대기'

  return (
    <>
      <ScreenHeader
        patientName={`${patient.name} ${patient.honorific}`}
        subtitle={stopped ? '직원 확인으로 전환' : `${visitType === 'initial' ? '초진' : '재진'} 문진 완료`}
        visitType={visitType}
        currentStep={5}
      />

      <div className="screen-body done-body done-body-v4">
        <div className="done-check-icon-large">
          <CheckCircleIcon />
        </div>

        <h2 className="done-title done-title-large">
          {stopped ? <>직원이 이어서<br/>도와드릴게요</> : <>문진이<br/>모두 끝났어요</>}
        </h2>

        <p className="done-message done-message-large">
          {stopped ? (
            <>
              입력한 내용은 직원과 의료진이 확인합니다.<br/>
              잠시만 자리에서 기다려 주세요.
            </>
          ) : (
            <>
              선생님이 어르신 말씀을 미리 보고 계세요.<br/>
              잠시만 자리에서 기다려 주세요.
            </>
          )}
        </p>

        <div className="queue-card queue-card-v4">
          <span className="queue-label queue-label-large">현재 상태</span>
          <span className="queue-number queue-number-large done-status-text">
            {statusText}
          </span>
        </div>

      </div>

      {onExitToQueue && (
        <footer className="screen-footer done-footer-v4">
          <button
            type="button"
            className="done-return-queue-button"
            onClick={onExitToQueue}
          >
            다음 환자 선택 화면으로 돌아가기
          </button>
        </footer>
      )}
    </>
  )
}
