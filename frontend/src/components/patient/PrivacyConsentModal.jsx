import { useState } from 'react'

export const PRIVACY_CONSENT_VERSION = 'munjin-privacy-consent-2026-06-07'

export const PRIVACY_NOTICE_ITEMS = [
  '환자 확인 및 문진 세션 생성',
  '음성 문진의 실시간 텍스트 변환',
  '의료진 확인용 원페이퍼 및 환자 안내문 생성',
  '문진 중 위험 표현 감지와 직원 호출 처리',
]

export const SENSITIVE_NOTICE_ITEMS = [
  '증상, 경과, 복약, 병력 등 건강 관련 문진 답변',
  '환자가 의사에게 묻고 싶은 질문과 진료 후 안내 내용',
]

export const RETENTION_NOTICE = 'MVP 시연 및 검증 목적의 세션 데이터는 최대 3일 보관 후 삭제하는 정책을 적용합니다.'

// 환자 태블릿 진입 전 보여주는 앱형 동의 팝업입니다.
// 핵심 문구는 짧고 크게, 법정 고지에 가까운 상세 내용은 [전문보기] 안에 둡니다.
export default function PrivacyConsentModal({
  patientName = '환자',
  isSaving = false,
  error = '',
  rejected = false,
  onAccept,
  onReject,
  onStaffHelp,
}) {
  const [detailOpen, setDetailOpen] = useState(false)
  const [privacyChecked, setPrivacyChecked] = useState(false)
  const [sensitiveChecked, setSensitiveChecked] = useState(false)
  const canAccept = privacyChecked && sensitiveChecked && !isSaving

  return (
    <div className="privacy-consent-backdrop" role="presentation">
      <section className="privacy-consent-modal" role="dialog" aria-modal="true" aria-labelledby="privacy-consent-title">
        <h2 id="privacy-consent-title">서비스 이용 동의</h2>
        <p className="privacy-consent-lead">
          {patientName}님의 음성 문진 내용을 서비스 이용에 사용합니다.
        </p>
        <p className="privacy-consent-note">
          음성 원본 파일은 저장하지 않고, 확인된 문진 텍스트만 임시로 기록합니다.
          동의하지 않아도 직원이 수기 문진으로 도와드릴 수 있습니다.
        </p>

        <button
          type="button"
          className="privacy-consent-detail-toggle"
          onClick={() => setDetailOpen((next) => !next)}
          aria-expanded={detailOpen}
        >
          {detailOpen ? '전문 접기' : '[전문보기]'}
        </button>

        {detailOpen && (
          <div className="privacy-consent-detail">
            <section>
              <h3>개인정보 수집·이용 목적</h3>
              <ul>
                {PRIVACY_NOTICE_ITEMS.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </section>
            <section>
              <h3>수집 항목</h3>
              <p>
                이름 또는 표시명, 생년월일/연령, 성별, 접수번호, 진료과, 문진 답변 텍스트,
                실시간 전사 결과, 의료진 답변 및 안내문 내용
              </p>
            </section>
            <section>
              <h3>건강 관련 문진 정보 처리</h3>
              <p>
                문진 답변에는 증상, 복약, 병력 등 건강에 관한 정보가 포함될 수 있습니다.
                해당 정보는 의료진 확인과 안내문 생성을 위해서만 처리합니다.
              </p>
              <ul>
                {SENSITIVE_NOTICE_ITEMS.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </section>
            <section>
              <h3>보유 및 삭제</h3>
              <p>{RETENTION_NOTICE}</p>
              <p>동의를 거부할 권리가 있으며, 거부 시 음성 문진 대신 직원 수기 문진을 이용할 수 있습니다.</p>
            </section>
          </div>
        )}

        <div className="privacy-consent-checks">
          <label className="privacy-consent-check">
            <input
              type="checkbox"
              checked={privacyChecked}
              onChange={(event) => setPrivacyChecked(event.target.checked)}
            />
            <span>개인정보 수집·이용 안내를 확인했고 동의합니다.</span>
          </label>
          <label className="privacy-consent-check">
            <input
              type="checkbox"
              checked={sensitiveChecked}
              onChange={(event) => setSensitiveChecked(event.target.checked)}
            />
            <span>증상·복약·병력 등 건강 관련 문진 정보 처리에 동의합니다.</span>
          </label>
        </div>

        {error && <p className="privacy-consent-error">{error}</p>}
        {rejected && (
          <p className="privacy-consent-rejected">
            음성 문진은 시작하지 않습니다. 접수 직원에게 수기 문진을 요청해 주세요.
          </p>
        )}

        <div className="privacy-consent-actions">
          <button type="button" className="privacy-consent-secondary" onClick={onReject} disabled={isSaving}>
            동의하지 않음
          </button>
          <button type="button" className="privacy-consent-help" onClick={onStaffHelp} disabled={isSaving}>
            직원 도움
          </button>
          <button type="button" className="privacy-consent-primary" onClick={onAccept} disabled={!canAccept}>
            {isSaving ? '저장 중' : '동의'}
          </button>
        </div>
      </section>
    </div>
  )
}
