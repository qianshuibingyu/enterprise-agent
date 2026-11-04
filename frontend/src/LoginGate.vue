<script setup lang="ts">
import { onMounted, ref } from 'vue'
import App from './App.vue'
import { ApiError } from './api/inbox'

const authenticated = ref(false)
const checking = ref(true)
const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: 'include',
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!response.ok) {
    let message = `请求失败（${response.status}）`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // Keep the status-based message when the response is not JSON.
    }
    throw new ApiError(response.status, message)
  }
  return response.json() as Promise<T>
}

async function checkSession() {
  try {
    await requestJson('/auth/me')
    authenticated.value = true
  } catch {
    authenticated.value = false
  } finally {
    checking.value = false
  }
}

async function login() {
  submitting.value = true
  error.value = ''
  try {
    const csrf = await requestJson<{ csrf_token: string }>('/auth/csrf', {
      headers: { Origin: window.location.origin },
    })
    await requestJson('/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrf.csrf_token,
      },
      body: JSON.stringify({ username: username.value, password: password.value }),
    })
    password.value = ''
    authenticated.value = true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登录失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

onMounted(checkSession)
</script>

<template>
  <section v-if="checking" class="auth-loading">正在检查登录状态…</section>
  <App v-else-if="authenticated" />
  <main v-else class="login-page">
    <form class="login-card" @submit.prevent="login">
      <p class="eyebrow">Enterprise Agent</p>
      <h1>登录</h1>
      <p class="muted">登录后才能查看授权范围内的 Gmail 账号和收件箱。</p>
      <label for="username">用户名</label>
      <input id="username" v-model.trim="username" autocomplete="username" required />
      <label for="password">密码</label>
      <input id="password" v-model="password" type="password" autocomplete="current-password" required />
      <p v-if="error" class="login-error" role="alert">{{ error }}</p>
      <button class="primary" type="submit" :disabled="submitting">
        {{ submitting ? '登录中…' : '登录' }}
      </button>
      <p class="muted security-note">会话由 HttpOnly cookie 管理；浏览器不保存密码、session token 或 Gmail 凭据。</p>
    </form>
  </main>
</template>

<style scoped>
:global(body) { margin: 0; min-width: 320px; }
.auth-loading { min-height: 100vh; display: grid; place-items: center; color: #758198; }
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #f4f6fa; }
.login-card { width: min(100%, 420px); display: grid; gap: 12px; padding: 32px; background: white; border: 1px solid #e2e7f0; border-radius: 16px; box-shadow: 0 10px 30px rgba(30, 45, 75, .08); }
.eyebrow { margin: 0; color: #6c7890; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
h1 { margin: 0 0 4px; color: #172033; }
label { color: #536079; font-size: 13px; font-weight: 600; }
input { padding: 11px 12px; color: #172033; background: white; border: 1px solid #cbd6f4; border-radius: 9px; }
.primary { padding: 11px 14px; color: white; background: #3158c9; border: 1px solid #3158c9; border-radius: 9px; cursor: pointer; }
.primary:disabled { opacity: .65; cursor: wait; }
.muted { margin: 0; color: #758198; font-size: 13px; line-height: 1.5; }
.login-error { margin: 0; padding: 10px 12px; color: #9a2f3b; background: #fff7f8; border: 1px solid #efc7cd; border-radius: 8px; }
.security-note { margin-top: 4px; }
</style>
