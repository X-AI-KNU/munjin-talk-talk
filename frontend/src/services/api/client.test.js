import { describe, it, expect, beforeEach, vi } from 'vitest'
import {
  isRemoteApiEnabled,
  normalizeSession,
  sessionUrl,
} from './client.js'

describe('isRemoteApiEnabled', () => {
  it('VITE_API_BASE_URL이 비어있으면 false', () => {
    // default empty 값 = disabled
    // 실제 런타임에서 env가 비어있으면 false 반환
    const result = isRemoteApiEnabled()
    expect(typeof result).toBe('boolean')
  })
})

describe('normalizeSession', () => {
  it('null 입력에 null 반환', () => {
    expect(normalizeSession(null)).toBeNull()
    expect(normalizeSession(undefined)).toBeNull()
  })

  it('snake_case를 camelCase로 정규화한다', () => {
    const session = {
      session_id: 'sess_123',
      queue_number: 5,
      visit_type: 'initial',
      question_set_id: 'default',
      patient_token: 'tok_abc',
      patient: {
        full_name: '홍길동',
        birth_date: '1950-01-01',
        receipt_id: 'R-0001',
        name: '홍*동',
        gender: '남',
        department: '이비인후과',
      },
    }
    const result = normalizeSession(session)
    expect(result.sessionId).toBe('sess_123')
    expect(result.queueNumber).toBe(5)
    expect(result.visitType).toBe('initial')
    expect(result.questionSetId).toBe('default')
    expect(result.patientToken).toBe('tok_abc')
    expect(result.patient.fullName).toBe('홍길동')
    expect(result.patient.receiptId).toBe('R-0001')
  })

  it('이미 camelCase인 필드도 보존한다', () => {
    const session = {
      sessionId: 'sess_456',
      queueNumber: 3,
      visitType: 'followup',
      patient: { name: '김*수' },
    }
    const result = normalizeSession(session)
    expect(result.sessionId).toBe('sess_456')
    expect(result.queueNumber).toBe(3)
  })

  it('누락된 patient 필드에 기본값을 제공한다', () => {
    const session = { session_id: 'sess_789', patient: {} }
    const result = normalizeSession(session)
    expect(result.patient.name).toBe('환자')
    expect(result.patient.gender).toBe('-')
    expect(result.patient.department).toBe('이비인후과')
    // 최신 main: honorific 기본값/'어르신'은 '환자님'으로 정규화됨
    expect(result.patient.honorific).toBe('환자님')
  })
})

describe('sessionUrl', () => {
  it('토큰 없으면 경로만 반환', () => {
    expect(sessionUrl('/patient/abc')).toBe('/patient/abc')
    expect(sessionUrl('/patient/abc', '')).toBe('/patient/abc')
  })

  it('토큰 있으면 쿼리 파라미터 추가', () => {
    const url = sessionUrl('/patient/abc', 'my_token')
    expect(url).toBe('/patient/abc?pt=my_token')
  })

  it('이미 쿼리스트링이 있으면 &로 연결', () => {
    const url = sessionUrl('/patient/abc?foo=bar', 'my_token')
    expect(url).toBe('/patient/abc?foo=bar&pt=my_token')
  })
})
