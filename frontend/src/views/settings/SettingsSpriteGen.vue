<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Loader2, Wand2, Grid3x3, Play, Download, Circle } from 'lucide-vue-next'
import { apiClient } from '../../services/api/client'

const route = useRoute()
const memberId = computed(() => Number(route.params.id))

const generating = ref('')
const loading = ref(false)
const description = ref('')
const memberName = ref('')
const progress = ref<Record<string, boolean>>({})
const totalFrames = ref(40)
const completedFrames = ref(0)

const DIRECTIONS = ['south', 'west', 'east', 'north'] as const
const DIR_LABELS: Record<string, string> = { south: '\u2193 \u5357', west: '\u2190 \u897f', east: '\u2192 \u6771', north: '\u2191 \u5317' }
const ACTIONS = ['walk', 'sit', 'work'] as const
const ACTION_LABELS: Record<string, string> = { walk: '\u884c\u8d70', sit: '\u5750\u4e0b', work: '\u5de5\u4f5c' }

async function loadMember() {
  try {
    const members = await apiClient.get<any[]>('/api/v1/members')
    const m = members.find((x: any) => x.id === memberId.value)
    if (m) {
      memberName.value = m.name
      description.value = `A cute chibi ${m.name}, pixel art game character`
    }
  } catch { /* ignore */ }
}

async function loadProgress() {
  try {
    const data = await apiClient.get<any>(`/api/v1/members/${memberId.value}/sprite/progress`)
    progress.value = data.frames || {}
    totalFrames.value = data.total
    completedFrames.value = data.completed
  } catch { /* ignore */ }
}

function frameUrl(name: string) {
  return `/api/v1/members/${memberId.value}/sprite/frame/${name}_orig`
}

async function genHero() {
  generating.value = 'hero_south'
  try {
    await apiClient.post(`/api/v1/members/${memberId.value}/sprite/hero`, { description: description.value })
    await loadProgress()
  } finally { generating.value = '' }
}

async function genDirection(dir: string) {
  generating.value = `hero_${dir}`
  try {
    await apiClient.post(`/api/v1/members/${memberId.value}/sprite/direction/${dir}`, { description: description.value })
    await loadProgress()
  } finally { generating.value = '' }
}

async function genFrame(dir: string, action: string, frame: number) {
  const key = `${action}_${dir}_f${frame}`
  generating.value = key
  try {
    await apiClient.post(`/api/v1/members/${memberId.value}/sprite/frame`, {
      description: description.value, direction: dir, action, frame,
    })
    await loadProgress()
  } finally { generating.value = '' }
}

const cancelled = ref(false)

async function genAll() {
  generating.value = 'all'
  cancelled.value = false
  const id = memberId.value
  const desc = description.value

  try {
    // Hero
    if (!progress.value['hero_south'] && !cancelled.value) {
      generating.value = 'hero_south'
      await apiClient.post(`/api/v1/members/${id}/sprite/hero`, { description: desc })
      await loadProgress()
    }

    // Directions
    for (const dir of ['west', 'east', 'north'] as const) {
      if (cancelled.value) break
      const key = `hero_${dir}`
      if (progress.value[key]) continue
      generating.value = key
      await apiClient.post(`/api/v1/members/${id}/sprite/direction/${dir}`, { description: desc })
      await loadProgress()
    }

    // Animation frames
    for (const action of ACTIONS) {
      for (const dir of DIRECTIONS) {
        for (const f of [0, 1, 2]) {
          if (cancelled.value) break
          const key = `${action}_${dir}_f${f}`
          if (progress.value[key]) continue
          generating.value = key
          await apiClient.post(`/api/v1/members/${id}/sprite/frame`, {
            description: desc, direction: dir, action, frame: f,
          })
          await loadProgress()
        }
        if (cancelled.value) break
      }
      if (cancelled.value) break
    }
  } finally {
    generating.value = ''
  }
}

function cancelGen() {
  cancelled.value = true
}

async function composite() {
  loading.value = true
  try {
    await apiClient.post(`/api/v1/members/${memberId.value}/sprite/composite`, {})
  } finally { loading.value = false }
}

async function applySheet() {
  loading.value = true
  try {
    await apiClient.post(`/api/v1/members/${memberId.value}/sprite/apply`, {})
  } finally { loading.value = false }
}

onMounted(async () => {
  await loadMember()
  await loadProgress()
})
</script>

<template>
  <div class="max-w-4xl mx-auto p-6 space-y-6">
    <h2 class="text-lg font-bold text-slate-100 flex items-center gap-2">
      <Wand2 :size="20" />
      Sprite Generator &mdash; {{ memberName }}
    </h2>

    <!-- Description -->
    <div class="space-y-2">
      <label class="text-sm text-slate-400">角色描述（提示詞）</label>
      <textarea
        v-model="description"
        rows="2"
        class="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none"
        placeholder="A cute chibi mage with purple robe..."
      />
    </div>

    <!-- Progress -->
    <div class="flex items-center gap-3">
      <div class="flex-1 h-2 bg-slate-700 rounded-full overflow-hidden">
        <div class="h-full bg-emerald-500 transition-all" :style="{ width: `${(completedFrames / totalFrames) * 100}%` }" />
      </div>
      <span class="text-xs text-slate-400">{{ completedFrames }}/{{ totalFrames }}</span>
      <button
        v-if="!generating"
        @click="genAll"
        class="flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white text-xs rounded-lg"
      >
        <Play :size="12" />
        {{ completedFrames > 0 ? '繼續生成' : '生成全部' }}
      </button>
      <button
        v-else
        @click="cancelGen"
        class="flex items-center gap-1 px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white text-xs rounded-lg"
      >
        <span class="w-2 h-2 bg-white rounded-sm" />
        停止
      </button>
      <span v-if="generating" class="text-xs text-emerald-400">{{ generating }}</span>
    </div>

    <!-- Hero directions -->
    <div class="space-y-2">
      <h3 class="text-sm font-semibold text-slate-300">主形像 + 方向</h3>
      <div class="grid grid-cols-4 gap-3">
        <div v-for="dir in DIRECTIONS" :key="dir" class="bg-slate-800 rounded-lg p-3 text-center space-y-2">
          <div class="text-xs text-slate-400">{{ DIR_LABELS[dir] }}</div>
          <div class="w-16 h-32 mx-auto bg-slate-900 rounded border border-slate-700 flex items-center justify-center overflow-hidden">
            <img v-if="progress[`hero_${dir}`]" :src="frameUrl(`hero_${dir}`)" class="w-16 h-32 object-contain" style="image-rendering: pixelated" />
            <Circle v-else :size="16" class="text-slate-600" />
          </div>
          <button
            @click="dir === 'south' ? genHero() : genDirection(dir)" :disabled="!!generating"
            class="text-xs px-2 py-1 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-300 rounded w-full"
          >
            <Loader2 v-if="generating === `hero_${dir}`" :size="12" class="animate-spin inline" />
            <span v-else>{{ progress[`hero_${dir}`] ? '重生' : '生成' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Animation grid -->
    <div class="space-y-2">
      <h3 class="text-sm font-semibold text-slate-300">動畫幀（點擊格子單獨生成）</h3>
      <div class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr class="text-slate-500">
              <th class="text-left py-1 px-2 w-16"></th>
              <th v-for="dir in DIRECTIONS" :key="dir" class="py-1 px-1 text-center" colspan="3">{{ DIR_LABELS[dir] }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="action in ACTIONS" :key="action" class="border-t border-slate-700/50">
              <td class="py-2 px-2 text-slate-400 font-medium">{{ ACTION_LABELS[action] }}</td>
              <template v-for="dir in DIRECTIONS" :key="dir">
                <td v-for="f in [0,1,2]" :key="f" class="py-1 px-0.5 text-center">
                  <div
                    class="w-8 h-16 mx-auto bg-slate-900 rounded border cursor-pointer flex items-center justify-center overflow-hidden hover:border-emerald-500 transition"
                    :class="progress[`${action}_${dir}_f${f}`] ? 'border-emerald-700' : 'border-slate-700'"
                    @click="genFrame(dir, action, f)"
                    :title="`${action}_${dir}_f${f}`"
                  >
                    <img
                      v-if="progress[`${action}_${dir}_f${f}`]"
                      :src="frameUrl(`${action}_${dir}_f${f}`)"
                      class="w-8 h-16 object-contain" style="image-rendering: pixelated"
                    />
                    <Loader2 v-else-if="generating === `${action}_${dir}_f${f}`" :size="10" class="animate-spin text-emerald-400" />
                    <Circle v-else :size="6" class="text-slate-700" />
                  </div>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- Actions -->
    <div class="flex items-center gap-3 pt-3 border-t border-slate-700">
      <button
        @click="composite" :disabled="loading || completedFrames < 36"
        class="flex items-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-40 text-white text-sm rounded-lg"
      >
        <Grid3x3 :size="14" />
        合成 Sprite Sheet
      </button>
      <button
        @click="applySheet" :disabled="loading"
        class="flex items-center gap-1.5 px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-40 text-white text-sm rounded-lg"
      >
        <Download :size="14" />
        套用到成員
      </button>
      <span v-if="generating" class="text-xs text-slate-500">
        離開頁面不會丟失進度，回來可繼續
      </span>
    </div>
  </div>
</template>
