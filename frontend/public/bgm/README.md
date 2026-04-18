# Talk Thinking BGM Loops

此目錄放 3 首 ambient loop（20-30 秒、loop-safe、<300KB 每檔）：

- `ambient_01.mp3`
- `ambient_02.mp3`
- `ambient_03.mp3`

## 產生方式（推薦 ElevenLabs Music）

用 ElevenLabs Music API 或 web UI，prompt 範例：

1. `lo-fi ambient piano loop, calm, no drums, seamless loop, 25 seconds`
2. `ambient synth pad, warm, soft, no percussion, seamless loop, 25 seconds`
3. `minimal ambient bells, sparse, peaceful, seamless loop, 25 seconds`

## 需求

- 格式：MP3 128kbps CBR mono（壓小檔）
- 長度：20-30 秒
- Loop-safe：頭尾能無縫接（用 Audacity 的 Crossfade Tracks）
- 音量：-18 dB ~ -14 dB LUFS（不要太大聲蓋過 TTS）

音檔放入後 Talk 頁 thinking 持續 3 秒會自動淡入。若沒放檔案，Talk 頁仍正常運作（bgm 會靜音 fail）。
