<script setup lang="ts">
import { onMounted, ref } from 'vue'
import App from './App.vue'
import { ApiError, clearCsrfCache } from './api/inbox'

const authenticated = ref(false)
const checking = ref(true)
const mustChangePassword = ref(false)
const username = ref('')
const password = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
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
  // 204 responses (logout) carry no body; parsing them as JSON would throw.
  const text = await response.text()
  return (text ? JSON.parse(text) : undefined) as T
}

async function checkSession() {
  try {
    const identity = await requestJson<{ must_change_password: boolean }>('/auth/me')
    authenticated.value = true
    mustChangePassword.value = identity.must_change_password
  } catch {
    authenticated.value = false
    mustChangePassword.value = false
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
    const identity = await requestJson<{ must_change_password: boolean }>('/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrf.csrf_token,
      },
      body: JSON.stringify({ username: username.value, password: password.value }),
    })
    password.value = ''
    mustChangePassword.value = identity.must_change_password
    authenticated.value = true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登录失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

async function changeInitialPassword() {
  submitting.value = true
  error.value = ''
  try {
    if (newPassword.value.length < 6 || newPassword.value.length > 15) {
      throw new Error('新密码长度必须为 6–15 个字符。')
    }
    if (newPassword.value !== confirmPassword.value) {
      throw new Error('两次输入的新密码不一致，请重新确认。')
    }
    const csrf = await requestJson<{ csrf_token: string }>('/auth/csrf', {
      headers: { Origin: window.location.origin },
    })
    // First-login change is authenticated by the live session, so the
    // temporary password is not collected again.
    await requestJson('/auth/password', {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Origin: window.location.origin,
        'X-CSRF-Token': csrf.csrf_token,
      },
      body: JSON.stringify({ new_password: newPassword.value }),
    })
    clearCsrfCache()
    authenticated.value = false
    mustChangePassword.value = false
    newPassword.value = ''
    confirmPassword.value = ''
    await checkSession()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '修改密码失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

async function logoutForcedChange() {
  submitting.value = true
  try {
    const csrf = await requestJson<{ csrf_token: string }>('/auth/csrf', {
      headers: { Origin: window.location.origin },
    })
    await requestJson('/auth/logout', {
      method: 'POST',
      headers: { Origin: window.location.origin, 'X-CSRF-Token': csrf.csrf_token },
    })
    clearCsrfCache()
    authenticated.value = false
    mustChangePassword.value = false
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '退出登录失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

onMounted(checkSession)
</script>

<template>
  <section v-if="checking" class="auth-loading">正在检查登录状态…</section>
  <main v-else-if="authenticated && mustChangePassword" class="login-page">
    <section class="password-modal" role="dialog" aria-modal="true" aria-labelledby="password-dialog-title">
    <form class="login-card" novalidate @submit.prevent="changeInitialPassword">
      <p class="login-brand">Enterprise Agent · 账号安全</p>
      <h1 id="password-dialog-title">首次登录，请修改密码</h1>
      <p class="muted">请设置 6–15 位的新密码。为保障账号安全，修改完成后需要用新密码重新登录。</p>
      <label for="new-password">新密码</label>
      <input id="new-password" v-model="newPassword" type="password" autocomplete="new-password" minlength="6" maxlength="15" required placeholder="6–15 位字符" />
      <label for="confirm-password">确认新密码</label>
      <input id="confirm-password" v-model="confirmPassword" type="password" autocomplete="new-password" minlength="6" maxlength="15" required placeholder="请再次输入新密码" />
      <p v-if="error" class="login-error" role="alert">{{ error }}</p>
      <button class="primary" type="submit" :disabled="submitting">{{ submitting ? '提交中…' : '修改密码并重新登录' }}</button>
      <button class="secondary" type="button" :disabled="submitting" @click="logoutForcedChange">退出登录</button>
    </form>
    </section>
  </main>
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
.password-modal { position: fixed; inset: 0; z-index: 1000; display: grid; place-items: center; padding: 20px; background: rgb(15 30 34 / 55%); }
.password-modal .login-card { width: min(100%, 440px); }
.login-card { width: min(100%, 420px); display: grid; gap: 12px; padding: 30px; background: #fff; border: 1px solid #dfe7e8; border-radius: 8px; box-shadow: none; }
.login-brand { margin: 0 0 4px; color: #176978; font-size: 13px; font-weight: 600; }
h1 { margin: 0 0 2px; color: #19282c; font-size: 24px; font-weight: 600; }
.muted { margin: 0; color: #52666b; font-size: 13px; line-height: 1.55; }
label { margin-top: 2px; color: #344b50; font-size: 13px; font-weight: 500; }
input { min-height: 40px; padding: 9px 11px; color: #19282c; background: #fff; border: 1px solid #cbd7d9; border-radius: 5px; font: inherit; font-size: 14px; }
input::placeholder { color: #a0b0b3; }
input:focus { border-color: #176978; box-shadow: 0 0 0 3px rgb(23 105 120 / .12); outline: none; }
input:hover { border-color: #9aadb1; }
.primary { min-height: 40px; margin-top: 4px; padding: 9px 14px; color: #fff; background: #176978; border: 1px solid #176978; border-radius: 5px; cursor: pointer; font-size: 14px; font-weight: 500; }
.primary:hover:not(:disabled) { background: #10515e; border-color: #10515e; }
.primary:disabled { opacity: .7; cursor: wait; }
.login-error { margin: 0; padding: 10px 12px; color: #9a3c3c; background: #fff3f2; border: 1px solid #efd5d3; border-radius: 5px; }
.security-note { padding-top: 4px; border-top: 1px solid #e9eff0; }
@media (max-width: 480px) { .login-page { padding: 16px; } .login-card { padding: 22px 18px; } }
</style>
