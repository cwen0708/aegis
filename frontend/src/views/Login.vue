<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Lock, Loader2, ShieldAlert, User, Ticket } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { config } from '../config'

const API = config.apiUrl
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const loginMode = ref<'user' | 'invite' | 'admin'>('user')
const username = ref('')
const password = ref('')
const inviteCode = ref('')
const newUsername = ref('')
const newPassword = ref('')
const loading = ref(false)
const error = ref('')
const success = ref('')

async function goAfterLogin() {
  // 重新載入權限相關資料（projects、rooms）
  window.dispatchEvent(new Event('aegis-auth-changed'))
  const redirect = (route.query.redirect as string) || '/kanban'
  router.replace(redirect)
}

async function handleLogin() {
  error.value = ''
  loading.value = true
  try {
    if (loginMode.value === 'admin') {
      if (!password.value) { error.value = '請輸入密碼'; return }
      const ok = await auth.verifyPassword(password.value)
      if (ok) goAfterLogin()
      else { error.value = '密碼錯誤'; password.value = '' }
    } else if (loginMode.value === 'user') {
      if (!username.value.trim()) { error.value = '請輸入帳號'; return }
      if (!password.value) { error.value = '請輸入密碼'; return }
      const err = await auth.userLogin(username.value, password.value)
      if (!err) goAfterLogin()
      else { error.value = err; password.value = '' }
    }
  } catch {
    error.value = '連線失敗，請稍後再試'
  } finally {
    loading.value = false
  }
}

async function handleRegister() {
  error.value = ''
  success.value = ''
  if (!inviteCode.value.trim()) { error.value = '請輸入邀請碼'; return }
  if (!newUsername.value.trim() || newUsername.value.trim().length < 2) { error.value = '帳號至少 2 個字元'; return }
  if (!newPassword.value || newPassword.value.length < 6) { error.value = '密碼至少 6 個字元'; return }

  loading.value = true
  try {
    const res = await fetch(`${API}/api/v1/auth/register-with-invite`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        invite_code: inviteCode.value.trim(),
        username: newUsername.value.trim(),
        password: newPassword.value,
      }),
    })
    const data = await res.json()
    if (res.ok && data.token) {
      auth.login(data.token, 'user', data.user)
      await auth.fetchMe()
      goAfterLogin()
    } else {
      error.value = data.detail || '註冊失敗'
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
        <!-- Tab 切換 -->
        <div class="flex border-b border-slate-700 mb-5">
          <button
            @click="loginMode = 'user'; error = ''"
            class="flex-1 pb-2.5 text-xs font-medium transition-colors relative"
            :class="loginMode === 'user' ? 'text-emerald-400' : 'text-slate-500 hover:text-slate-300'"
          >
            <User class="w-3.5 h-3.5 inline mr-1" />登入
            <div v-if="loginMode === 'user'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-400" />
          </button>
          <button
            @click="loginMode = 'invite'; error = ''"
            class="flex-1 pb-2.5 text-xs font-medium transition-colors relative"
            :class="loginMode === 'invite' ? 'text-emerald-400' : 'text-slate-500 hover:text-slate-300'"
          >
            <Ticket class="w-3.5 h-3.5 inline mr-1" />邀請碼
            <div v-if="loginMode === 'invite'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-400" />
          </button>
          <button
            @click="loginMode = 'admin'; error = ''"
            class="flex-1 pb-2.5 text-xs font-medium transition-colors relative"
            :class="loginMode === 'admin' ? 'text-emerald-400' : 'text-slate-500 hover:text-slate-300'"
          >
            <Lock class="w-3.5 h-3.5 inline mr-1" />管理員
            <div v-if="loginMode === 'admin'" class="absolute bottom-0 left-0 right-0 h-0.5 bg-emerald-400" />
          </button>
        </div>

        <!-- 用戶登入 / 管理員登入 -->
        <form v-if="loginMode !== 'invite'" @submit.prevent="handleLogin" class="space-y-4">
          <div v-if="loginMode === 'user'">
            <input v-model="username" type="text" placeholder="帳號" autofocus
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm placeholder-slate-600" />
          </div>
          <div>
            <input v-model="password" type="password"
              :placeholder="loginMode === 'admin' ? '管理員密碼' : '密碼'"
              :autofocus="loginMode === 'admin'"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm placeholder-slate-600" />
          </div>
          <div v-if="error" class="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{{ error }}</div>
          <button type="submit" :disabled="loading"
            class="w-full flex items-center justify-center gap-2 px-4 py-3 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all shadow-lg shadow-emerald-500/20">
            <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
            {{ loading ? '登入中...' : '登入' }}
          </button>
        </form>

        <!-- 邀請碼註冊 -->
        <form v-else @submit.prevent="handleRegister" class="space-y-4">
          <div>
            <input v-model="inviteCode" type="text" placeholder="邀請碼" autofocus
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm placeholder-slate-600 uppercase tracking-wider" />
          </div>
          <div>
            <input v-model="newUsername" type="text" placeholder="設定帳號"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm placeholder-slate-600" />
          </div>
          <div>
            <input v-model="newPassword" type="password" placeholder="設定密碼（至少 6 字元）"
              class="w-full bg-slate-900 border border-slate-700 rounded-lg p-3 text-slate-200 focus:ring-2 focus:ring-emerald-500 outline-none text-sm placeholder-slate-600" />
          </div>
          <div v-if="error" class="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">{{ error }}</div>
          <button type="submit" :disabled="loading"
            class="w-full flex items-center justify-center gap-2 px-4 py-3 bg-emerald-500 hover:bg-emerald-600 disabled:opacity-50 text-white rounded-lg font-bold text-sm transition-all shadow-lg shadow-emerald-500/20">
            <Loader2 v-if="loading" class="w-4 h-4 animate-spin" />
            {{ loading ? '註冊中...' : '註冊並登入' }}
          </button>
        </form>
      </div>
    </div>
  </div>
</template>
