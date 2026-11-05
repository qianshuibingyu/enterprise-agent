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
const messagePage = ref(1)
const messageHasMore = ref(false)
const messageLoadingMore = ref(false)
const expandedMessageIds = ref<Set<number>>(new Set())
const messageHandlingFilter = ref('')
const messageIngestionFilter = ref('')
const messageChannelAccountFilter = ref('')
const inquiryStatusFilter = ref('')
const inquiryHandlingFilter = ref('')
const filterLoading = ref(false)
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
const providerOpeningMessageId = ref<number | null>(null)
const providerFallback = ref<{ label: string; url: string } | null>(null)
const unauthorized = ref(false)
const unauthorizedStatus = ref<401 | 403 | null>(null)
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

const messageChannelAccounts = computed(() =>
  accounts.value.filter((account) => ['gmail', 'outlook', 'whatsapp'].includes(account.channel_type)),
)

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
  return '开始授权'
}

function needsChannelAuthorization(status: string | undefined) {
  return !['connected', 'connected_pending_inbound', 'verified_inbound'].includes(status ?? '')
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

function toggleMessageExpanded(messageId: number) {
  const next = new Set(expandedMessageIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  expandedMessageIds.value = next
}

async function loadMoreMessages() {
  if (messageLoadingMore.value || !messageHasMore.value) return
  messageLoadingMore.value = true
  actionError.value = ''
  try {
    const next = await inboxApi.getMessages(queryString({
      handling_status: messageHandlingFilter.value,
      ingestion_status: messageIngestionFilter.value,
      channel_account_id: messageChannelAccountFilter.value,
      page: String(messagePage.value + 1),
      page_size: '20',
      sort: 'occurred_at',
      descending: 'false',
    }))
    messages.value = next.items
    messagePage.value = next.page
    messageHasMore.value = next.has_more
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '更多消息加载失败，请稍后重试。'
  } finally {
    messageLoadingMore.value = false
  }
}

async function loadPreviousMessages() {
  if (messageLoadingMore.value || messagePage.value <= 1) return
  messageLoadingMore.value = true
  actionError.value = ''
  try {
    const previous = await inboxApi.getMessages(queryString({
      handling_status: messageHandlingFilter.value,
      ingestion_status: messageIngestionFilter.value,
      channel_account_id: messageChannelAccountFilter.value,
      page: String(messagePage.value - 1),
      page_size: '20',
      sort: 'occurred_at',
      descending: 'false',
    }))
    messages.value = previous.items
    messagePage.value = previous.page
    messageHasMore.value = previous.has_more
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '消息分页加载失败，请稍后重试。'
  } finally {
    messageLoadingMore.value = false
  }
}

function formatTime(value: string | null | undefined) {
  if (!value) return '未提供'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function accountLabel(accountId: number) {
  const account = accountById.value.get(accountId)
  return account ? `${account.channel_type} #${account.id}` : `账号 #${accountId}`
}

function accountStatus(accountId: number) {
  return accountById.value.get(accountId)?.status
}

function messageContactLabel(message: Message) {
  if (message.channel_type !== 'whatsapp') {
    return message.customer_contact || message.customer_nickname || '联系方式未提供'
  }
  const externalId = message.external_message_id || ''
  if (externalId.includes('@g.us')) return '群聊'
  if (message.customer_contact && /^\d{6,15}$/.test(message.customer_contact)) {
    return `+${message.customer_contact}`
  }
  if (externalId.includes('@lid')) return 'WhatsApp 联系人（LID）'
  return 'WhatsApp 联系人'
}

function messageSenderLabel(message: Message) {
  if (message.channel_type === 'whatsapp') return message.customer_nickname || '发送人未提供'
  return message.customer_nickname || ''
}

function queryString(values: Record<string, string>) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value) })
  return params.toString() ? `?${params.toString()}` : ''
}

function statusLabel(status: string) {
  if (status === 'new') return '新询盘'
  if (status === 'assigned') return '已转交'
  return status
}

function ingestionStatusLabel(status: string) {
  if (status === 'received') return '已接收'
  if (status === 'processed') return '已处理入站'
  if (status === 'failed') return '入站失败'
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
  const initialLoad = accounts.value.length === 0 && messages.value.length === 0 && inquiries.value.length === 0 && analysis.value === null
  if (initialLoad) loading.value = true
  filterLoading.value = true
  error.value = ''
  actionError.value = ''
  unauthorized.value = false

  try {
    const [nextAccounts, nextChannelAccounts, nextMessages, nextInquiries, nextAnalysis, nextTargets] = await Promise.all([
      inboxApi.getAccounts(),
      channelsApi.accounts(),
      inboxApi.getMessages(queryString({
        handling_status: messageHandlingFilter.value,
        ingestion_status: messageIngestionFilter.value,
        channel_account_id: messageChannelAccountFilter.value,
        page: '1', page_size: '20', sort: 'occurred_at', descending: 'false',
      })),
      inboxApi.getInquiries(queryString({
        status: inquiryStatusFilter.value,
        handling_status: inquiryHandlingFilter.value,
        page: '1', page_size: '50', sort: 'updated_at', descending: 'true',
      })),
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
    messages.value = nextMessages.items
    messagePage.value = nextMessages.page
    messageHasMore.value = nextMessages.has_more
    expandedMessageIds.value = new Set()
    inquiries.value = nextInquiries.items
    analysis.value = nextAnalysis
    transferTargets.value = nextTargets
    if (!nextInquiries.items.some((inquiry) => inquiry.id === selectedInquiryId.value)) {
      selectedInquiryId.value = nextInquiries.items[0]?.id ?? null
      selectedSalesUserId.value = null
    }
  } catch (cause) {
    if (cause instanceof ApiError && (cause.status === 401 || cause.status === 403)) {
      unauthorized.value = true
      unauthorizedStatus.value = cause.status
      error.value = cause.message
    } else if (cause instanceof Error) {
      error.value = cause.message
    } else {
      error.value = '工作台数据加载失败'
    }
  } finally {
    if (initialLoad) loading.value = false
    filterLoading.value = false
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
  whatsappError.value = ''
  whatsappMessage.value = ''
  whatsappQr.value = ''
  try {
    if (!account) {
      const csrf = await inboxApi.getCsrf()
      account = await channelsApi.createWhatsAppAccount(csrf.csrf_token)
      accounts.value = [...accounts.value, account]
    }
    if (!account) throw new Error('WhatsApp 账号初始化失败。')
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
  outlookAuthorizationError.value = ''
  outlookAuthorizationMessage.value = ''
  if (account && !needsChannelAuthorization(account.status)) {
    outlookAuthorizationMessage.value = 'Outlook 已连接，无需重新授权。请在消息队列点击“去渠道处理”打开邮件。'
    return
  }
  const authorizationWindow = window.open('about:blank', '_blank')
  if (authorizationWindow) authorizationWindow.opener = null
  try {
    if (!account) {
      const csrf = await inboxApi.getCsrf()
      await channelsApi.createOutlookAccount(csrf.csrf_token)
      await loadWorkspace()
      account = accounts.value.find((item) => item.channel_type === 'outlook')
    }
    if (!account) throw new Error('Outlook 账号初始化失败。')
    const csrf = await inboxApi.getCsrf()
    const result = await channelsApi.startOutlookAuthorization(account.id, csrf.csrf_token)
    if (authorizationWindow && !authorizationWindow.closed) {
      authorizationWindow.location.assign(result.authorization_url)
    } else {
      window.location.assign(result.authorization_url)
    }
  } catch (cause) {
    if (authorizationWindow && !authorizationWindow.closed) authorizationWindow.close()
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
          links_repaired: 0,
        }
      : result
    const repaired = summary.links_repaired ? `，补齐邮件链接 ${summary.links_repaired} 条` : ''
    outlookMessage.value = `Outlook 主动读取完成：确认 ${summary.total} 条，其中新增 ${summary.created} 条，重复 ${summary.duplicates} 条${repaired}。`
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

function isWebUrl(url: string) {
  return /^https?:\/\//i.test(url)
}

function isAppSchemeUrl(url: string) {
  return /^[a-z][a-z0-9+.-]*:/i.test(url) && !isWebUrl(url)
}

/**
 * Hand an app scheme (whatsapp://) to the OS.
 *
 * A tab cannot render this protocol, so opening it through a pre-opened blank
 * popup left an empty window behind when the desktop app was missing.
 */
function launchAppScheme(url: string) {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.rel = 'noopener noreferrer'
  anchor.style.display = 'none'
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
}

async function openMessageProvider(message: Message) {
  actionError.value = ''
  actionMessage.value = ''
  providerFallback.value = null
  providerOpeningMessageId.value = message.id
  const providerWindow = window.open('about:blank', '_blank')
  if (providerWindow) providerWindow.opener = null
  try {
    const result = await inboxApi.getMessageProviderAction(message.id)
    if (result.supported && result.url) {
      const appScheme = isAppSchemeUrl(result.url)
      if (!appScheme) {
        if (providerWindow && !providerWindow.closed) {
          providerWindow.location.assign(result.url)
        } else {
          // A strict popup policy may still block the pre-opened tab.
          window.location.assign(result.url)
        }
      } else {
        if (providerWindow && !providerWindow.closed) providerWindow.close()
        launchAppScheme(result.url)
      }
      if (result.web_url && result.web_url !== result.url && isWebUrl(result.web_url)) {
        providerFallback.value = {
          label: result.channel_type === 'whatsapp' ? '改用 WhatsApp 网页版打开' : '改用网页版打开',
          url: result.web_url,
        }
      }
      actionMessage.value = result.reason || (appScheme
        ? '已请求打开本机应用；若系统没有响应，可用下面的网页版入口。'
        : '已在新窗口打开渠道处理入口。')
      return
    }
    if (providerWindow && !providerWindow.closed) providerWindow.close()
    actionError.value = result.reason || '当前消息暂不支持渠道处理。'
  } catch (cause) {
    if (providerWindow && !providerWindow.closed) providerWindow.close()
    actionError.value = cause instanceof Error ? cause.message : '渠道处理入口获取失败。'
  } finally {
    window.setTimeout(() => {
      if (providerOpeningMessageId.value === message.id) providerOpeningMessageId.value = null
    }, 700)
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
                v-if="channelType === 'whatsapp' || needsChannelAuthorization(channelAccount(channelType)?.status)"
                class="primary"
                type="button"
                @click="channelType === 'gmail' ? startGmailAuthorization() : channelType === 'outlook' ? startOutlookAuthorization() : startWhatsAppPairing()"
              >
                {{ channelActionLabel(channelType, channelAccount(channelType)?.status) }}
              </button>
              <span v-else class="connection-ready">已连接</span>
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

    <template v-else-if="!profileOpen">
      <section v-if="loading" class="notice">正在加载授权范围内的数据…</section>
      <section v-else-if="unauthorized" class="notice error">
      {{ unauthorizedStatus === 401 ? '当前会话已失效，请重新登录。' : '当前账号无权访问该运营收件箱。' }}
    </section>
    <section v-else-if="error" class="notice error">
      {{ error }}
      <button class="link-button" type="button" @click="loadWorkspace">重试</button>
    </section>
    <section v-else class="content-grid" data-ui="inbox">
      <section v-if="analysis" class="analysis-strip">
        <div class="overview-heading">
          <div>
            <p class="eyebrow">今日工作量</p>
            <h2>先看异常，再处理消息</h2>
          </div>
          <span class="overview-note">数据来自当前授权范围</span>
        </div>
        <div class="analysis-card">
          <span>待处理消息</span>
          <strong>{{ analysis.pending_message_count ?? 0 }}</strong>
          <small>需要人工查看</small>
        </div>
        <div class="analysis-card">
          <span>询盘状态</span>
          <strong>{{ Object.entries(analysis.inquiries_by_status ?? {}).map(([status, count]) => `${statusLabel(status)} ${count}`).join(' · ') || '无数据' }}</strong>
          <small>当前询盘分布</small>
        </div>
        <div class="analysis-card">
          <span>人工处理</span>
          <strong>{{ Object.entries(analysis.inquiries_by_handling_status ?? {}).map(([status, count]) => `${handlingStatusLabel(status)} ${count}`).join(' · ') || '无数据' }}</strong>
          <small>处理状态分布</small>
        </div>
        <div class="analysis-card">
          <span>我的转交</span>
          <strong>{{ analysis.my_transfers?.length ?? 0 }}</strong>
          <small>本周期转交记录</small>
        </div>
        <div class="analysis-card">
          <span>渠道异常</span>
          <strong>{{ analysis.channel_statuses?.filter((item) => item.is_abnormal).length ?? 0 }}</strong>
          <small>{{ analysis.channel_statuses?.filter((item) => item.is_abnormal).map((item) => `${item.channel_type}: ${item.status}`).join(' · ') || '无异常' }}</small>
        </div>
      </section>

      <section class="inbox-panel panel" :class="{ 'is-refreshing': filterLoading }">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">运营收件箱</p>
            <h2>消息处理队列</h2>
          </div>
          <span class="count">{{ messages.length }} 条待查</span>
        </div>

        <div class="inbox-filters">
          <div class="filter-group">
            <span>询盘</span>
            <select v-model="inquiryStatusFilter" aria-label="询盘业务状态" @change="loadWorkspace">
              <option value="">全部阶段</option><option value="new">新询盘</option><option value="assigned">已转交</option>
            </select>
            <select v-model="inquiryHandlingFilter" aria-label="询盘人工状态" @change="loadWorkspace">
              <option value="">全部处理状态</option><option value="pending">待处理</option><option value="processed">已处理</option><option value="ignored">已忽略</option>
            </select>
          </div>
        </div>
        <p v-if="filterLoading" class="refresh-state" role="status">正在刷新当前筛选结果…</p>
        <p v-if="inquiries.length === 0" class="empty">当前授权范围内没有符合条件的询盘。</p>
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
          <div class="panel-heading compact message-heading">
            <div>
              <p class="eyebrow">逐条处理</p>
              <h2>消息</h2>
            </div>
            <span class="count">{{ messages.length }} 条</span>
          </div>
          <div class="inbox-filters">
            <div class="filter-group">
              <span>渠道</span>
              <select v-model="messageChannelAccountFilter" aria-label="消息渠道" @change="loadWorkspace">
                <option value="">全部渠道</option>
                <option v-for="account in messageChannelAccounts" :key="account.id" :value="String(account.id)">
                  {{ account.channel_type === 'whatsapp' ? 'WhatsApp' : account.channel_type === 'outlook' ? 'Outlook' : 'Gmail' }}
                </option>
              </select>
            </div>
            <div class="filter-group">
              <span>状态</span>
              <select v-model="messageIngestionFilter" aria-label="消息入站状态" @change="loadWorkspace">
                <option value="">全部入站</option><option value="received">已接收</option><option value="processed">已处理入站</option><option value="failed">入站失败</option>
              </select>
              <select v-model="messageHandlingFilter" aria-label="消息人工状态" @change="loadWorkspace">
                <option value="">全部人工</option><option value="pending">待处理</option><option value="processed">已处理</option><option value="ignored">已忽略</option>
              </select>
            </div>
          </div>
          <p v-if="actionMessage" class="inline-feedback success" role="status">{{ actionMessage }}</p>
          <p v-if="providerFallback" class="inline-feedback success">
            <a :href="providerFallback.url" target="_blank" rel="noopener noreferrer">{{ providerFallback.label }}</a>
          </p>
          <p v-if="actionError" class="inline-feedback error" role="alert">{{ actionError }}</p>
          <p v-if="messages.length === 0" class="empty">当前授权范围内没有符合条件的消息。</p>
          <div v-for="message in messages" :key="message.id" class="message-row">
            <div class="message-meta">
              <span class="channel-mark" :class="`channel-${message.channel_type}`">{{ message.channel_type === 'whatsapp' ? 'WS' : message.channel_type === 'outlook' ? 'OL' : 'GM' }}</span>
              <strong>{{ messageContactLabel(message) }}</strong>
              <span v-if="messageSenderLabel(message)" class="sender">发送人：{{ messageSenderLabel(message) }}</span>
              <span class="meta-time">{{ formatTime(message.occurred_at) }}</span>
              <span class="state-label ingestion-state">入站：{{ ingestionStatusLabel(message.ingestion_status) }}</span>
              <span class="state-label">人工：{{ handlingStatusLabel(message.handling_status) }}</span>
              <span v-if="accountStatus(message.channel_account_id) === 'blocked'" class="status-warning">渠道阻塞</span><span v-if="accountStatus(message.channel_account_id) === 'revoked'" class="status-warning">渠道已撤销</span>
            </div>
            <p :class="{ 'message-preview': !expandedMessageIds.has(message.id) }">{{ expandedMessageIds.has(message.id) ? (message.display_text || '（无正文）') : (message.display_excerpt || '（无正文）') }}</p>
            <div class="message-actions">
              <button class="action-button action-secondary" type="button" @click="toggleMessageExpanded(message.id)">
                {{ expandedMessageIds.has(message.id) ? '收起正文' : '展开正文' }}
              </button>
              <button
                class="action-button action-primary"
                :class="{ 'is-opening': providerOpeningMessageId === message.id }"
                type="button"
                :disabled="providerOpeningMessageId === message.id"
                @click="openMessageProvider(message)"
              >
                {{ providerOpeningMessageId === message.id ? '正在打开…' : '去渠道处理' }}
              </button>
              <button
                class="action-button action-secondary"
                type="button"
                :disabled="handlingSubmitting || message.handling_status === 'processed'"
                @click="updateMessageHandling(message, 'processed')"
              >
                {{ message.handling_status === 'processed' ? '已处理' : '标记已处理' }}
              </button>
              <button
                class="action-button action-secondary"
                type="button"
                :disabled="handlingSubmitting || message.handling_status === 'ignored'"
                @click="updateMessageHandling(message, 'ignored')"
              >
                {{ message.handling_status === 'ignored' ? '已忽略' : '忽略' }}
              </button>
            </div>
          </div>
          <div v-if="messageHasMore || messagePage > 1" class="pagination-bar">
            <button v-if="messagePage > 1" class="secondary" type="button" :disabled="messageLoadingMore" @click="loadPreviousMessages">上一页</button>
            <span>第 {{ messagePage }} 页 · 每页 20 条</span>
            <button class="secondary" type="button" :disabled="messageLoadingMore || !messageHasMore" @click="loadMoreMessages">下一页</button>
          </div>
        </div>
      </section>

      <section v-if="selectedInquiry" class="detail-panel panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">链路详情 · fixture #{{ selectedInquiry.id }}</p>
            <h2>{{ selectedInquiry.customer_nickname || selectedInquiry.customer_contact }}</h2>
          </div>
          <span class="status-pill" :class="connectionStatusClass(accountStatus(selectedInquiry.source_channel_account_id))">{{ connectionStatusLabel(accountStatus(selectedInquiry.source_channel_account_id)) }}</span>
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
    </template>
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
.inbox-filters { display: flex; flex-wrap: wrap; gap: 8px; padding: 0 20px 10px; }
.inbox-filters select { min-width: 0; padding: 7px 8px; color: #172033; background: white; border: 1px solid #cbd6f4; border-radius: 7px; }
.status-warning { color: #9a2f3b; font-size: 11px; font-weight: 700; }
.subsection { margin: 25px 20px 0; padding-top: 20px; border-top: 1px solid #e5eaf2; }
.message-row { padding: 11px 0; border-top: 1px solid #edf0f5; font-size: 13px; }
.message-row p { margin: 5px 0 0; line-height: 1.5; white-space: pre-wrap; overflow-wrap: anywhere; }
.message-preview { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; overflow: hidden; }
.message-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 7px; }
.load-more-messages { display: block; width: 100%; margin-top: 12px; }
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

/* Inbox refresh: a quiet ledger surface with a clear top-to-bottom work path. */
:root {
  color: #20272d;
  background: #eef0f2;
  letter-spacing: 0;
}
body { background: #eef0f2; }
.workspace { width: min(1320px, calc(100% - 56px)); padding: 30px 0 72px; }
.topbar { align-items: flex-end; margin-bottom: 28px; }
.eyebrow { color: #68727b; letter-spacing: .1em; }
h1 { color: #20272d; font-size: clamp(30px, 4vw, 46px); line-height: 1.05; letter-spacing: 0; }
h2 { color: #20272d; font-size: 22px; letter-spacing: 0; }
h3 { color: #20272d; }
.current-user { color: #66717a; }
.panel, .notice { border: 1px solid #d7dde1; border-radius: 8px; box-shadow: none; }
.content-grid { display: flex; flex-direction: column; gap: 18px; margin-top: 24px; }
.analysis-strip { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; margin-top: 0; border-top: 1px solid #c8d0d5; border-bottom: 1px solid #c8d0d5; }
.overview-heading { grid-column: 1 / -1; display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; padding: 22px 20px 18px; background: #eef0f2; }
.overview-heading h2 { margin: 0; }
.overview-heading .eyebrow { margin-bottom: 7px; }
.overview-note { color: #68727b; font-size: 12px; }
.analysis-card { min-height: 116px; gap: 8px; padding: 19px 20px; background: #f8f9fa; border: 0; border-right: 1px solid #d7dde1; border-radius: 0; }
.analysis-card:last-child { border-right: 0; }
.analysis-card span { color: #68727b; font-size: 12px; font-weight: 650; letter-spacing: .04em; text-transform: uppercase; }
.analysis-card strong { color: #20272d; font-size: 28px; font-weight: 700; }
.analysis-card small { color: #68727b; font-size: 12px; line-height: 1.4; }
.inbox-panel { padding: 0; overflow: visible; }
.inbox-panel > .panel-heading { padding: 22px 24px 10px; }
.inbox-panel > .panel-heading p { margin: 5px 0 0; color: #68727b; font-size: 13px; }
.count { min-width: 30px; height: 30px; border-radius: 4px; color: #fff; background: #20272d; }
.inbox-filters { align-items: center; gap: 10px; padding: 12px 24px 18px; border-bottom: 1px solid #d7dde1; }
.inbox-filters::before { content: "筛选"; color: #68727b; font-size: 12px; font-weight: 700; }
.inbox-filters select, .transfer-form select { min-height: 36px; padding: 7px 30px 7px 10px; color: #20272d; background: #fff; border: 1px solid #bfc8ce; border-radius: 4px; }
.subsection { margin: 0; padding: 20px 24px 24px; border-top: 0; }
.subsection > .panel-heading.compact { padding: 0 0 12px; }
.subsection > .panel-heading.compact h3 { margin: 0; }
.message-row { display: grid; grid-template-columns: minmax(190px, .65fr) minmax(0, 1.7fr) auto; column-gap: 18px; align-items: start; padding: 16px 0; border-top: 1px solid #e3e7e9; }
.message-meta { grid-column: 1; display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 8px; min-width: 0; }
.message-meta strong { flex-basis: 100%; color: #20272d; font-size: 13px; }
.message-meta .sender, .message-meta .meta-time, .message-meta .state-label { color: #68727b; font-size: 12px; line-height: 1.45; }
.message-meta .state-label { color: #1d5fbf; font-weight: 700; }
.message-meta .ingestion-state { color: #68727b; font-weight: 600; }
.message-row p { grid-column: 2; grid-row: 1; margin: 0; color: #344047; line-height: 1.55; }
.message-row .message-actions { grid-column: 3; grid-row: 1 / span 2; justify-content: flex-end; align-items: flex-start; margin-top: 0; }
.message-row .channel-mark { display: inline-flex; width: fit-content; margin-top: 2px; padding: 3px 6px; color: #1d5fbf; background: #e8f0fb; border-radius: 3px; font-size: 11px; font-weight: 800; }
.message-row .message-preview { grid-column: 2; }
.message-actions { gap: 8px; }
.action-button, .primary, .secondary { min-height: 36px; padding: 8px 12px; border-radius: 4px; font-size: 13px; font-weight: 700; cursor: pointer; }
.action-button { border: 1px solid #bfc8ce; }
.action-primary, .primary { color: #fff; background: #20272d; border-color: #20272d; }
.action-primary:hover, .primary:hover { background: #1d5fbf; border-color: #1d5fbf; }
.action-secondary, .secondary { color: #20272d; background: #fff; border-color: #bfc8ce; }
.action-secondary:hover, .secondary:hover { color: #1d5fbf; border-color: #1d5fbf; }
.action-button:disabled, .primary:disabled, .secondary:disabled { color: #89939b; background: #edf0f2; border-color: #d4dade; cursor: not-allowed; }
.pagination-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 18px; padding-top: 16px; border-top: 1px solid #d7dde1; }
.pagination-bar button { min-height: 34px; padding: 7px 11px; color: #20272d; background: #fff; border: 1px solid #bfc8ce; border-radius: 4px; cursor: pointer; }
.pagination-bar button:disabled { color: #9aa3aa; background: #edf0f2; cursor: not-allowed; }
.pagination-bar span { color: #68727b; font-size: 12px; }
.detail-panel { padding: 26px 30px; }
.detail-panel > .panel-heading { align-items: flex-start; }
.detail-panel > .panel-heading p { margin: 6px 0 0; color: #68727b; font-size: 13px; }
.facts-grid { gap: 0; margin: 24px 0; border-top: 1px solid #d7dde1; border-bottom: 1px solid #d7dde1; }
.facts-grid div { padding: 14px 16px; background: #f8f9fa; border-right: 1px solid #d7dde1; border-radius: 0; }
.facts-grid div:last-child { border-right: 0; }
.facts-grid strong { color: #20272d; }
.detail-section { border-color: #d7dde1; }
.transfer-form { grid-template-columns: minmax(180px, 1fr) minmax(180px, 1fr) auto; }
.transfer-form .primary { grid-column: auto; }
.empty-state { min-height: 230px; background: #f8f9fa; }
@media (max-width: 800px) {
  .workspace { width: min(100% - 32px, 1320px); }
  .analysis-strip { grid-template-columns: repeat(2, 1fr); }
  .analysis-card:nth-child(2) { border-right: 0; }
  .analysis-card:nth-child(-n + 2) { border-bottom: 1px solid #d7dde1; }
  .message-row { grid-template-columns: 1fr; gap: 7px; }
  .message-row .message-meta, .message-row p, .message-row .message-preview, .message-row .message-actions, .message-row .channel-mark { grid-column: 1; grid-row: auto; }
  .message-row .message-actions { justify-content: flex-start; margin-top: 7px; }
  .message-row .channel-mark { margin-top: 0; }
  .pagination-bar { align-items: stretch; flex-direction: column; }
}
@media (max-width: 480px) {
  .workspace { width: min(100% - 24px, 1320px); padding-top: 22px; }
  .topbar { align-items: flex-start; flex-direction: column; }
  .analysis-strip { grid-template-columns: 1fr; }
  .analysis-card, .analysis-card:nth-child(2) { border-right: 0; border-bottom: 1px solid #d7dde1; }
  .analysis-card:last-child { border-bottom: 0; }
  .inbox-panel > .panel-heading, .inbox-filters, .subsection { padding-left: 16px; padding-right: 16px; }
  .detail-panel { padding: 20px 16px; }
  .facts-grid { grid-template-columns: 1fr; }
  .facts-grid div { border-right: 0; border-bottom: 1px solid #d7dde1; }
  .facts-grid div:last-child { border-bottom: 0; }
  .transfer-form { grid-template-columns: 1fr; }
  .transfer-form .primary { grid-column: 1; }
}

/* Current workspace: a compact operations desk, ordered by the decision a user makes next. */
:root {
  color: #1f2933;
  background: #f4f6f7;
  font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", system-ui, sans-serif;
}
body { background: #f4f6f7; }
.workspace { width: min(1280px, calc(100% - 64px)); padding: 28px 0 64px; }
.topbar { align-items: center; min-height: 48px; margin-bottom: 30px; }
.topbar > div:first-child .eyebrow,
.content-grid .eyebrow { display: none; }
h1 { margin: 0; color: #1f2933; font-size: 26px; font-weight: 700; line-height: 1.25; }
h2 { font-size: 18px; font-weight: 700; line-height: 1.35; }
h3 { font-size: 14px; font-weight: 700; }
.topbar-actions { gap: 8px; }
.current-user { margin-right: 8px; color: #52606d; font-size: 13px; }
.topbar .link-button { color: #52606d; text-decoration: none; }
.topbar .link-button:hover { color: #c0392b; }

.content-grid { gap: 28px; margin-top: 0; }
.analysis-strip { grid-template-columns: repeat(5, minmax(0, 1fr)); border: 0; background: transparent; }
.overview-heading { align-items: center; padding: 0 0 12px; background: transparent; }
.overview-heading h2 { font-size: 17px; }
.overview-note { color: #6b7785; font-size: 13px; }
.analysis-card { min-height: 98px; padding: 14px 16px; background: #ffffff; border: 1px solid #e1e7ea; border-right: 0; }
.analysis-card:first-of-type { border-radius: 7px 0 0 7px; }
.analysis-card:last-child { border-right: 1px solid #e1e7ea; border-radius: 0 7px 7px 0; }
.analysis-card span { color: #62707c; font-size: 12px; font-weight: 500; letter-spacing: 0; text-transform: none; }
.analysis-card strong { color: #1f2933; font-size: 22px; font-weight: 700; line-height: 1.25; font-variant-numeric: tabular-nums; }
.analysis-card small { color: #74818c; font-size: 12px; }

.panel { border-color: #dfe6e9; border-radius: 8px; background: #ffffff; }
.inbox-panel > .panel-heading { align-items: center; padding: 24px 26px 16px; }
.inbox-panel > .panel-heading h2 { margin: 0; font-size: 20px; }
.count { min-width: auto; height: 28px; padding: 0 9px; border-radius: 4px; color: #165d68; background: #e5f3f4; font-size: 12px; font-weight: 700; }
.inbox-filters { gap: 20px; padding: 14px 26px 18px; background: #fafbfb; border-top: 1px solid #edf0f1; border-bottom: 1px solid #e5eaec; }
.inbox-filters::before { display: none; }
.filter-group { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.filter-group > span { color: #52606d; font-size: 13px; font-weight: 700; }
.inbox-filters select, .transfer-form select { min-height: 34px; padding: 6px 28px 6px 9px; border-color: #cbd5d9; color: #334e57; font-size: 13px; }
.inquiry-row { padding: 14px 26px; border-color: #eef1f2; }
.inquiry-row:hover { background: #f7fbfb; }
.inquiry-row.selected { background: #eef8f8; box-shadow: inset 3px 0 0 #147a85; }
.inquiry-row strong { color: #243b44; font-size: 14px; }
.status { color: #147a85; font-size: 12px; font-weight: 700; }
.channel, .preview { color: #667681; font-size: 12px; }
.subsection { margin: 0; padding: 26px; border-top: 8px solid #f4f6f7; }
.message-heading { align-items: center; padding-bottom: 14px !important; }
.message-heading h2 { margin: 0; font-size: 18px; }
.subsection .inbox-filters { margin: 0 -26px; padding-left: 26px; padding-right: 26px; }
.message-row { grid-template-columns: 220px minmax(0, 1fr) auto; column-gap: 24px; padding: 18px 0; border-color: #e8edef; }
.message-meta { align-content: start; gap: 5px 8px; }
.message-meta strong { color: #243b44; font-size: 14px; line-height: 1.35; }
.message-meta .sender, .message-meta .meta-time, .message-meta .state-label { font-size: 12px; }
.message-meta .state-label { color: #147a85; }
.message-row p { color: #334e57; font-size: 14px; line-height: 1.65; }
.message-row .channel-mark { padding: 3px 6px; color: #165d68; background: #e5f3f4; font-size: 11px; }
.message-actions { max-width: 244px; gap: 6px; }
.action-button, .primary, .secondary { min-height: 34px; padding: 7px 10px; border-radius: 4px; font-size: 12px; font-weight: 700; }
.action-primary, .primary { background: #202a31; border-color: #202a31; }
.action-primary:hover, .primary:hover { background: #165d68; border-color: #165d68; }
.action-secondary, .secondary { color: #40535c; border-color: #cbd5d9; }
.action-secondary:hover, .secondary:hover { color: #165d68; border-color: #82b7bd; background: #f5fbfb; }
.pagination-bar { justify-content: flex-start; min-height: 44px; margin-top: 0; padding: 16px 0 0; border-top: 0; }
.pagination-bar span { margin-right: auto; color: #687782; font-size: 12px; }
.pagination-bar button { min-width: 72px; }
.pagination-bar button:last-child { order: 3; }

.detail-panel { padding: 26px; }
.detail-panel > .panel-heading { padding: 0 0 16px; }
.detail-panel > .panel-heading h2 { font-size: 20px; }
.facts-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 18px 0 22px; border: 1px solid #e1e7ea; border-radius: 6px; overflow: hidden; }
.facts-grid div { padding: 14px 16px; background: #fafbfb; }
.facts-grid span, .contact-list dt { color: #677681; font-size: 12px; }
.facts-grid strong { color: #243b44; font-size: 14px; }
.detail-section { padding: 20px 0; }
.detail-section h3 { margin-bottom: 12px; }
.contact-list dd { color: #334e57; font-size: 14px; }

@media (max-width: 1000px) {
  .analysis-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .analysis-card { border-right: 1px solid #e1e7ea; border-radius: 7px; }
  .message-row { grid-template-columns: 180px minmax(0, 1fr); }
  .message-row .message-actions { grid-column: 2; grid-row: 2; justify-content: flex-start; max-width: none; margin-top: 12px; }
}
@media (max-width: 700px) {
  .workspace { width: min(100% - 32px, 1280px); padding-top: 20px; }
  .topbar { align-items: flex-start; flex-direction: column; gap: 16px; }
  .topbar-actions { width: 100%; flex-wrap: wrap; }
  .current-user { width: 100%; }
  .analysis-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .overview-heading { grid-column: 1 / -1; align-items: flex-start; flex-direction: column; gap: 4px; }
  .analysis-card, .analysis-card:first-of-type, .analysis-card:last-child { min-height: 88px; border: 1px solid #e1e7ea; border-radius: 7px; }
  .inbox-panel > .panel-heading, .subsection, .detail-panel { padding-left: 18px; padding-right: 18px; }
  .inbox-filters, .subsection .inbox-filters { margin-left: -18px; margin-right: -18px; padding-left: 18px; padding-right: 18px; }
  .message-row { grid-template-columns: 1fr; gap: 8px; }
  .message-row .message-meta, .message-row p, .message-row .message-preview, .message-row .message-actions { grid-column: 1; grid-row: auto; }
  .message-row .message-actions { margin-top: 6px; }
  .facts-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .facts-grid div:nth-child(2) { border-right: 0; }
  .facts-grid div:nth-child(-n + 2) { border-bottom: 1px solid #d7dde1; }
}
@media (max-width: 440px) {
  h1 { font-size: 23px; }
  .analysis-strip { grid-template-columns: 1fr; }
  .analysis-card { min-height: auto; }
  .filter-group { width: 100%; align-items: flex-start; flex-direction: column; }
  .filter-group select { width: 100%; }
  .message-actions { max-width: none; }
  .action-button { flex: 1 1 calc(50% - 6px); }
  .facts-grid { grid-template-columns: 1fr; }
  .facts-grid div, .facts-grid div:nth-child(2) { border-right: 0; border-bottom: 1px solid #d7dde1; }
  .facts-grid div:last-child { border-bottom: 0; }
}

/* Interaction feedback stays local to the object being worked on. */
.analysis-card:nth-child(2) { border-radius: 7px 0 0 7px; }
button, select, .inquiry-row, .message-row, .panel {
  transition: background-color 160ms ease, border-color 160ms ease, color 160ms ease, opacity 160ms ease, transform 120ms ease;
}
button:not(:disabled):active { transform: translateY(1px); }
button:focus-visible, select:focus-visible, .inquiry-row:focus-visible {
  outline: 3px solid rgba(20, 122, 133, .28);
  outline-offset: 2px;
}
.inquiry-row { position: relative; }
.inquiry-row:hover { transform: translateX(2px); }
.message-row { position: relative; }
.message-row:hover { background: #fbfdfd; }
.message-row:hover::before {
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: -10px;
  width: 2px;
  background: #82b7bd;
  content: "";
}
.is-refreshing .inbox-filters { background: #f2f9f9; }
.refresh-state { margin: 10px 26px 0; color: #165d68; font-size: 12px; }
.inline-feedback { margin: 12px 0 2px; padding: 9px 11px; border-radius: 4px; font-size: 13px; line-height: 1.45; animation: feedback-in 160ms ease-out; }
.inline-feedback.success { color: #135c44; background: #eef8f2; }
.inline-feedback.error { color: #a12e25; background: #fff2f0; }
.inline-feedback a { color: inherit; font-weight: 700; }
.action-primary.is-opening { cursor: progress; opacity: .78; }
.connection-ready { color: #135c44; font-size: 13px; font-weight: 700; }
@keyframes feedback-in {
  from { opacity: 0; transform: translateY(-3px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
@media (max-width: 700px) {
  .refresh-state { margin-left: 18px; margin-right: 18px; }
  .message-row:hover { transform: none; }
}
</style>
