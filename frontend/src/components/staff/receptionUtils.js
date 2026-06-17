// 접수 화면에서 공유하는 기본값과 표시 규칙입니다.
// 배포용 화면에서는 실제 사람처럼 보이는 이름/생년월일 샘플을 기본값으로 두지 않습니다.

export const INITIAL_RECEPTION_FORM = {
  fullName: '',
  birthDate: '',
  gender: '여성',
  receiptId: '',
  department: '이비인후과',
  doctor: '이민우',
  phone: '',
  visitType: 'initial',
}

export const SESSION_STATUS_LABEL = {
  waiting_tablet: '문진 대기',
  in_progress: '문진 진행중',
  staff_help: '직원 도움 요청',
  consent_rejected: '동의 거부',
  completed: '의사 답변 대기',
  needs_priority: '우선 확인 필요',
  reviewed: '답변·안내 완료',
}

export const MANUAL_INPUT_STATUSES = new Set([
  'staff_help',
  'consent_rejected',
  'needs_priority',
  'in_progress',
  'waiting_tablet',
])

// 생년월일은 브라우저 date input에 맡기면 일부 환경에서 5자리 이상 연도가 입력될 수 있습니다.
// 접수처에서는 숫자 8자리만 받아 YYYY-MM-DD로 고정하고, 명백히 불가능한 월/일은 입력 중에도 막습니다.
export function formatBirthDate(value, previousValue = '') {
  const digits = String(value || '').replace(/\D/g, '').slice(0, 8)
  const formatted = formatBirthDateDigits(digits)
  if (!isBirthDateDraftAllowed(formatted)) {
    return String(previousValue || '').slice(0, 10)
  }
  return formatted
}

function formatBirthDateDigits(digits) {
  if (digits.length <= 4) return digits
  if (digits.length <= 6) return `${digits.slice(0, 4)}-${digits.slice(4)}`
  return `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6)}`
}

function isBirthDateDraftAllowed(value) {
  const digits = String(value || '').replace(/\D/g, '')
  if (!digits) return true

  if (digits.length >= 4) {
    const year = Number(digits.slice(0, 4))
    const currentYear = new Date().getFullYear()
    if (year < 1900 || year > currentYear) return false
  }

  if (digits.length >= 5 && !['0', '1'].includes(digits[4])) return false
  if (digits.length >= 6) {
    const month = Number(digits.slice(4, 6))
    if (month < 1 || month > 12) return false
  }

  if (digits.length >= 7 && Number(digits[6]) > 3) return false
  if (digits.length >= 8) {
    const year = Number(digits.slice(0, 4))
    const month = Number(digits.slice(4, 6))
    const day = Number(digits.slice(6, 8))
    const date = new Date(year, month - 1, day)
    const today = new Date()
    if (
      date.getFullYear() !== year
      || date.getMonth() !== month - 1
      || date.getDate() !== day
      || date > today
    ) {
      return false
    }
    let age = today.getFullYear() - year
    if ((today.getMonth() + 1 < month) || (today.getMonth() + 1 === month && today.getDate() < day)) {
      age -= 1
    }
    if (age > 130) return false
  }
  return true
}

export function getBirthDateError(value) {
  const formatted = String(value || '').trim()
  const digits = formatted.replace(/\D/g, '')
  if (!digits) return '생년월일을 입력해 주세요.'
  if (digits.length !== 8 || !/^\d{4}-\d{2}-\d{2}$/.test(formatted)) {
    return '생년월일은 8자리로 입력해 주세요. 예: 1950-09-17'
  }

  const year = Number(digits.slice(0, 4))
  const month = Number(digits.slice(4, 6))
  const day = Number(digits.slice(6, 8))
  const date = new Date(year, month - 1, day)
  const today = new Date()
  const yearNow = today.getFullYear()

  if (year < 1900 || year > yearNow) {
    return '연도는 1900년부터 올해까지만 입력할 수 있습니다.'
  }
  if (
    date.getFullYear() !== year
    || date.getMonth() !== month - 1
    || date.getDate() !== day
  ) {
    return '존재하지 않는 날짜입니다. 다시 확인해 주세요.'
  }
  if (date > today) {
    return '오늘 이후 날짜는 생년월일로 사용할 수 없습니다.'
  }

  let age = yearNow - year
  if ((today.getMonth() + 1 < month) || (today.getMonth() + 1 === month && today.getDate() < day)) {
    age -= 1
  }
  if (age > 130) {
    return '나이가 130세를 넘습니다. 생년월일을 다시 확인해 주세요.'
  }
  return ''
}

export function formatPhone(value) {
  const digits = String(value || '').replace(/\D/g, '').slice(0, 11)
  if (digits.length <= 3) return digits
  if (digits.length <= 7) return `${digits.slice(0, 3)}-${digits.slice(3)}`
  return `${digits.slice(0, 3)}-${digits.slice(3, 7)}-${digits.slice(7)}`
}
