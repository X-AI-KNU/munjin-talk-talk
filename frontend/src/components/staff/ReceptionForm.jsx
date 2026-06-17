import { Link } from 'react-router-dom'
import { formatBirthDate, formatPhone, getBirthDateError } from './receptionUtils.js'

// 신분 확인과 문진 세션 생성을 담당하는 좌측 폼입니다.
export default function ReceptionForm({ form, created, updateField, onSubmit, onOpenTablet, submitError = '' }) {
  const birthDateError = form.birthDate ? getBirthDateError(form.birthDate) : ''
  const canSubmit = !birthDateError

  return (
    <section className="rp-panel">
      <div className="rp-panel-title">
        <h2>신분 확인</h2>
        <span>생년월일 확인 기반</span>
      </div>

      <form className="rp-form" onSubmit={onSubmit}>
        <label>
          <span>이름</span>
          <input value={form.fullName} onChange={(e) => updateField('fullName', e.target.value)} />
        </label>
        <label>
          <span>생년월일</span>
          <input
            type="text"
            inputMode="numeric"
            autoComplete="bday"
            maxLength={10}
            placeholder="YYYY-MM-DD"
            aria-invalid={Boolean(birthDateError)}
            value={form.birthDate}
            onChange={(e) => updateField('birthDate', formatBirthDate(e.target.value, form.birthDate))}
          />
          {birthDateError && <small className="rp-field-error">{birthDateError}</small>}
        </label>
        <label>
          <span>성별</span>
          <select value={form.gender} onChange={(e) => updateField('gender', e.target.value)}>
            <option>여성</option>
            <option>남성</option>
          </select>
        </label>
        <label>
          <span>접수번호</span>
          <input placeholder="비우면 자동 생성" value={form.receiptId} onChange={(e) => updateField('receiptId', e.target.value)} />
        </label>
        <label>
          <span>진료과</span>
          <input value={form.department} onChange={(e) => updateField('department', e.target.value)} />
        </label>
        <label>
          <span>담당 의사</span>
          <input value={form.doctor} onChange={(e) => updateField('doctor', e.target.value)} />
        </label>
        <label className="wide">
          <span>연락처</span>
          <input
            inputMode="numeric"
            placeholder="010-0000-0000"
            value={form.phone}
            onChange={(e) => updateField('phone', formatPhone(e.target.value))}
          />
        </label>

        <div className="rp-segment wide">
          <button
            type="button"
            className={form.visitType === 'initial' ? 'active' : ''}
            onClick={() => updateField('visitType', 'initial')}
          >
            초진
          </button>
          <button
            type="button"
            className={form.visitType === 'followup' ? 'active' : ''}
            onClick={() => updateField('visitType', 'followup')}
          >
            재진
          </button>
        </div>

        {submitError && <p className="rp-form-error wide">{submitError}</p>}

        <button className="rp-primary wide" type="submit" disabled={!canSubmit}>문진 세션 생성</button>
      </form>

      {created && (
        <div className="rp-created">
          <strong>{created.patient.name} 문진 준비 완료</strong>
          <p>태블릿에서 아래 환자용 URL을 열어 문진을 시작합니다.</p>
          <div className="rp-created-actions">
            <button onClick={() => onOpenTablet(created.sessionId)}>태블릿 화면 열기</button>
            <Link to={`/doctor/${created.sessionId}`}>원페이퍼 미리보기</Link>
          </div>
        </div>
      )}
    </section>
  )
}
