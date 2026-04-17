/**
 * PCM16Processor — AudioWorkletProcessor
 *
 * 將麥克風 Float32 PCM（-1 .. 1）轉成 Int16 PCM（little-endian）並分塊 post
 * 回主執行緒。供 ElevenLabs/Deepgram Realtime STT 使用。
 *
 * 使用方式：
 *   const ctx = new AudioContext({ sampleRate: 16000 })
 *   await ctx.audioWorklet.addModule('/worklets/pcm16-processor.js')
 *   const src = ctx.createMediaStreamSource(stream)
 *   const node = new AudioWorkletNode(ctx, 'pcm16-processor')
 *   node.port.onmessage = (e) => wsSend(e.data)  // ArrayBuffer of Int16
 *   src.connect(node).connect(ctx.destination)   // destination 可省，不需聽回放
 *
 * Chunk 大小：預設 1600 樣本 = 100ms @ 16kHz（官方建議區間內，不過度碎片化）。
 */

const DEFAULT_CHUNK_SAMPLES = 1600 // 100ms @ 16kHz

class PCM16Processor extends AudioWorkletProcessor {
  constructor(options) {
    super()
    const opts = (options && options.processorOptions) || {}
    const size = Number(opts.chunkSamples)
    this.chunkSamples = Number.isFinite(size) && size > 0 ? size : DEFAULT_CHUNK_SAMPLES
    // Int16 環形 buffer（滿就 flush 出去）
    this._buffer = new Int16Array(this.chunkSamples)
    this._offset = 0
  }

  /**
   * @param {Float32Array[][]} inputs
   * @returns {boolean}
   */
  process(inputs) {
    const input = inputs[0]
    if (!input || input.length === 0) {
      return true
    }
    const channel = input[0]
    if (!channel || channel.length === 0) {
      return true
    }

    for (let i = 0; i < channel.length; i++) {
      // Float32 (-1..1) -> Int16 (-32768..32767), 飽和處理
      const s = Math.max(-1, Math.min(1, channel[i]))
      this._buffer[this._offset++] = s < 0 ? s * 0x8000 : s * 0x7fff

      if (this._offset >= this.chunkSamples) {
        // 傳 ArrayBuffer（Int16 buffer.slice(0) 的 buffer），主執行緒直接送 WS
        const out = new Int16Array(this._buffer.slice(0))
        this.port.postMessage(out.buffer, [out.buffer])
        this._offset = 0
      }
    }
    return true
  }
}

registerProcessor('pcm16-processor', PCM16Processor)
