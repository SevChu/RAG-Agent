import { describe, expect, it } from 'vitest'
import {
  defaultParameters,
  parameterError,
  RequestGate,
  SubmissionIdentity,
  terminal,
} from '../training'
describe('training contracts and request identity', () => {
  it('rejects unsafe numerical boundaries and allows backend-supported small rates', () => {
    expect(parameterError(defaultParameters(), 20)).toBe('')
    for (const parameters of [
      { ...defaultParameters(), rank: 1.5 },
      { ...defaultParameters(), dropout: 1 },
      { ...defaultParameters(), learning_rate: 0 },
      { ...defaultParameters(), seed: NaN },
    ])
      expect(parameterError(parameters, 20)).not.toBe('')
    expect(
      parameterError({ ...defaultParameters(), learning_rate: 1e-12, dropout: 0.99999999 }, 100),
    ).toBe('')
    expect(parameterError(defaultParameters(), 101)).not.toBe('')
  })
  it('reuses the same identity only while the submitted configuration is unchanged', () => {
    const identity = new SubmissionIdentity()
    const first = identity.for({ seed: 42 })
    expect(identity.for({ seed: 42 })).toBe(first)
    expect(identity.for({ seed: 43 })).not.toBe(first)
  })
  it('ignores late requests and all responses after disposal', () => {
    const gate = new RequestGate()
    const old = gate.next(),
      current = gate.next()
    expect(gate.current(old)).toBe(false)
    expect(gate.current(current)).toBe(true)
    gate.dispose()
    expect(gate.current(current)).toBe(false)
  })
  it('keeps cancelling active until a terminal result is observed', () => {
    expect(terminal('cancelling')).toBe(false)
    expect(terminal('interrupted')).toBe(true)
  })
})
