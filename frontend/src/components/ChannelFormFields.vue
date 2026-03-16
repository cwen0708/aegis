<script setup lang="ts">
import { Eye, EyeOff } from 'lucide-vue-next'
import type { ChannelField } from '../composables/useChannelConfig'

defineProps<{
  fields: ChannelField[]
  formData: Record<string, any>
  visibleFields: Record<string, boolean>
}>()

const emit = defineEmits<{
  toggleVisibility: [key: string]
}>()
</script>

<template>
  <div v-for="field in fields" :key="field.key" class="space-y-1">
    <!-- Text / Password -->
    <template v-if="field.type === 'text' || field.type === 'password'">
      <label class="block text-sm text-slate-400">{{ field.label }}</label>
      <div class="relative">
        <input
          v-model="formData[field.key]"
          :type="field.type === 'password' && !visibleFields[field.key] ? 'password' : 'text'"
          :placeholder="field.placeholder"
          class="w-full px-3 py-2 bg-slate-800 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500 placeholder-slate-600 pr-10"
        />
        <button
          v-if="field.type === 'password'"
          @click="emit('toggleVisibility', field.key)"
          class="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
        >
          <EyeOff v-if="visibleFields[field.key]" class="w-4 h-4" />
          <Eye v-else class="w-4 h-4" />
        </button>
      </div>
      <p v-if="field.hint" class="text-[11px] text-slate-600">{{ field.hint }}</p>
    </template>

    <!-- Checkbox -->
    <template v-else-if="field.type === 'checkbox'">
      <label class="flex items-center gap-3 cursor-pointer py-1">
        <button
          @click="formData[field.key] = !formData[field.key]"
          :class="[
            'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
            formData[field.key] ? 'bg-emerald-600' : 'bg-slate-600'
          ]"
        >
          <span
            :class="[
              'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
              formData[field.key] ? 'translate-x-4' : 'translate-x-0.5'
            ]"
          />
        </button>
        <span class="text-sm text-slate-300">{{ field.label }}</span>
      </label>
    </template>

    <!-- Select -->
    <template v-else-if="field.type === 'select'">
      <label class="block text-sm text-slate-400">{{ field.label }}</label>
      <select
        v-model="formData[field.key]"
        class="w-full px-3 py-2 bg-slate-800 text-slate-200 border border-slate-600 rounded-lg focus:outline-none focus:border-emerald-500"
      >
        <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </option>
      </select>
      <p v-if="field.hint" class="text-[11px] text-slate-600">{{ field.hint }}</p>
    </template>
  </div>
</template>
