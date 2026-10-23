<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  listChannelAccounts,
  listChannels,
  startTestAuthorization,
  type ChannelAccount,
  type ChannelDescriptor,
} from './api/channels'

const channels = ref<ChannelDescriptor[]>([])
const accounts = ref<ChannelAccount[]>([])
const error = ref('')
const loading = ref(true)

const statusLabel: Record<string, string> = {
  not_connected: '未连接',
  authorizing: '授权中',
  connected: '已连接',
  blocked: '阻塞',
  error: '错误',
  revoked: '已撤销',
}

async function refresh() {
  loading.value = true
  error.value = ''
  try {
    ;[channels.value, accounts.value] = await Promise.all([
      listChannels(),
      listChannelAccounts(),
    ])
  } catch {
    error.value = '无法读取渠道状态，请确认已登录且后端可用。'
  } finally {
    loading.value = false
  }
}

async function connectForTest(channel: ChannelDescriptor) {
  const account = accounts.value.find((item) => item.channel_type === channel.channel_type)
  if (!account) {
    error.value = '当前用户没有该渠道账号，需由管理员配置账号后再连接。'
    return
  }
  try {
    const result = await startTestAuthorization(channel.channel_type, account.id)
    window.location.href = result.authorization_url
  } catch {
    error.value = '测试连接启动失败。'
  }
}

onMounted(refresh)
</script>

<template>
  <main class="shell">
    <header>
      <p class="eyebrow">Enterprise Agent</p>
      <h1>渠道连接中心</h1>
      <p class="intro">仅管理当前登录用户被授权的渠道账号。长期凭据不会由浏览器保存。</p>
    </header>

    <p v-if="loading">正在读取渠道状态…</p>
    <p v-if="error" class="error">{{ error }}</p>

    <section v-for="channel in channels" :key="channel.channel_type" class="card">
      <div class="card-heading">
        <div>
          <h2>{{ channel.display_name }}</h2>
          <p>{{ channel.guide }}</p>
        </div>
        <span class="status">
          {{ statusLabel[accounts.find((item) => item.channel_type === channel.channel_type)?.status ?? 'not_connected'] }}
        </span>
      </div>
      <p v-if="channel.blocked_reason" class="notice">状态：{{ channel.blocked_reason }}</p>
      <button
        v-if="channel.test_provider_available && accounts.some((item) => item.channel_type === channel.channel_type)"
        type="button"
        @click="connectForTest(channel)"
      >
        使用测试连接（不代表真实已连接）
      </button>
    </section>
  </main>
</template>

<style scoped>
:global(body) { margin: 0; background: #f5f7fb; color: #172033; font-family: sans-serif; }
.shell { max-width: 840px; margin: 0 auto; padding: 56px 24px; }
.eyebrow { color: #667085; letter-spacing: .08em; text-transform: uppercase; }
h1 { margin: 8px 0; }
.intro { color: #667085; }
.card { margin-top: 20px; padding: 24px; background: white; border: 1px solid #e4e7ec; border-radius: 12px; }
.card-heading { display: flex; justify-content: space-between; gap: 20px; }
h2 { margin: 0 0 8px; }
.card p { color: #667085; line-height: 1.5; }
.status { white-space: nowrap; padding: 6px 10px; border-radius: 999px; background: #eef2ff; color: #3730a3; }
.notice { padding: 10px 12px; background: #fff7ed; border-radius: 8px; }
button { padding: 10px 14px; border: 0; border-radius: 8px; background: #364fc7; color: white; cursor: pointer; }
.error { color: #b42318; }
</style>
