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
      <p class="login-brand">Enterprise Agent · 客户运营工作台</p>
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
.auth-loading { min-height: 100vh; display: grid; place-items: center; color: #52666b; font-size: 14px; }
.login-page { min-height: 100vh; display: grid; place-items: center; padding: 24px; background: #edf2f3; }
.login-card { width: min(100%, 420px); display: grid; gap: 12px; padding: 30px; background: #fff; border: 1px solid #dfe7e8; border-radius: 8px; box-shadow: none; }
.login-brand { margin: 0 0 4px; color: #176978; font-size: 13px; font-weight: 600; }
h1 { margin: 0 0 2px; color: #19282c; font-size: 24px; font-weight: 600; }
.muted { margin: 0; color: #52666b; font-size: 13px; line-height: 1.55; }
label { margin-top: 2px; color: #344b50; font-size: 13px; font-weight: 500; }
input { min-height: 40px; padding: 9px 11px; color: #19282c; background: #fff; border: 1px solid #cbd7d9; border-radius: 5px; }
input:hover { border-color: #9aadb1; }
.primary { min-height: 40px; margin-top: 4px; padding: 9px 14px; color: #fff; background: #176978; border: 1px solid #176978; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: 500; }
.primary:hover:not(:disabled) { background: #10515e; border-color: #10515e; }
.primary:disabled { opacity: .7; cursor: wait; }
.login-error { margin: 0; padding: 10px 12px; color: #9a3c3c; background: #fff3f2; border: 1px solid #efd5d3; border-radius: 5px; }
.security-note { padding-top: 4px; border-top: 1px solid #e9eff0; }
@media (max-width: 480px) { .login-page { padding: 16px; } .login-card { padding: 22px 18px; } }
</style>
