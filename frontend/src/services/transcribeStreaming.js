import { API_BASE_URL, apiHeaders, ensureApiConfigured, sleep } from './api/client.js'

const encoder = new TextEncoder()
const decoder = new TextDecoder()
const CRC32_TABLE = makeCrc32Table()

export async function openTranscribeStream({
  sessionId,
  questionId,
  visitType,
  onTranscript,
  onStatus,
  onError,
  onAudioActivity,
}) {
  ensureApiConfigured()

  const AudioContextClass = window.AudioContext || window.webkitAudioContext
  const audioContext = new AudioContextClass({ sampleRate: 16000 })
  await resumeAudioContext(audioContext)
  const sampleRate = audioContext.sampleRate

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      sampleRate,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  })
  const { stream_url: streamUrl } = await getTranscribeStreamUrl({
    sessionId,
    questionId,
    visitType,
    sampleRate,
  })

  const socket = new WebSocket(streamUrl)
  socket.binaryType = 'arraybuffer'

  const source = audioContext.createMediaStreamSource(stream)
  const silentGain = audioContext.createGain()
  // 완전한 0 gain은 일부 브라우저에서 오디오 그래프가 쉬어버릴 수 있어
  // 들리지 않는 수준의 아주 작은 gain으로 그래프를 계속 당겨옵니다.
  silentGain.gain.value = 0.00001

  const finalSegments = []
  let latestText = ''
  let started = false
  let stopped = false
  let framesSent = 0
  let bytesSent = 0
  const noAudioTimer = window.setTimeout(async () => {
    if (stopped || framesSent > 0) return
    await resumeAudioContext(audioContext)
    if (audioContext.state === 'suspended') {
      onError?.(new Error('audio_context_suspended'))
    } else {
      onError?.(new Error('audio_stream_no_frames'))
    }
  }, 2500)

  socket.onmessage = async (event) => {
    try {
      const buffer = event.data instanceof Blob ? await event.data.arrayBuffer() : event.data
      const message = decodeEventMessage(buffer)
      const payloadText = decoder.decode(message.payload)
      const payload = payloadText ? JSON.parse(payloadText) : {}
      if (message.headers[':message-type'] === 'exception') {
        onError?.(new Error(payload.Message || message.headers[':exception-type'] || 'transcribe_stream_exception'))
        return
      }
      const results = payload?.Transcript?.Results || []
      for (const result of results) {
        const text = result?.Alternatives?.[0]?.Transcript || ''
        if (!text) continue
        if (result.IsPartial) {
          latestText = [...finalSegments, text].join(' ').trim()
          onTranscript?.(latestText, { partial: true })
        } else {
          finalSegments.push(text)
          latestText = finalSegments.join(' ').trim()
          onTranscript?.(latestText, { partial: false })
        }
      }
    } catch (error) {
      onError?.(error)
    }
  }

  socket.onerror = () => {
    onError?.(new Error('transcribe_stream_socket_error'))
  }

  await new Promise((resolve, reject) => {
    socket.onopen = () => resolve()
    socket.onerror = () => reject(new Error('transcribe_stream_open_failed'))
  })
  socket.onerror = () => {
    onError?.(new Error('transcribe_stream_socket_error'))
  }
  socket.onclose = () => {
    if (!stopped) onStatus?.('stopped')
  }

  const audioPipeline = await createAudioCapturePipeline({
    audioContext,
    source,
    silentGain,
    onChunk({ pcm, rms, timestamp }) {
      if (!started || stopped || socket.readyState !== WebSocket.OPEN) return
      onAudioActivity?.({ rms, timestamp })
      socket.send(encodeAudioEvent(pcm))
      framesSent += 1
      bytesSent += pcm.byteLength
    },
    onFallbackError(error) {
      console.warn('audio worklet backup path:', error)
    },
  })

  await resumeAudioContext(audioContext)
  started = true
  onStatus?.('recording')

  return {
    get transcript() {
      return latestText
    },
    async stop() {
      stopped = true
      window.clearTimeout(noAudioTimer)
      try {
        if (socket.readyState === WebSocket.OPEN) {
          socket.send(encodeAudioEvent(new Uint8Array()))
          await sleep(bytesSent > 0 ? 1000 : 250)
          socket.close()
        }
      } finally {
        audioPipeline.disconnect()
        stream.getTracks().forEach((track) => track.stop())
        await audioContext.close()
        onStatus?.('stopped')
      }
      return latestText.trim()
    },
  }
}

async function createAudioCapturePipeline({ audioContext, source, silentGain, onChunk, onFallbackError }) {
  if (audioContext.audioWorklet && typeof AudioWorkletNode !== 'undefined') {
    try {
      await audioContext.audioWorklet.addModule('/audio-worklets/pcm16-processor.js')
      const workletNode = new AudioWorkletNode(audioContext, 'pcm16-processor')
      workletNode.port.onmessage = (event) => {
        const { pcm, rms, timestamp } = event.data || {}
        if (!pcm) return
        onChunk({ pcm: new Uint8Array(pcm), rms: Number(rms || 0), timestamp: timestamp || Date.now() })
      }
      source.connect(workletNode)
      workletNode.connect(silentGain)
      silentGain.connect(audioContext.destination)
      return {
        mode: 'audio_worklet',
        disconnect() {
          workletNode.port.onmessage = null
          workletNode.disconnect()
          source.disconnect()
          silentGain.disconnect()
        },
      }
    } catch (error) {
      onFallbackError?.(error)
    }
  }

  const processor = audioContext.createScriptProcessor(4096, 1, 1)
  processor.onaudioprocess = (event) => {
    if (audioContext.state === 'suspended') {
      resumeAudioContext(audioContext)
      return
    }
    const input = event.inputBuffer.getChannelData(0)
    onChunk({
      pcm: floatToPcm16(input),
      rms: calculateRms(input),
      timestamp: Date.now(),
    })
  }

  source.connect(processor)
  processor.connect(silentGain)
  silentGain.connect(audioContext.destination)
  return {
    mode: 'script_processor',
    disconnect() {
      try {
        processor.disconnect()
        source.disconnect()
        silentGain.disconnect()
      } catch {
        // disconnect는 stop 중 정리 작업이라 실패해도 사용자 흐름을 막지 않습니다.
      }
    },
  }
}

async function resumeAudioContext(audioContext) {
  if (audioContext.state !== 'suspended') return
  try {
    await audioContext.resume()
  } catch {
    // Chrome은 직접 사용자 제스처가 있어야 AudioContext가 재개되는 경우가 있습니다.
    // 이때는 빈 오디오 오류로 UI에 알려 환자가 마이크 버튼을 다시 누르게 합니다.
  }
}

async function getTranscribeStreamUrl({ sessionId, questionId, visitType, sampleRate }) {
  const res = await fetch(`${API_BASE_URL}/transcribe-stream-url`, {
    method: 'POST',
    headers: await apiHeaders({ sessionId, json: true }),
    body: JSON.stringify({
      session_id: sessionId,
      question_id: questionId,
      visit_type: visitType,
      sample_rate: sampleRate,
    }),
  })
  if (!res.ok) throw new Error('transcribe_stream_url_failed')
  return res.json()
}

function calculateRms(input) {
  let sum = 0
  for (let i = 0; i < input.length; i += 1) {
    sum += input[i] * input[i]
  }
  return Math.sqrt(sum / Math.max(1, input.length))
}

function encodeAudioEvent(payload) {
  return encodeEventMessage({
    ':content-type': 'application/octet-stream',
    ':event-type': 'AudioEvent',
    ':message-type': 'event',
  }, payload)
}

function encodeEventMessage(headers, payload) {
  const headerBytes = encodeHeaders(headers)
  const totalLength = 16 + headerBytes.length + payload.length
  const message = new Uint8Array(totalLength)
  const view = new DataView(message.buffer)
  view.setUint32(0, totalLength, false)
  view.setUint32(4, headerBytes.length, false)
  view.setUint32(8, crc32(message.subarray(0, 8)), false)
  message.set(headerBytes, 12)
  message.set(payload, 12 + headerBytes.length)
  view.setUint32(totalLength - 4, crc32(message.subarray(0, totalLength - 4)), false)
  return message
}

function encodeHeaders(headers) {
  const chunks = []
  for (const [name, value] of Object.entries(headers)) {
    const nameBytes = encoder.encode(name)
    const valueBytes = encoder.encode(value)
    const chunk = new Uint8Array(1 + nameBytes.length + 1 + 2 + valueBytes.length)
    let offset = 0
    chunk[offset] = nameBytes.length
    offset += 1
    chunk.set(nameBytes, offset)
    offset += nameBytes.length
    chunk[offset] = 7
    offset += 1
    new DataView(chunk.buffer).setUint16(offset, valueBytes.length, false)
    offset += 2
    chunk.set(valueBytes, offset)
    chunks.push(chunk)
  }
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
  const out = new Uint8Array(total)
  let offset = 0
  for (const chunk of chunks) {
    out.set(chunk, offset)
    offset += chunk.length
  }
  return out
}

function decodeEventMessage(buffer) {
  const bytes = new Uint8Array(buffer)
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const totalLength = view.getUint32(0, false)
  const headersLength = view.getUint32(4, false)
  const headers = decodeHeaders(bytes.subarray(12, 12 + headersLength))
  const payload = bytes.subarray(12 + headersLength, totalLength - 4)
  return { headers, payload }
}

function decodeHeaders(bytes) {
  const headers = {}
  let offset = 0
  while (offset < bytes.length) {
    const nameLen = bytes[offset]
    offset += 1
    const name = decoder.decode(bytes.subarray(offset, offset + nameLen))
    offset += nameLen
    const type = bytes[offset]
    offset += 1
    if (type !== 7) break
    const valueLen = new DataView(bytes.buffer, bytes.byteOffset + offset, 2).getUint16(0, false)
    offset += 2
    headers[name] = decoder.decode(bytes.subarray(offset, offset + valueLen))
    offset += valueLen
  }
  return headers
}

function floatToPcm16(input) {
  const pcm = new Uint8Array(input.length * 2)
  const view = new DataView(pcm.buffer)
  for (let i = 0; i < input.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, input[i]))
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
  }
  return pcm
}

function makeCrc32Table() {
  const table = new Uint32Array(256)
  for (let i = 0; i < 256; i += 1) {
    let c = i
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    }
    table[i] = c >>> 0
  }
  return table
}

function crc32(bytes) {
  let crc = 0xffffffff
  for (let i = 0; i < bytes.length; i += 1) {
    crc = CRC32_TABLE[(crc ^ bytes[i]) & 0xff] ^ (crc >>> 8)
  }
  return (crc ^ 0xffffffff) >>> 0
}
