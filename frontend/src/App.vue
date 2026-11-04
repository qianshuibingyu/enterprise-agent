<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  ApiError,
  inboxApi,
  type ChannelAccount,
  type Inquiry,
  type InternalAnalysis,
  type Message,
  type TransferTarget,
} from './api/inbox'
import { channelsApi } from './api/channels'
import type { ChannelType, ConnectionStatus } from './api/channels'
import {
  fakeAuthorize,
  fakeChannels,
  fakeRevoke,
  canStartFakeAuthorization,
  statusLabel as channelStatusLabel,
  type FakeChannel,
} from './channelCenter'

const accounts = ref<ChannelAccount[]>([])
const messages = ref<Message[]>([])
const inquiries = ref<Inquiry[]>([])
const analysis = ref<InternalAnalysis | null>(null)
const transferTargets = ref<TransferTarget[]>([])
const selectedInquiryId = ref<number | null>(null)
const selectedSalesUserId = ref<number | null>(null)
const loading = ref(true)
const transferSubmitting = ref(false)
const outlookReading = ref(false)
const outlookMessage = ref('')
const outlookError = ref('')
const outlookAuthorizationMessage = ref('')
const outlookAuthorizationError = ref('')
const channels = ref<FakeChannel[]>(fakeChannels.map((channel) => ({ ...channel })))
const error = ref('')
const actionMessage = ref('')
const actionError = ref('')
const handlingSubmitting = ref(false)
const unauthorized = ref(false)
const gmailMessage = ref('')
const gmailError = ref('')
const whatsappMessage = ref('')
const whatsappError = ref('')
const whatsappQr = ref('')
const whatsappQrExpiresAt = ref('')
const profileOpen = ref(false)
const currentUser = ref<{ username: string; role: string } | null>(null)
const logoutError = ref('')
let whatsappPollTimer: number | undefined

const channelDetails: Record<ChannelType, { name: string; provider: string; description: string; next: string }> = {
  gmail: {
    name: 'Gmail',
    provider: 'Google OAuth · Gmail API / Pub/Sub',
    description: '接收 Gmail 入站邮件，使用后端维护的 Watch 和历史游标。',
    next: '在 Google 官方页面完成授权，随后发送一封自有测试邮件。',
  },
  outlook: {
    name: 'Outlook',
    provider: 'Microsoft OAuth · Graph 只读',
    description: '按当前授权主动读取 Inbox，不发送、修改或删除邮件。',
    next: '在 Microsoft 官方页面完成授权，随后执行一次主动读取。',
  },
  whatsapp: {
    name: 'WhatsApp',
    provider: 'Baileys adapter · 关联设备',
    description: '通过项目内 adapter 接收入站消息，QR 只在当前页面短时显示。',
    next: '由账号所有者扫描短时 QR，再使用自有测试账号发送入站消息。',
  },
}
const managedChannelTypes: ChannelType[] = ['gmail', 'outlook', 'whatsapp']

const connectionStatusLabels: Record<string, string> = {
  not_ready: '未连接',
  awaiting_authorization: '授权中',
  connected_pending_inbound: '已连接，待入站',
  verified_inbound: '真实入站已验收',
  blocked: '平台阻塞',
  system_error: '系统错误',
  revoked: '已撤销',
}

const connectionStatusGuidance: Record<string, string> = {
  not_ready: '尚未创建本人的 provider 账号记录。',
  awaiting_authorization: '授权流程已开始，完成官方页面后返回这里。',
  connected_pending_inbound: '授权和连接已记录，仍需要一条真实入站消息完成验收。',
  verified_inbound: '已保存真实入站消息，并通过来源、mapping 和幂等校验。',
  blocked: 'provider 或账号资格暂时无法继续，请确认平台准入和部署配置。',
  system_error: '系统没有完成本次连接，请检查后端配置后重试。',
  revoked: '连接已断开，历史消息不会被删除。',
}

const realAccounts = computed(() => new Map(accounts.value.map((account) => [account.channel_type, account])))

function connectionStatusLabel(status: string | undefined) {
  return connectionStatusLabels[status || 'not_ready'] || status || '未连接'
}

function connectionStatusClass(status: string | undefined) {
  return `state-${status || 'not_ready'}`
}

function channelAccount(channelType: ChannelType) {
  return realAccounts.value.get(channelType)
}

function channelActionLabel(channelType: ChannelType, status: string | undefined) {
  if (channelType === 'whatsapp') return status === 'connected_pending_inbound' || status === 'verified_inbound' ? '重新关联' : '开始关联'
  return status === 'connected_pending_inbound' || status === 'verified_inbound' ? '重新授权' : '开始授权'
}

async function disconnectChannel(channelType: ChannelType) {
  const account = channelAccount(channelType)
  if (!account) return
  const label = channelDetails[channelType].name
  if (!window.confirm(`确认撤销本地 ${label} 连接状态？历史消息不会删除。`)) return
  try {
    const csrf = await inboxApi.getCsrf()
    if (channelType === 'whatsapp') {
      await channelsApi.disconnectWhatsApp(account.id, csrf.csrf_token)
    } else {
      await channelsApi.revoke(account.id, csrf.csrf_token)
    }
    await loadWorkspace()
    if (channelType === 'whatsapp') whatsappMessage.value = 'WhatsApp 已断开本地连接，历史消息保留。'
    if (channelType === 'gmail') gmailMessage.value = 'Gmail 已撤销本地连接状态；如需撤销 Google 授权，请在 Google 账号设置中操作。'
    if (channelType === 'outlook') outlookAuthorizationMessage.value = 'Outlook 已撤销本地连接状态；如需撤销 Microsoft 授权，请在 Microsoft 账号设置中操作。'
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : `${label} 断开失败。`
    if (channelType === 'whatsapp') whatsappError.value = message
    if (channelType === 'gmail') gmailError.value = message
    if (channelType === 'outlook') outlookAuthorizationError.value = message
  }
}

const selectedInquiry = computed(() =>
  inquiries.value.find((inquiry) => inquiry.id === selectedInquiryId.value) ?? null,
)

const accountById = computed(() =>
  new Map(accounts.value.map((account) => [account.id, account])),
)

const timeline = computed(() => {
  if (!selectedInquiry.value) return []
  const inquiry = selectedInquiry.value
  return [
    { label: '询盘创建', value: inquiry.created_at },
    { label: '最近更新时间', value: inquiry.updated_at },
  ].filter((event) => event.value)
})

function selectInquiry(id: number) {
  selectedInquiryId.value = id
}

function formatTime(value: string | null | undefined) {
  if (!value) return '未提供'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function accountLabel(accountId: number) {
  const account = accountById.value.get(accountId)
  return account ? `${account.channel_type} #${account.id}` : `账号 #${accountId}`
}

function statusLabel(status: string) {
  if (status === 'new') return '新询盘'
  if (status === 'assigned') return '已转交'
  return status
}

function handlingStatusLabel(status: string) {
  if (status === 'pending') return '待处理'
  if (status === 'processed') return '已处理'
  if (status === 'ignored') return '已忽略'
  return status
}

async function logoutSystemAccount() {
  logoutError.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.logout(csrf.csrf_token)
    window.location.reload()
  } catch (cause) {
    logoutError.value = cause instanceof Error ? cause.message : '退出登录失败，请稍后重试。'
  }
}

async function loadWorkspace() {
  loading.value = true
  error.value = ''
  actionError.value = ''
  unauthorized.value = false

  try {
    const [nextAccounts, nextChannelAccounts, nextMessages, nextInquiries, nextAnalysis, nextTargets] = await Promise.all([
      inboxApi.getAccounts(),
      channelsApi.accounts(),
      inboxApi.getMessages(),
      inboxApi.getInquiries(),
      inboxApi.getInternalAnalysis(),
      inboxApi.getTransferTargets().catch((cause) => {
        if (cause instanceof ApiError && cause.status === 403) return []
        throw cause
      }),
    ])
    currentUser.value = await inboxApi.getCurrentUser()
    accounts.value = nextAccounts.map((account) => {
      const channelAccount = nextChannelAccounts.find((item) => item.id === account.id)
      return channelAccount
        ? { ...account, status: channelAccount.status, external_account_id: channelAccount.external_account_id }
        : account
    })
    messages.value = nextMessages
    inquiries.value = nextInquiries
    analysis.value = nextAnalysis
    transferTargets.value = nextTargets
    if (selectedInquiryId.value === null && nextInquiries.length > 0) {
      selectedInquiryId.value = nextInquiries[0].id
    }
  } catch (cause) {
    if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
      unauthorized.value = true
      error.value = cause.message
    } else if (cause instanceof Error) {
      error.value = cause.message
    } else {
      error.value = '工作台数据加载失败'
    }
  } finally {
    loading.value = false
  }
}

function authorizeFakeChannel(channelType: FakeChannel['channel_type']) {
  channels.value = channels.value.map((channel) =>
    channel.channel_type === channelType ? fakeAuthorize(channel) : channel,
  )
}

function revokeFakeChannel(channelType: FakeChannel['channel_type']) {
  channels.value = channels.value.map((channel) =>
    channel.channel_type === channelType ? fakeRevoke(channel) : channel,
  )
}

async function startWhatsAppPairing() {
  let account = accounts.value.find((item) => item.channel_type === 'whatsapp')
  if (!account) {
    const csrf = await inboxApi.getCsrf()
    account = await channelsApi.createWhatsAppAccount(csrf.csrf_token)
    accounts.value = [...accounts.value, account]
  }
  whatsappError.value = ''
  whatsappMessage.value = ''
  whatsappQr.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    const result = await channelsApi.startWhatsAppPairing(account.id, csrf.csrf_token)
    whatsappQr.value = result.qr
    whatsappQrExpiresAt.value = result.expires_at
    whatsappMessage.value = result.qr
      ? `二维码有效期至 ${formatTime(result.expires_at)}；请由账号所有者立即扫码。`
      : '关联已启动，正在等待 WhatsApp adapter 返回状态。'
    const expiresAt = result.expires_at ? Date.parse(result.expires_at) : Number.NaN
    const pollUntil = Number.isFinite(expiresAt) ? expiresAt : Date.now() + 5 * 60_000
    const poll = async () => {
      if (Date.now() >= pollUntil) {
        return
      }
      try {
        const current = await channelsApi.getWhatsAppStatus(account.id)
        if (current.qr) {
          whatsappQr.value = current.qr
          whatsappQrExpiresAt.value = current.expires_at || ''
        }
        if (current.status) {
          accounts.value = accounts.value.map((item) => item.id === account.id
            ? { ...item, status: current.status || item.status, external_account_id: current.external_account_id }
            : item)
        }
        if (current.state === 'connected' || current.state === 'connected_pending_inbound') {
          whatsappQr.value = ''
          whatsappQrExpiresAt.value = ''
          whatsappMessage.value = 'WhatsApp 已连接，当前等待真实入站消息验收。'
          return
        }
        if (current.state === 'blocked' || current.state === 'error' || current.state === 'system_error') {
          whatsappError.value = current.detail || 'WhatsApp 连接失败，请检查 adapter 配置。'
          whatsappMessage.value = ''
          return
        }
        if (current.state === 'revoked' || current.state === 'logged_out' || current.status === 'revoked') {
          whatsappQr.value = ''
          whatsappQrExpiresAt.value = ''
          whatsappError.value = 'WhatsApp 设备已退出，请由账号所有者重新关联。'
          whatsappMessage.value = ''
          return
        }
        if (current.state === 'disconnected' || current.state === 'reconnecting' || current.state === 'starting') {
          whatsappMessage.value = 'WhatsApp 连接暂时中断，正在自动重连；账号授权未撤销。'
          whatsappPollTimer = window.setTimeout(() => void poll(), 1000)
          return
        }
        whatsappPollTimer = window.setTimeout(() => void poll(), 1000)
      } catch (cause) {
        whatsappError.value = cause instanceof Error ? cause.message : 'WhatsApp 状态查询失败。'
        whatsappMessage.value = ''
      }
    }
    whatsappPollTimer = window.setTimeout(() => void poll(), 500)
  } catch (cause) {
    whatsappError.value = cause instanceof Error ? cause.message : 'WhatsApp 关联启动失败。'
  }
}

async function startGmailAuthorization() {
  let account = accounts.value.find((item) => item.channel_type === 'gmail')
  if (!account) {
    const csrf = await inboxApi.getCsrf()
    await channelsApi.createGmailAccount(csrf.csrf_token)
    await loadWorkspace()
    gmailMessage.value = 'Gmail 账号已初始化，请再次点击开始授权。'
    return
  }
  try {
    const csrf = await inboxApi.getCsrf()
    const result = await channelsApi.startGmailAuthorization(account.id, csrf.csrf_token)
    window.location.assign(result.authorization_url)
  } catch (cause) {
    gmailError.value = cause instanceof Error ? cause.message : 'Gmail 授权启动失败。'
  }
}

function readGmailCallbackState() {
  const params = new URLSearchParams(window.location.search)
  const gmail = params.get('gmail')
  if (gmail === 'connected') gmailMessage.value = 'Gmail 授权完成。'
  if (gmail === 'error') gmailError.value = params.get('message') || 'Gmail 授权失败。'
  const outlook = params.get('outlook')
  if (outlook === 'connected') outlookAuthorizationMessage.value = 'Outlook 授权完成。'
  if (outlook === 'error') outlookAuthorizationError.value = params.get('message') || 'Outlook 授权失败。'
}

async function startOutlookAuthorization() {
  let account = accounts.value.find((item) => item.channel_type === 'outlook')
  if (!account) {
    const csrf = await inboxApi.getCsrf()
    await channelsApi.createOutlookAccount(csrf.csrf_token)
    await loadWorkspace()
    account = accounts.value.find((item) => item.channel_type === 'outlook')
  }
  if (!account) return
  try {
    const csrf = await inboxApi.getCsrf()
    const result = await channelsApi.startOutlookAuthorization(account.id, csrf.csrf_token)
    window.location.assign(result.authorization_url)
  } catch (cause) {
    outlookAuthorizationError.value = cause instanceof Error ? cause.message : 'Outlook 授权启动失败。'
  }
}

async function readOutlookMessages() {
  const account = accounts.value.find((item) => item.channel_type === 'outlook')
  if (!account) {
    outlookError.value = '当前授权范围没有 Outlook 账号。'
    outlookMessage.value = ''
    return
  }
  outlookReading.value = true
  outlookError.value = ''
  outlookMessage.value = ''
  try {
    const result = await inboxApi.getOutlookMessages(account.id)
    const summary = Array.isArray(result)
      ? {
          total: result.length,
          created: result.filter((item) => item.created).length,
          duplicates: result.filter((item) => !item.created).length,
        }
      : result
    outlookMessage.value = `Outlook 主动读取完成：确认 ${summary.total} 条，其中新增 ${summary.created} 条，重复 ${summary.duplicates} 条。`
    await loadWorkspace()
  } catch (cause) {
    if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
      outlookError.value = '当前用户没有权限读取该 Outlook 账号。'
    } else if (cause instanceof ApiError && cause.status === 503) {
      outlookError.value = 'Outlook MCP 尚未配置或不可用。'
    } else if (cause instanceof Error) {
      outlookError.value = cause.message
    } else {
      outlookError.value = 'Outlook 读取失败，请稍后重试。'
    }
  } finally {
    outlookReading.value = false
  }
}

async function updateMessageHandling(message: Message, action: 'processed' | 'ignored') {
  handlingSubmitting.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.updateMessageHandling(message.id, action, csrf.csrf_token)
    actionMessage.value = action === 'processed' ? '消息已标记为已处理。' : '消息已忽略。'
    await loadWorkspace()
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '消息状态更新失败，请稍后重试。'
  } finally {
    handlingSubmitting.value = false
  }
}

async function updateSelectedInquiryHandling(action: 'processed' | 'ignored') {
  if (!selectedInquiry.value) return
  handlingSubmitting.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.updateInquiryHandling(selectedInquiry.value.id, action, csrf.csrf_token)
    actionMessage.value = action === 'processed' ? '询盘已标记为已处理。' : '询盘已忽略。'
    await loadWorkspace()
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '状态更新失败，请稍后重试。'
  } finally {
    handlingSubmitting.value = false
  }
}

async function transferSelectedInquiry() {
  if (!selectedInquiry.value || selectedSalesUserId.value === null) {
    actionError.value = '请选择有效的业务员。'
    actionMessage.value = ''
    return
  }

  transferSubmitting.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.transferInquiry(selectedInquiry.value.id, selectedSalesUserId.value, csrf.csrf_token)
    actionMessage.value = '询盘已转交，正在刷新授权范围内的数据。'
    selectedSalesUserId.value = null
    await loadWorkspace()
  } catch (cause) {
    if (cause instanceof ApiError) {
      actionError.value = cause.status === 403
        ? '当前用户或目标业务员无权完成转交。'
        : cause.message
    } else if (cause instanceof Error) {
      actionError.value = cause.message
    } else {
      actionError.value = '转交失败，请稍后重试。'
    }
  } finally {
    transferSubmitting.value = false
  }
}

onMounted(() => {
  readGmailCallbackState()
  loadWorkspace()
})
</script>

<template>
  <main class="workspace">
    <header class="topbar">
      <div>
        <p class="eyebrow">{{ profileOpen ? '个人设置' : '运营工作台' }}</p>
        <h1>{{ profileOpen ? '渠道连接' : '客户链路' }}</h1>
      </div>
      <div class="topbar-actions">
        <span v-if="currentUser" class="current-user">{{ currentUser.username }}（{{ currentUser.role }}）</span>
        <button class="link-button logout-link" type="button" @click="logoutSystemAccount">
          退出登录
        </button>
        <button class="secondary" type="button" @click="profileOpen = !profileOpen">
          {{ profileOpen ? '返回工作台' : '我的 / 接入账号' }}
        </button>
        <button class="secondary" type="button" @click="loadWorkspace">刷新</button>
      </div>
    </header>
    <p v-if="logoutError" class="action-error">{{ logoutError }}</p>

    <section v-if="profileOpen" class="profile-view" data-ui="settings">
      <div class="profile-heading">
        <div>
          <p class="eyebrow">我的 / 账号管理</p>
          <h2>个人渠道连接</h2>
          <p class="profile-lede">管理当前登录用户本人的授权和连接状态。所有 provider 调用都经过后端，页面只展示非敏感状态。</p>
        </div>
        <button class="link-button back-link" type="button" @click="profileOpen = false">返回工作台</button>
      </div>

      <div class="settings-list">
        <article v-for="channelType in managedChannelTypes" :key="channelType" class="channel-setting">
          <div class="setting-intro">
            <div class="setting-title-row">
              <h3>{{ channelDetails[channelType].name }}</h3>
              <span class="status-pill" :class="connectionStatusClass(channelAccount(channelType)?.status)">
                {{ connectionStatusLabel(channelAccount(channelType)?.status) }}
              </span>
            </div>
            <p>{{ channelDetails[channelType].provider }}</p>
            <p>{{ channelDetails[channelType].description }}</p>
            <p class="next-step">下一步：{{ channelAccount(channelType)?.status === 'verified_inbound' ? '继续在收件箱处理已授权范围内的消息。' : channelDetails[channelType].next }}</p>
          </div>
          <div class="setting-panel">
            <div class="setting-facts">
              <div><span>账号记录</span><strong>{{ channelAccount(channelType) ? `#${channelAccount(channelType)?.id}` : '尚未创建' }}</strong></div>
              <div><span>外部账号映射</span><strong>{{ channelAccount(channelType)?.external_account_id || '—' }}</strong></div>
              <div><span>验收口径</span><strong>{{ channelAccount(channelType)?.status === 'verified_inbound' ? '真实入站已保存' : '尚未完成' }}</strong></div>
            </div>
            <div class="setting-actions">
              <button
                class="primary"
                type="button"
                @click="channelType === 'gmail' ? startGmailAuthorization() : channelType === 'outlook' ? startOutlookAuthorization() : startWhatsAppPairing()"
              >
                {{ channelActionLabel(channelType, channelAccount(channelType)?.status) }}
              </button>
              <button
                v-if="channelType === 'outlook' && channelAccount(channelType)"
                class="secondary"
                type="button"
                :disabled="outlookReading"
                @click="readOutlookMessages"
              >
                {{ outlookReading ? '读取中…' : '主动读取 Inbox' }}
              </button>
              <button
                v-if="channelAccount(channelType) && channelAccount(channelType)?.status !== 'revoked'"
                class="link-button danger-link"
                type="button"
                @click="disconnectChannel(channelType)"
              >
                {{ channelType === 'whatsapp' ? '断开关联' : '撤销本地连接' }}
              </button>
            </div>
            <p v-if="channelType === 'gmail' && gmailMessage" class="action-success">{{ gmailMessage }}</p>
            <p v-if="channelType === 'gmail' && gmailError" class="action-error">{{ gmailError }}</p>
            <p v-if="channelType === 'outlook' && outlookAuthorizationMessage" class="action-success">{{ outlookAuthorizationMessage }}</p>
            <p v-if="channelType === 'outlook' && outlookAuthorizationError" class="action-error">{{ outlookAuthorizationError }}</p>
            <p v-if="channelType === 'whatsapp' && whatsappMessage" class="action-success">{{ whatsappMessage }}</p>
            <p v-if="channelType === 'whatsapp' && whatsappError" class="action-error">{{ whatsappError }}</p>
            <p v-if="channelType === 'outlook' && outlookMessage" class="action-success">{{ outlookMessage }}</p>
            <p v-if="channelType === 'outlook' && outlookError" class="action-error">{{ outlookError }}</p>
            <div v-if="channelType === 'whatsapp' && whatsappQr" class="qr-box">
              <p class="muted">短时 QR：只保留在当前页面内存，过期后自动清除。</p>
              <img :src="whatsappQr" alt="WhatsApp 关联二维码" />
              <button class="link-button" type="button" @click="whatsappQr = ''; whatsappQrExpiresAt = ''">清除 QR</button>
            </div>
          </div>
        </article>
      </div>

      <section class="fixture-section">
        <div class="fixture-heading">
          <div>
            <h3>测试状态样例</h3>
            <p>仅用于离线 UI 回归，所有内容均为 <strong>TEST_ONLY</strong>，不会调用 provider 或改变真实账号。</p>
          </div>
          <span class="test-chip">TEST_ONLY</span>
        </div>
        <div class="fixture-list">
          <article v-for="channel in channels" :key="channel.channel_type" class="fixture-row">
            <div>
              <strong>{{ channel.display_name }}</strong>
              <span>{{ channelStatusLabel(channel.status) }} · {{ channel.provider }}</span>
            </div>
            <div class="channel-actions">
              <button class="secondary" type="button" :disabled="!canStartFakeAuthorization(channel)" @click="authorizeFakeChannel(channel.channel_type)">Fake 授权</button>
              <button class="link-button" type="button" :disabled="channel.status === 'revoked' || channel.status === 'not_ready'" @click="revokeFakeChannel(channel.channel_type)">撤销 fake</button>
            </div>
          </article>
        </div>
      </section>
      <p class="security-note">浏览器不保存 token、refresh token、client secret、OAuth code、QR 或 auth state；OAuth 只通过后端返回的官方授权地址启动。</p>
    </section>

    <section v-if="loading" class="notice">正在加载授权范围内的数据…</section>
    <section v-else-if="unauthorized" class="notice error">
      当前会话无权访问工作台。请先登录，或联系管理员配置渠道权限。
    </section>
    <section v-else-if="error" class="notice error">
      {{ error }}
      <button class="link-button" type="button" @click="loadWorkspace">重试</button>
    </section>
    <section v-else class="content-grid">
      <section v-if="analysis" class="analysis-strip">
        <div class="analysis-card">
          <span>待处理消息</span>
          <strong>{{ analysis.pending_message_count ?? 0 }}</strong>
        </div>
        <div class="analysis-card">
          <span>询盘状态</span>
          <strong>{{ Object.entries(analysis.inquiries_by_status ?? {}).map(([status, count]) => `${statusLabel(status)} ${count}`).join(' · ') || '无数据' }}</strong>
        </div>
        <div class="analysis-card">
          <span>人工处理</span>
          <strong>{{ Object.entries(analysis.inquiries_by_handling_status ?? {}).map(([status, count]) => `${handlingStatusLabel(status)} ${count}`).join(' · ') || '无数据' }}</strong>
        </div>
        <div class="analysis-card">
          <span>我的转交</span>
          <strong>{{ analysis.my_transfers?.length ?? 0 }}</strong>
        </div>
        <div class="analysis-card">
          <span>渠道异常</span>
          <strong>{{ analysis.channel_statuses?.filter((item) => item.is_abnormal).length ?? 0 }}</strong>
          <small>{{ analysis.channel_statuses?.filter((item) => item.is_abnormal).map((item) => `${item.channel_type}: ${item.status}`).join(' · ') || '无异常' }}</small>
        </div>
      </section>

      <aside class="inbox-panel panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">授权范围</p>
            <h2>询盘列表</h2>
          </div>
          <span class="count">{{ inquiries.length }}</span>
        </div>

        <p v-if="inquiries.length === 0" class="empty">当前授权范围内没有询盘。</p>
        <button
          v-for="inquiry in inquiries"
          :key="inquiry.id"
          class="inquiry-row"
          :class="{ selected: inquiry.id === selectedInquiryId }"
          type="button"
          @click="selectInquiry(inquiry.id)"
        >
          <span class="row-topline">
            <strong>{{ inquiry.customer_nickname || inquiry.customer_contact }}</strong>
            <span class="status">{{ statusLabel(inquiry.status) }}</span>
          </span>
          <span class="channel">{{ accountLabel(inquiry.source_channel_account_id) }}</span>
          <span class="preview">{{ inquiry.display_excerpt || '（无正文）' }}</span>
        </button>

        <div class="subsection">
          <div class="panel-heading compact">
            <h2>消息</h2>
            <span class="count">{{ messages.length }}</span>
          </div>
          <p v-if="messages.length === 0" class="empty">当前授权范围内没有消息。</p>
          <div v-for="message in messages" :key="message.id" class="message-row">
            <strong>{{ message.channel_type }} · {{ message.ingestion_status }}</strong>
            <span>{{ formatTime(message.occurred_at) }} · 人工状态：{{ message.handling_status }}</span>
            <p>{{ message.display_excerpt || '（无正文）' }}</p>
            <div class="message-actions">
              <button
                class="link-button"
                type="button"
                :disabled="handlingSubmitting || message.handling_status === 'processed'"
                @click="updateMessageHandling(message, 'processed')"
              >
                {{ message.handling_status === 'processed' ? '已处理' : '标记已处理' }}
              </button>
              <button
                class="link-button"
                type="button"
                :disabled="handlingSubmitting || message.handling_status === 'ignored'"
                @click="updateMessageHandling(message, 'ignored')"
              >
                {{ message.handling_status === 'ignored' ? '已忽略' : '忽略' }}
              </button>
            </div>
          </div>
        </div>
      </aside>

      <section v-if="selectedInquiry" class="detail-panel panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">链路详情 · fixture #{{ selectedInquiry.id }}</p>
            <h2>{{ selectedInquiry.customer_nickname || selectedInquiry.customer_contact }}</h2>
          </div>
          <span class="test-chip">TEST_ONLY</span>
        </div>

        <div class="facts-grid">
          <div><span>业务类型</span><strong>未提供（当前模型无此字段）</strong></div>
          <div><span>阶段/状态</span><strong>{{ statusLabel(selectedInquiry.status) }}</strong></div>
          <div><span>负责人</span><strong>{{ selectedInquiry.assigned_sales_user_id ? `用户 #${selectedInquiry.assigned_sales_user_id}` : '未分配' }}</strong></div>
          <div><span>来源渠道</span><strong>{{ accountLabel(selectedInquiry.source_channel_account_id) }}</strong></div>
        </div>

        <section class="detail-section">
          <h3>原始客户信息</h3>
          <dl class="contact-list">
            <div><dt>联系人</dt><dd>{{ selectedInquiry.customer_nickname }}</dd></div>
            <div><dt>联系方式</dt><dd>{{ selectedInquiry.customer_contact }}</dd></div>
            <div><dt>安全正文</dt><dd>{{ selectedInquiry.display_text || '（无正文）' }}</dd></div>
            <div v-if="selectedInquiry.content_truncated"><dt>正文状态</dt><dd>正文已安全截断，仅展示授权范围内的纯文本内容。</dd></div>
          </dl>
        </section>

        <section class="detail-section">
          <h3>附件 metadata</h3>
          <p v-if="selectedInquiry.attachments.length === 0" class="empty">没有附件 metadata。</p>
          <ul v-else class="attachment-list">
            <li v-for="attachment in selectedInquiry.attachments" :key="attachment.id">
              <strong>{{ attachment.original_filename }}</strong>
              <span>{{ attachment.media_type }} · {{ attachment.size_bytes }} bytes</span>
            </li>
          </ul>
        </section>

        <section class="detail-section">
          <h3>时间信息</h3>
          <p v-if="timeline.length === 0" class="empty">当前没有状态事件或转交时间字段。</p>
          <ol v-else class="timeline">
            <li v-for="event in timeline" :key="event.label">
              <span>{{ event.label }}</span>
              <strong>{{ formatTime(event.value) }}</strong>
            </li>
          </ol>
          <p v-if="selectedInquiry.timeline_complete" class="muted">以下事件来自后端持久化时间线。</p>
          <p v-else class="muted">当前没有完整的持久化事件历史。</p>
          <ol v-if="selectedInquiry.timeline_complete" class="timeline event-timeline">
            <li v-for="event in selectedInquiry.timeline" :key="event.id">
              <span>{{ event.event_type }}（{{ event.from_status || '—' }} → {{ event.to_status || '—' }}）</span>
              <strong>{{ formatTime(event.occurred_at) }}</strong>
            </li>
          </ol>
        </section>

        <section class="detail-section">
          <h3>确定性分析</h3>
          <p v-if="!analysis" class="empty">当前没有分析结果。</p>
          <template v-else>
            <p class="muted">当前阶段：{{ analysis.my_transfers?.find((item) => item.inquiry_id === selectedInquiry.id)?.current_stage ?? statusLabel(selectedInquiry.status) }}</p>
            <p class="muted">最近可用事件时间：{{ formatTime(analysis.my_transfers?.find((item) => item.inquiry_id === selectedInquiry.id)?.recent_event?.occurred_at ?? selectedInquiry.updated_at) }}</p>
            <p class="muted">事件历史：{{ selectedInquiry.timeline_complete ? '已由后端持久化事件提供。' : '当前没有完整的持久化事件历史。' }}</p>
          </template>
        </section>

        <section class="detail-section action-section">
          <h3>当前可执行操作</h3>
          <p v-if="actionMessage" class="action-success">{{ actionMessage }}</p>
          <p v-if="actionError" class="action-error">{{ actionError }}</p>
          <div v-if="selectedInquiry.status === 'new'" class="transfer-form">
            <label for="transfer-target">手动转交给业务员</label>
            <select id="transfer-target" v-model="selectedSalesUserId">
              <option :value="null">请选择业务员</option>
              <option v-for="target in transferTargets" :key="target.id" :value="target.id">
                {{ target.username }}（用户 #{{ target.id }}）
              </option>
            </select>
            <button
              class="primary"
              type="button"
              :disabled="transferSubmitting || selectedSalesUserId === null"
              @click="transferSelectedInquiry"
            >
              {{ transferSubmitting ? '转交中…' : '确认手动转交' }}
            </button>
            <p v-if="transferTargets.length === 0" class="muted">当前没有可用的 active sales 目标。</p>
          </div>
          <p v-else class="muted">当前询盘已转交；重复转交由后端幂等处理，不在此处自动改派。</p>
          <div class="actions">
            <button
              class="secondary"
              type="button"
              :disabled="handlingSubmitting || selectedInquiry.handling_status === 'processed'"
              @click="updateSelectedInquiryHandling('processed')"
            >
              {{ selectedInquiry.handling_status === 'processed' ? '已处理' : '标记已处理' }}
            </button>
            <button
              class="secondary"
              type="button"
              :disabled="handlingSubmitting || selectedInquiry.handling_status === 'ignored'"
              @click="updateSelectedInquiryHandling('ignored')"
            >
              {{ selectedInquiry.handling_status === 'ignored' ? '已忽略' : '忽略' }}
            </button>
          </div>
          <p class="muted">页面不代替后端授权，不会自动发送、自动转交或修改客户数据。</p>
        </section>
      </section>
      <section v-else class="detail-panel panel empty-state">
        <h2>暂无可展示的链路</h2>
        <p>授权范围内没有询盘，或后端返回为空。</p>
      </section>
    </section>
  </main>
</template>

<style>
:root {
  color: #172033;
  background: #f4f6fa;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-synthesis: none;
}

* { box-sizing: border-box; }
body { margin: 0; min-width: 320px; }
button { font: inherit; }
.workspace { width: min(1240px, calc(100% - 40px)); margin: 0 auto; padding: 36px 0 56px; }
.topbar, .panel-heading, .row-topline { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.topbar { margin-bottom: 18px; }
.topbar-actions { display: flex; align-items: center; gap: 10px; }
.current-user { color: #536079; font-size: 13px; }
.logout-link { color: #9a2f3b; }
.eyebrow { margin: 0 0 6px; color: #6c7890; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
h1, h2, h3, p { margin-top: 0; }
h1 { margin-bottom: 0; font-size: clamp(28px, 4vw, 42px); }
h2 { margin-bottom: 0; font-size: 20px; }
h3 { margin-bottom: 14px; font-size: 15px; }
.test-badge, .test-chip { color: #7a4d00; background: #fff1c7; border: 1px solid #f0d789; }
.test-badge { padding: 10px 14px; border-radius: 10px; font-size: 13px; }
.test-chip { padding: 5px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; }
.profile-panel { margin-top: 20px; padding: 20px; }
.profile-card { display: grid; gap: 10px; padding: 16px; background: #f7f9fc; border: 1px solid #e5eaf2; border-radius: 10px; }
.qr-box { display: grid; gap: 8px; padding: 12px; background: #fffaf0; border: 1px solid #f0d789; border-radius: 9px; }
.qr-box img { width: 240px; height: 240px; image-rendering: pixelated; background: white; }
.channel-center { margin-top: 20px; padding: 20px; }
.channel-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
.channel-card { display: grid; gap: 8px; padding: 15px; background: #f7f9fc; border: 1px solid #e5eaf2; border-radius: 10px; }
.channel-provider { margin: 0; color: #3158c9; font-size: 12px; overflow-wrap: anywhere; }
.channel-actions { display: flex; align-items: center; gap: 10px; }
.analysis-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-top: 20px; }
.analysis-card { display: grid; gap: 7px; padding: 15px 16px; background: white; border: 1px solid #e2e7f0; border-radius: 12px; }
.analysis-card span { color: #758198; font-size: 12px; }
.analysis-card strong { font-size: 18px; }
.content-grid { display: grid; grid-template-columns: minmax(280px, 370px) 1fr; gap: 20px; margin-top: 20px; }
.panel { background: white; border: 1px solid #e2e7f0; border-radius: 16px; box-shadow: 0 10px 30px rgba(30, 45, 75, .06); }
.inbox-panel { padding: 20px 0; overflow: hidden; }
.detail-panel { padding: 28px; min-width: 0; }
.panel-heading { padding: 0 20px 16px; }
.panel-heading.compact { padding: 0 0 12px; }
.count { display: inline-grid; min-width: 28px; height: 28px; place-items: center; border-radius: 999px; color: #3158c9; background: #edf2ff; font-size: 13px; font-weight: 700; }
.inquiry-row { display: block; width: 100%; padding: 15px 20px; text-align: left; color: inherit; background: transparent; border: 0; border-top: 1px solid #edf0f5; cursor: pointer; }
.inquiry-row:hover, .inquiry-row.selected { background: #f2f5ff; }
.row-topline { align-items: flex-start; }
.status { color: #3158c9; font-size: 12px; white-space: nowrap; }
.channel, .preview, .message-row span, .muted, .empty { color: #758198; font-size: 13px; }
.channel, .preview { display: block; margin-top: 6px; }
.preview { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.subsection { margin: 25px 20px 0; padding-top: 20px; border-top: 1px solid #e5eaf2; }
.message-row { padding: 11px 0; border-top: 1px solid #edf0f5; font-size: 13px; }
.message-row p { margin: 5px 0 0; line-height: 1.5; }
.message-actions { display: flex; gap: 12px; margin-top: 7px; }
.notice { margin-top: 20px; padding: 18px; background: white; border: 1px solid #e2e7f0; border-radius: 12px; }
.notice.error { color: #9a2f3b; border-color: #efc7cd; background: #fff7f8; }
.facts-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 26px 0; }
.facts-grid div { padding: 14px; background: #f7f9fc; border-radius: 10px; }
.facts-grid span, .contact-list dt { display: block; color: #758198; font-size: 12px; }
.facts-grid strong { display: block; margin-top: 7px; font-size: 14px; }
.detail-section { padding: 22px 0; border-top: 1px solid #e5eaf2; }
.contact-list { display: grid; gap: 11px; margin: 0; }
.contact-list div { display: grid; grid-template-columns: 90px 1fr; gap: 12px; }
.contact-list dd { margin: 0; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
.attachment-list { display: grid; gap: 10px; padding: 0; margin: 0; list-style: none; }
.attachment-list li { display: flex; justify-content: space-between; gap: 16px; padding: 11px 13px; background: #f7f9fc; border-radius: 9px; }
.attachment-list span { color: #758198; font-size: 13px; }
.timeline { display: grid; gap: 12px; padding: 0 0 0 18px; margin: 0; }
.timeline li { display: flex; justify-content: space-between; gap: 16px; padding-left: 5px; }
.timeline strong { font-size: 13px; }
.transfer-form { display: grid; grid-template-columns: minmax(180px, 1fr) auto; align-items: center; gap: 10px; margin-bottom: 16px; }
.transfer-form label { color: #758198; font-size: 13px; }
.transfer-form select { min-width: 0; padding: 9px 10px; color: #172033; background: white; border: 1px solid #cbd6f4; border-radius: 9px; }
.transfer-form .primary { grid-column: 2; }
.action-success { padding: 10px 12px; color: #176b43; background: #effaf4; border: 1px solid #b9e6ca; border-radius: 8px; }
.action-error { padding: 10px 12px; color: #9a2f3b; background: #fff7f8; border: 1px solid #efc7cd; border-radius: 8px; }
.actions { display: flex; flex-wrap: wrap; gap: 10px; }
.primary, .secondary, .link-button { border-radius: 9px; padding: 9px 13px; cursor: pointer; }
.primary { color: white; background: #3158c9; border: 1px solid #3158c9; }
.secondary { color: #3158c9; background: white; border: 1px solid #cbd6f4; }
.secondary:disabled { color: #8b96a8; background: #f2f4f7; border-color: #e0e4eb; cursor: not-allowed; }
.link-button { padding: 0; color: inherit; background: transparent; border: 0; text-decoration: underline; }
.danger-link { color: #9a2f3b; }
.empty-state { display: grid; min-height: 280px; place-content: center; text-align: center; }
.profile-view { display: grid; gap: 24px; width: min(1152px, 100%); margin: 32px auto 0; }
.profile-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 4px 0 12px; }
.profile-heading h2 { margin: 0 0 10px; font-size: 30px; font-weight: 650; letter-spacing: -0.02em; }
.profile-lede { max-width: 620px; margin: 0; color: #596477; font-size: 15px; line-height: 1.6; }
.back-link { padding-top: 8px; font-size: 14px; text-decoration: none; }
.settings-list { display: grid; gap: 0; }
.channel-setting { display: grid; grid-template-columns: minmax(260px, 0.7fr) minmax(0, 1.3fr); gap: 48px; padding: 32px 0; border-top: 1px solid #dfe4eb; }
.channel-setting:last-child { border-bottom: 1px solid #dfe4eb; }
.setting-intro { padding-top: 4px; }
.setting-title-row { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-bottom: 10px; }
.setting-title-row h3 { margin: 0; color: #172033; font-size: 18px; font-weight: 650; }
.setting-intro p { margin: 0 0 8px; color: #667287; font-size: 13px; line-height: 1.55; }
.setting-intro .next-step { margin-top: 18px; color: #344054; }
.status-pill { display: inline-flex; align-items: center; min-height: 24px; padding: 3px 8px; border-radius: 4px; font-size: 12px; font-weight: 650; white-space: nowrap; }
.state-not_ready, .state-awaiting_authorization { color: #596477; background: #eef1f4; }
.state-connected_pending_inbound { color: #7a4d00; background: #fff2cc; }
.state-verified_inbound { color: #176b43; background: #e4f6eb; }
.state-blocked, .state-system_error { color: #9a2f3b; background: #fdebed; }
.state-revoked { color: #5f6368; background: #e5e7eb; }
.setting-panel { display: grid; gap: 18px; padding: 20px; background: #fafbfc; border-radius: 8px; }
.setting-facts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.setting-facts div { min-width: 0; }
.setting-facts span { display: block; margin-bottom: 5px; color: #788397; font-size: 12px; }
.setting-facts strong { display: block; overflow-wrap: anywhere; color: #253047; font-size: 14px; font-weight: 550; }
.setting-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.danger-link { color: #9a2f3b; }
.profile-feedback { margin-top: -8px; }
.fixture-section { padding-top: 8px; border-top: 1px solid #dfe4eb; }
.fixture-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 12px; }
.fixture-heading h3 { margin: 0 0 6px; font-size: 15px; }
.fixture-heading p { margin: 0; color: #6c7890; font-size: 13px; line-height: 1.5; }
.fixture-list { display: grid; gap: 1px; overflow: hidden; background: #dfe4eb; border-radius: 8px; }
.fixture-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 16px; background: #f8fafc; }
.fixture-row strong, .fixture-row span { display: block; }
.fixture-row span { margin-top: 4px; color: #6c7890; font-size: 12px; }
.security-note { margin: 0; color: #788397; font-size: 12px; line-height: 1.5; }
.profile-state { display: grid; gap: 10px; padding: 24px; background: #fafbfc; border-radius: 8px; }
.profile-state strong { font-size: 15px; }
.profile-state p { margin: 0 0 4px; color: #667287; font-size: 13px; }
.loading-bar { display: block; height: 14px; background: #e8edf2; border-radius: 3px; }
.loading-title { width: 28%; height: 20px; }
.loading-line { width: 72%; }
.loading-line.short { width: 48%; }
@media (max-width: 800px) { .channel-grid { grid-template-columns: 1fr; } .analysis-strip { grid-template-columns: repeat(2, 1fr); } .content-grid { grid-template-columns: 1fr; } .facts-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 800px) { .channel-setting { grid-template-columns: 1fr; gap: 18px; } .profile-heading { display: block; } .back-link { margin-top: 12px; } }
@media (max-width: 480px) { .analysis-strip { grid-template-columns: 1fr; } .transfer-form { grid-template-columns: 1fr; } .transfer-form .primary { grid-column: 1; } .profile-view { margin-top: 20px; } .profile-heading h2 { font-size: 25px; } .setting-panel { padding: 16px; } .setting-facts { grid-template-columns: 1fr; gap: 12px; } .fixture-row { display: grid; align-items: start; } .setting-actions > button { min-height: 42px; } }
@media (max-width: 480px) { .workspace { width: min(100% - 24px, 1240px); padding-top: 22px; } .detail-panel { padding: 20px; } .facts-grid { grid-template-columns: 1fr; } .attachment-list li { display: grid; gap: 5px; } }
</style>
