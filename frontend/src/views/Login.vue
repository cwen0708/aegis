<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Lock, Loader2, ShieldAlert } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const password = ref('')
const loading = ref(false)
const error = ref('')

async function handleLogin() {
  error.value = ''
  if (!password.value) {
    error.value = '請輸入密碼'
    return
  }

  loading.value = true
  try {
    const ok = await auth.verifyPassword(password.value)
    if (ok) {
      const redirect = (route.query.redirect as string) || '/kanban'
      router.replace(redirect)
    } else {
      error.value = '密碼錯誤'
      password.value = ''
    }
  } catch {
    error.value = '連線失敗，請稍後再試'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-slate-950 flex items-center justify-center px-4">
    <div class="w-full max-w-sm">
      <!-- Logo -->
      <div class="text-center mb-8">
        <div class="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 mb-4">
          <ShieldAlert class="w-8 h-8 text-emerald-400" />
        </div>
        <h1 class="text-2xl font-bold text-slate-100">Aegis</h1>
        <p class="text-sm text-slate-500 mt-1">AI Engineering Grid & Intelligence System</p>
      </div>

      <!-- Login Form -->
      <div class="bg-slate-800/50 rounded-2xl border border-slate-700 p-6">
        <div class="flex items-center gap-2 mb-4">
          <Lock class="w-4 h-4 text-amber-400" />
          <h2 class="text-sm font-semibold text-slate-200">管理員登入</h2>
        </div>

        <form @submit.prevent="handleLogin" class="space-y-4">
          <div>
            <input
              v-model="password"
              type="password"
              placeholder="請輸入管理員密碼"
              autofocus
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm placeholder-slate-600"
            />
          </div>

          <div v-if="error" class="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
            {{ error }}
          </div>

          <button
            type="submit"
            :disabled="loading"
            class="w-full flex items-center justify-center gap-2 px-4 py-3 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all shadow-lg shadow-emerald-500/20"
          >
            <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
            {{ loading ? '驗證中...' : '登入' }}
          </button>
        </form>
      </div>
    </div>
  </div>
</template>
