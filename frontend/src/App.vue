<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import {
  ApiError,
  inboxApi,
  type ChannelAccount,
  type Inquiry,
  type InquiryLinkCandidates,
  type InternalAnalysis,
  type Message,
  type OperationLog,
  type RefetchCheck,
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

type MessageContent = Awaited<ReturnType<typeof inboxApi.getMessageContent>>
const INQUIRY_PAGE_SIZE = 12

const accounts = ref<ChannelAccount[]>([])
const messages = ref<Message[]>([])
const messagePage = ref(1)
const messageHasMore = ref(false)
const messageLoadingMore = ref(false)
const canLoadMoreMessages = computed(() => messageHasMore.value && messages.value.length >= 20)
const expandedMessageIds = ref<Set<number>>(new Set())
const fullMessageContentIds = ref<Set<number>>(new Set())
const collapsedGroupKeys = ref<Set<string>>(new Set())
const contentLoadingMessageIds = ref<Set<number>>(new Set())
const messageContent = ref<Record<number, MessageContent>>({})
const messageHandlingFilter = ref('pending')
const messageIngestionFilter = ref('')
const messageAssignmentFilter = ref('all')
const processedMessages = ref<Message[]>([])
const ignoredMessages = ref<Message[]>([])
const processedBoxOpen = ref(false)
const archiveOpen = ref(false)
const actionToast = ref<{ text: string; kind: 'processed' | 'ignored' } | null>(null)
let actionToastTimer: number | undefined
const messageFeedback = ref<Record<number, { text: string; kind: 'success' | 'error' }>>({})
const messageFeedbackTimers = new Map<number, number>()
const operationLogOpen = ref(false)
const operationLogs = ref<OperationLog[]>([])
const operationLogLoading = ref(false)
const operationLogInquiryId = ref<number | null>(null)
const messageChannelAccountFilter = ref('')
const inquiryStatusFilter = ref('')
const inquiryHandlingFilter = ref('')
const filterLoading = ref(false)
const inquiries = ref<Inquiry[]>([])
const workspaceView = ref<'messages' | 'review' | 'customers' | 'customerMessages'>('messages')
const inquiryPage = ref(1)
const inquiryHasMore = ref(false)
const inquiryTotalCount = ref(0)
const inquiryTotalPages = computed(() => Math.max(1, Math.ceil(inquiryTotalCount.value / INQUIRY_PAGE_SIZE)))
const analysis = ref<InternalAnalysis | null>(null)
const transferTargets = ref<TransferTarget[]>([])
const selectedInquiryId = ref<number | null>(null)
const selectedSalesUserId = ref<number | null>(null)
const selectedBusinessType = ref<'inquiry' | 'after_sales' | null>(null)
const selectedMessageId = ref<number | null>(null)
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
const linkReviewMessageId = ref<number | null>(null)
const linkReviewCandidates = ref<InquiryLinkCandidates | null>(null)
const linkReviewLoading = ref(false)
const linkReviewError = ref('')
let linkReviewRequestId = 0
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
const refetchChecks = ref<Record<number, RefetchCheck>>({})
const refetchCheckingAccountIds = ref<Set<number>>(new Set())
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
const linkReviewMessage = computed(() => messages.value.find((message) => message.id === linkReviewMessageId.value) ?? null)
const selectedInquiryIndex = computed(() => inquiries.value.findIndex((item) => item.id === selectedInquiryId.value))
const isInquiryView = computed(() => workspaceView.value === 'review' || workspaceView.value === 'customers')

async function switchWorkspaceView(view: 'messages' | 'review' | 'customers' | 'customerMessages') {
  workspaceView.value = view
  inquiryPage.value = 1
  inquiryHandlingFilter.value = view === 'review' ? 'pending' : ''
  selectedMessageId.value = null
  if (view === 'messages' || view === 'customerMessages') {
    messageAssignmentFilter.value = view === 'customerMessages' ? 'assigned' : 'all'
    messageHandlingFilter.value = 'pending'
    messageIngestionFilter.value = ''
    messageChannelAccountFilter.value = ''
  }
  selectedInquiryId.value = null
  await loadWorkspace()
}

async function openCustomerMessage(messageId: number) {
  await switchWorkspaceView('customerMessages')
  try {
    const message = await inboxApi.getMessage(messageId)
    if (!messages.value.some((item) => item.id === messageId)) messages.value = [message, ...messages.value]
    const groupKey = messageGroupKey(message)
    const expandedGroups = new Set(collapsedGroupKeys.value)
    expandedGroups.delete(groupKey)
    collapsedGroupKeys.value = expandedGroups
    selectedMessageId.value = messageId
    await nextTick()
    document.getElementById(`message-${messageId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '客户消息加载失败。'
  }
}

async function goToInquiryPage(page: number, preferredIndex?: number) {
  const targetPage = Math.max(1, Math.min(page, inquiryTotalPages.value))
  if (targetPage === inquiryPage.value || filterLoading.value) return
  const keepDetailOpen = selectedInquiryId.value !== null
  const targetIndex = preferredIndex ?? Math.max(0, selectedInquiryIndex.value)
  inquiryPage.value = targetPage
  const loaded = await loadWorkspace()
  if (loaded && keepDetailOpen) {
    selectedInquiryId.value = inquiries.value[Math.min(targetIndex, inquiries.value.length - 1)]?.id ?? null
  }
}

function resetInquiryFilters() {
  inquiryPage.value = 1
  selectedInquiryId.value = null
  void loadWorkspace()
}

async function moveInquiry(delta: number) {
  const index = selectedInquiryIndex.value + delta
  if (index >= 0 && index < inquiries.value.length) {
    selectInquiry(inquiries.value[index].id)
  } else if (delta > 0 && inquiryHasMore.value) {
    await goToInquiryPage(inquiryPage.value + 1, 0)
  } else if (delta < 0 && inquiryPage.value > 1) {
    await goToInquiryPage(inquiryPage.value - 1, INQUIRY_PAGE_SIZE - 1)
  }
}

const accountById = computed(() =>
  new Map(accounts.value.map((account) => [account.id, account])),
)

const timeline = computed(() => {
  if (!selectedInquiry.value) return []
  const inquiry = selectedInquiry.value
  // The aggregate hides global timestamps when some channel sources are not
  // visible; only display timestamps returned under that visibility contract.
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

function messageContentFor(messageId: number) {
  return messageContent.value[messageId]
}

function providerDisplayName(provider: string | null | undefined) {
  const value = provider || ''
  if (value.includes('gmail')) return 'Gmail'
  if (value.includes('outlook')) return 'Outlook'
  if (value.includes('whatsapp')) return 'WhatsApp'
  return 'provider'
}

type ContentSourceState = { text: string; tone: 'ok' | 'info' | 'warn' }

/** 明确区分实时回源成功、持久化快照回放，以及每一种可诊断的回源失败。 */
function contentSourceState(payload: MessageContent | null | undefined): ContentSourceState {
  if (!payload) return { text: '', tone: 'info' }
  const name = providerDisplayName(payload.provider)
  const savedAt = payload.source.snapshot_at ? formatTime(payload.source.snapshot_at) : '入库时'
  if (payload.source.live_refetch) {
    return { text: `已从 ${name} 实时回源校验；展示安全解析后的原文（${savedAt} 存证）`, tone: 'ok' }
  }
  switch (payload.source.fallback_reason) {
    case 'persisted_snapshot_replayed':
      return { text: `已从持久化入站快照回溯原文（${savedAt} 存证）；${name} 会话离线或缓存未命中，回源链路已降级`, tone: 'info' }
    case 'provider_configuration_missing':
      return { text: `${name} 回源未配置：请检查服务端 OAuth 配置。当前展示入库存证原文（${savedAt}）`, tone: 'warn' }
    case 'provider_credentials_unavailable':
      return { text: `${name} 凭据不可用或无法解密：请核对凭据加密密钥，必要时重新授权。当前展示入库存证原文（${savedAt}）`, tone: 'warn' }
    case 'provider_authorization_failed':
      return { text: `${name} 授权已失效：请在「我的 / 接入账号」重新授权该渠道。当前展示入库存证原文（${savedAt}）`, tone: 'warn' }
    case 'provider_content_empty':
    case 'provider_content_unrenderable':
      return { text: `${name} 未返回可展示正文，当前展示入库存证原文（${savedAt}）`, tone: 'info' }
    case 'provider_refetch_failed':
      return { text: `${name} 实时回源失败（网络或 provider 不可用），请查看 backend 日志；当前展示入库存证原文（${savedAt}）`, tone: 'warn' }
    case 'provider_refetch_unavailable':
      return { text: `当前渠道未配置实时回源，展示入库存证原文（${savedAt}）`, tone: 'info' }
    case 'provider_message_id_missing':
    case 'channel_account_unavailable':
      return { text: `消息缺少回源所需的 provider 标识，展示入库存证原文（${savedAt}）`, tone: 'info' }
    default:
      return { text: `已从持久化入站快照回溯原文（${savedAt} 存证）；${name} 实时校验未执行`, tone: 'info' }
  }
}

function toggleFullMessageContent(messageId: number) {
  const next = new Set(fullMessageContentIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  fullMessageContentIds.value = next
}

/** 展开正文时按收起全文的初始状态展示，避免下次查看原文直接落到展开全文。 */
function toggleOriginalView(messageId: number) {
  if (expandedMessageIds.value.has(messageId)) {
    const next = new Set(expandedMessageIds.value)
    next.delete(messageId)
    expandedMessageIds.value = next
    const nextFull = new Set(fullMessageContentIds.value)
    nextFull.delete(messageId)
    fullMessageContentIds.value = nextFull
  } else {
    void viewMessageContent(messageId)
  }
}

function toggleMessageGroup(groupKey: string) {
  const next = new Set(collapsedGroupKeys.value)
  if (next.has(groupKey)) next.delete(groupKey)
  else next.add(groupKey)
  collapsedGroupKeys.value = next
}

async function refreshAnalysisCounts() {
  try {
    analysis.value = await inboxApi.getInternalAnalysis()
  } catch {
    // 计数刷新失败不影响当前操作结果展示。
  }
}

function showActionToast(text: string, kind: 'processed' | 'ignored') {
  if (actionToastTimer !== undefined) window.clearTimeout(actionToastTimer)
  actionToast.value = { text, kind }
  actionToastTimer = window.setTimeout(() => {
    actionToast.value = null
    actionToastTimer = undefined
  }, 2000)
}

function showMessageFeedback(messageId: number, text: string, kind: 'success' | 'error' = 'success') {
  const previous = messageFeedbackTimers.get(messageId)
  if (previous !== undefined) window.clearTimeout(previous)
  messageFeedback.value = { ...messageFeedback.value, [messageId]: { text, kind } }
  const timer = window.setTimeout(() => {
    const next = { ...messageFeedback.value }
    delete next[messageId]
    messageFeedback.value = next
    messageFeedbackTimers.delete(messageId)
  }, 2000)
  messageFeedbackTimers.set(messageId, timer)
}

async function openOperationLogs(inquiryId?: number) {
  operationLogOpen.value = true
  operationLogInquiryId.value = inquiryId ?? null
  operationLogLoading.value = true
  try {
    operationLogs.value = await inboxApi.getOperationLogs(inquiryId)
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '操作记录加载失败。'
  } finally {
    operationLogLoading.value = false
  }
}

async function openOperationLogObject(record: OperationLog) {
  if (record.object_type !== 'message' || record.object_id === null) return
  operationLogOpen.value = false
  await openCustomerMessage(record.object_id)
}

function moveMessageToBox(updated: Message) {
  messages.value = messages.value.filter((item) => item.id !== updated.id)
  if (updated.handling_status === 'processed') {
    processedMessages.value = [updated, ...processedMessages.value.filter((item) => item.id !== updated.id)]
  } else if (updated.handling_status === 'ignored') {
    ignoredMessages.value = [updated, ...ignoredMessages.value.filter((item) => item.id !== updated.id)]
  }
}

async function loadArchive() {
  try {
    const [processed, ignored] = await Promise.all([
      inboxApi.getMessages(queryString({ handling_status: 'processed', page: '1', page_size: '100', sort: 'occurred_at', descending: 'true' })),
      inboxApi.getMessages(queryString({ handling_status: 'ignored', page: '1', page_size: '100', sort: 'occurred_at', descending: 'true' })),
    ])
    processedMessages.value = processed.items
    ignoredMessages.value = ignored.items
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '归档箱加载失败，请稍后重试。'
  }
}

async function openLinkReview(messageId: number) {
  const requestId = ++linkReviewRequestId
  linkReviewMessageId.value = messageId
  linkReviewCandidates.value = null
  linkReviewLoading.value = true
  linkReviewError.value = ''
  actionError.value = ''
  try {
    const candidates = await inboxApi.getMessageInquiryCandidates(messageId)
    if (requestId === linkReviewRequestId) linkReviewCandidates.value = candidates
  } catch (cause) {
    if (requestId === linkReviewRequestId) {
      linkReviewError.value = cause instanceof DOMException && cause.name === 'TimeoutError'
        ? '查询超过 15 秒仍未完成，请重试。'
        : cause instanceof Error ? cause.message : '加载归链候选失败，请重试。'
    }
  } finally {
    if (requestId === linkReviewRequestId) linkReviewLoading.value = false
  }
}

function toggleLinkReview(messageId: number) {
  if (linkReviewMessageId.value === messageId && linkReviewCandidates.value && !linkReviewLoading.value) {
    closeLinkReview()
    return
  }
  void openLinkReview(messageId)
}

function retryLinkReview() {
  if (linkReviewMessageId.value !== null) void openLinkReview(linkReviewMessageId.value)
}

function closeLinkReview() {
  linkReviewRequestId += 1
  linkReviewMessageId.value = null
  linkReviewCandidates.value = null
  linkReviewError.value = ''
  linkReviewLoading.value = false
}

async function confirmMessageLink(inquiryId: number, confirmIdentity = false) {
  if (linkReviewMessageId.value === null) return
  handlingSubmitting.value = true
  actionError.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.linkMessageToInquiry(inquiryId, linkReviewMessageId.value, csrf.csrf_token, confirmIdentity)
    actionMessage.value = confirmIdentity
      ? '已人工确认联系人身份并关联到所选链路。'
      : '消息已关联到所选链路。'
    closeLinkReview()
    await loadWorkspace()
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '消息关联失败。'
  } finally {
    handlingSubmitting.value = false
  }
}

async function retryMessageOverview(messageId: number) {
  handlingSubmitting.value = true
  actionError.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    const updated = await inboxApi.retryMessageOverview(messageId, csrf.csrf_token)
    messages.value = messages.value.map((item) => item.id === messageId ? updated : item)
    showMessageFeedback(messageId, '已提交重新生成。')
    if (updated.overview?.status === 'pending') void pollMessageOverview(messageId)
  } catch (cause) {
    showMessageFeedback(messageId, cause instanceof Error ? cause.message : '中文概要重试失败。', 'error')
  } finally {
    handlingSubmitting.value = false
  }
}

async function pollMessageOverview(messageId: number, attempt = 0): Promise<void> {
  if (attempt >= 12 || !messages.value.some((item) => item.id === messageId)) return
  await new Promise((resolve) => window.setTimeout(resolve, 1500))
  try {
    const updated = await inboxApi.getMessage(messageId)
    messages.value = messages.value.map((item) => item.id === messageId ? updated : item)
    if (updated.overview?.status === 'pending') void pollMessageOverview(messageId, attempt + 1)
  } catch {
    // A transient poll failure must not remove or alter the current message.
  }
}

async function restoreArchivedMessage(messageId: number) {
  handlingSubmitting.value = true
  actionError.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.restoreMessage(messageId, csrf.csrf_token)
    actionMessage.value = '消息已恢复到待处理栏。'
    await loadWorkspace()
    await loadArchive()
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '消息恢复失败。'
  } finally {
    handlingSubmitting.value = false
  }
}

async function viewMessageContent(messageId: number) {
  actionError.value = ''
  const nextLoading = new Set(contentLoadingMessageIds.value)
  nextLoading.add(messageId)
  contentLoadingMessageIds.value = nextLoading
  try {
    messageContent.value = {
      ...messageContent.value,
      [messageId]: await inboxApi.getMessageContent(messageId),
    }
    const nextExpanded = new Set(expandedMessageIds.value)
    nextExpanded.add(messageId)
    expandedMessageIds.value = nextExpanded
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '原文查看失败，请稍后重试。'
  } finally {
    const remaining = new Set(contentLoadingMessageIds.value)
    remaining.delete(messageId)
    contentLoadingMessageIds.value = remaining
  }
}

async function loadMoreMessages() {
  if (messageLoadingMore.value || !canLoadMoreMessages.value) return
  messageLoadingMore.value = true
  actionError.value = ''
  try {
    const next = await inboxApi.getMessages(queryString({
      handling_status: messageHandlingFilter.value,
      assignment_status: workspaceView.value === 'customerMessages' ? 'assigned' : messageAssignmentFilter.value,
      ingestion_status: messageIngestionFilter.value,
      ...messageChannelFilterParams(),
      page: String(messagePage.value + 1),
      page_size: '20',
      sort: 'occurred_at',
      descending: 'true',
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
      assignment_status: workspaceView.value === 'customerMessages' ? 'assigned' : messageAssignmentFilter.value,
      ingestion_status: messageIngestionFilter.value,
      ...messageChannelFilterParams(),
      page: String(messagePage.value - 1),
      page_size: '20',
      sort: 'occurred_at',
      descending: 'true',
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
  return account?.external_account_id || (account ? `${channelLabel(account.channel_type)} #${account.id}` : `账号 #${accountId}`)
}

function accountStatus(accountId: number) {
  return accountById.value.get(accountId)?.status
}

function whatsappGroupShortLabel(jid: string) {
  const raw = jid.replace(/@g\.us$/, '')
  return raw.length > 12 ? `${raw.slice(0, 6)}…${raw.slice(-4)}` : raw
}

/**
 * 从 external_message_id 还原 WhatsApp 群聊 JID。
 * ID 规范格式为 `remoteJid:participant:messageId`（与 bridge 的 parseExternalMessageId 一致），
 * 群聊 remoteJid 以 @g.us 结尾。后端目前没有独立的会话/群组字段，
 * 因此只在展示层解析，用于把同一群的消息聚成一条链，不改变任何数据结构。
 */
function whatsappGroupJid(message: Message): string | null {
  if (message.channel_type !== 'whatsapp' || message.is_website_form) return null
  const externalId = message.external_message_id || ''
  const messageSeparator = externalId.lastIndexOf(':')
  const prefix = messageSeparator > 0 ? externalId.slice(0, messageSeparator) : ''
  const participantSeparator = prefix.lastIndexOf(':')
  let remoteJid = participantSeparator > 0 ? prefix.slice(0, participantSeparator) : ''
  if (!remoteJid.endsWith('@g.us')) {
    // 历史 ID 或 participant 内含冒号时，退回按 @g.us 结尾直接截取首段
    const marker = externalId.indexOf('@g.us:')
    remoteJid = marker > 0 ? externalId.slice(0, marker + '@g.us'.length) : ''
  }
  return remoteJid.endsWith('@g.us') ? remoteJid : null
}

/** 展示分组键：群聊优先按群 JID 聚合，避免无联系人身份时退化成「一条消息一组」。 */
function messageGroupKey(message: Message): string {
  if (message.is_website_form) return `website-form:${message.id}`
  if (message.inquiry_id !== null) return `inquiry:${message.inquiry_id}`
  const groupJid = whatsappGroupJid(message)
  if (groupJid) return `group:${message.channel_type}:${groupJid}`
  const identity = message.normalized_customer_contact || message.customer_contact || `#${message.id}`
  return `contact:${message.channel_type}:${identity}`
}

function messageContactLabel(message: Message) {
  if (message.is_website_form) return `官网表单提交 #${message.id}`
  if (message.channel_type !== 'whatsapp') {
    return message.customer_contact || message.customer_nickname || '联系方式未提供'
  }
  const externalId = message.external_message_id || ''
  const groupJid = whatsappGroupJid(message)
  if (groupJid) return `群聊 ${whatsappGroupShortLabel(groupJid)}`
  if (externalId.includes('@g.us')) return '群聊'
  if (message.customer_contact && /^\d{6,15}$/.test(message.customer_contact)) {
    return `+${message.customer_contact}`
  }
  if (externalId.includes('@lid')) return 'WhatsApp 联系人（LID）'
  return 'WhatsApp 联系人'
}

function messageSenderLabel(message: Message) {
  if (message.is_website_form) return '官网表单'
  if (message.channel_type === 'whatsapp') return message.customer_nickname || '发送人未提供'
  return message.customer_nickname || ''
}

type MessageGroupScope = 'inquiry' | 'group' | 'contact'

type MessageGroup = {
  key: string
  scope: MessageGroupScope
  inquiryId: number | null
  contactLabel: string
  messages: Message[]
}

/** 同一询盘 / 同一群聊 / 同一联系人身份的消息合并为一条链，仅做展示合并，不做数据归并。 */
const groupedMessageItems = computed<MessageGroup[]>(() => {
  const groups: MessageGroup[] = []
  const index = new Map<string, MessageGroup>()
  for (const message of messages.value) {
    const key = messageGroupKey(message)
    let group = index.get(key)
    if (!group) {
      group = {
        key,
        scope: key.startsWith('inquiry:') ? 'inquiry' : key.startsWith('group:') ? 'group' : 'contact',
        inquiryId: message.inquiry_id,
        contactLabel: messageContactLabel(message),
        messages: [],
      }
      index.set(key, group)
      groups.push(group)
    }
    group.messages.push(message)
  }
  return groups
})

function messagesForGroup(group: MessageGroup) {
  if (group.messages.length <= 1 || !collapsedGroupKeys.value.has(group.key)) return group.messages
  // 组内按 occurred_at 倒序，[0] 才是最新一条；折叠时应保留最新消息。
  return [group.messages[0]]
}

function messageGroupLabel(group: MessageGroup) {
  if (group.scope === 'inquiry') return `询盘 #${group.inquiryId} 会话 · ${group.messages.length} 条消息`
  if (group.scope === 'group') return `同一群聊会话 · ${group.messages.length} 条消息`
  return `同一联系人会话 · ${group.messages.length} 条消息`
}

/** 行内组别徽标：无论组展开还是折叠，都能看出该消息属于哪个会话组。 */
function groupBadgeLabel(group: MessageGroup, message: Message) {
  const scope = group.scope === 'inquiry'
    ? `询盘 #${group.inquiryId} 会话`
    : group.scope === 'group' ? '群聊会话' : '联系人会话'
  if (collapsedGroupKeys.value.has(group.key)) {
    return `${scope} · 共 ${group.messages.length} 条（已折叠，仅显示最新 1 条）`
  }
  const position = group.messages.indexOf(message) + 1
  return `${scope} · 组内第 ${position}/${group.messages.length} 条`
}

function channelLabel(channelType: string | null | undefined) {
  if (channelType === 'website_form') return '官网表单'
  if (channelType === 'whatsapp') return 'WhatsApp'
  if (channelType === 'outlook') return 'Outlook'
  if (channelType === 'gmail') return 'Gmail'
  return channelType || '未知渠道'
}

function messageChannelFilterParams() {
  const websiteForm = messageChannelAccountFilter.value === 'website_form'
  return {
    channel_account_id: websiteForm ? '' : messageChannelAccountFilter.value,
    channel_type: websiteForm ? 'website_form' : '',
  }
}

function queryString(values: Record<string, string>) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => { if (value) params.set(key, value) })
  return params.toString() ? `?${params.toString()}` : ''
}

function lifecycleStageLabel(stage: Inquiry['lifecycle_stage']) {
  if (stage === 'active') return '活跃'
  if (stage === 'archived_silent') return '归档静默（可恢复）'
  if (stage === 'purge_due') return '超过90天（待清理；未自动删除）'
  return '期限未知'
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

function contactIdentityLabel(state: Message['contact_identity_state']) {
  if (state === 'certain') return '身份已确认'
  if (state === 'forwarded') return '转发来源：需人工确认后关联'
  if (state === 'identity_uncertain') return '身份不确定'
  if (state === 'needs_manual_review') return '待人工核验身份'
  return '不支持的身份'
}

function linkStateLabel(state: Message['link_state']) {
  if (state === 'linked') return '已关联'
  if (state === 'manual_review') return '待人工判断'
  if (state === 'unmatched') return '未匹配'
  return '不适用'
}

function handlingStatusLabel(status: string) {
  if (status === 'pending') return '待处理'
  if (status === 'processed') return '已处理'
  if (status === 'ignored') return '已忽略'
  return status
}

async function runRefetchCheck(accountId: number) {
  if (!accountId) return
  const checking = new Set(refetchCheckingAccountIds.value)
  checking.add(accountId)
  refetchCheckingAccountIds.value = checking
  actionError.value = ''
  try {
    const result = await inboxApi.checkChannelRefetch(accountId)
    refetchChecks.value = { ...refetchChecks.value, [accountId]: result }
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '回源自检失败，请稍后重试。'
  } finally {
    const remaining = new Set(refetchCheckingAccountIds.value)
    remaining.delete(accountId)
    refetchCheckingAccountIds.value = remaining
  }
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

async function loadWorkspace(): Promise<boolean> {
  const initialLoad = accounts.value.length === 0 && messages.value.length === 0 && inquiries.value.length === 0 && analysis.value === null
  if (initialLoad) loading.value = true
  filterLoading.value = true
  error.value = ''
  actionError.value = ''
  unauthorized.value = false

  try {
    const emptyMessagePage = { items: [] as Message[], page: 1, page_size: 20, has_more: false }
    const emptyInquiryPage = { items: [] as Inquiry[], page: 1, page_size: INQUIRY_PAGE_SIZE, has_more: false, total_count: 0 }
    const [nextChannelAccounts, nextMessages, nextInquiries, nextTargets, nextUser] = await Promise.all([
      channelsApi.accounts(),
      isInquiryView.value ? Promise.resolve(emptyMessagePage) : inboxApi.getMessages(queryString({
        handling_status: messageHandlingFilter.value,
        assignment_status: workspaceView.value === 'customerMessages' ? 'assigned' : messageAssignmentFilter.value,
        ingestion_status: messageIngestionFilter.value,
        ...messageChannelFilterParams(),
        needs_review: '',
        page: '1', page_size: '20', sort: 'occurred_at', descending: 'true',
      })),
      isInquiryView.value ? inboxApi.getInquiries(queryString({
        status: workspaceView.value === 'customers' ? 'assigned' : workspaceView.value === 'review' ? 'new' : '',
        handling_status: inquiryHandlingFilter.value,
        page: String(inquiryPage.value), page_size: String(INQUIRY_PAGE_SIZE), sort: 'updated_at', descending: 'true',
      })) : Promise.resolve(emptyInquiryPage),
      isInquiryView.value ? inboxApi.getTransferTargets().catch((cause) => {
        if (cause instanceof ApiError && cause.status === 403) return []
        throw cause
      }) : Promise.resolve([] as TransferTarget[]),
      inboxApi.getCurrentUser(),
    ])
    currentUser.value = nextUser
    accounts.value = nextChannelAccounts
    messages.value = nextMessages.items
    messagePage.value = nextMessages.page
    messageHasMore.value = nextMessages.has_more
    expandedMessageIds.value = new Set()
    fullMessageContentIds.value = new Set()
    messageContent.value = {}
    contentLoadingMessageIds.value = new Set()
    if (archiveOpen.value || processedBoxOpen.value) await loadArchive()
    inquiries.value = nextInquiries.items
    inquiryHasMore.value = nextInquiries.has_more
    inquiryTotalCount.value = nextInquiries.total_count ?? (nextInquiries.has_more ? inquiryPage.value * INQUIRY_PAGE_SIZE + 1 : (inquiryPage.value - 1) * INQUIRY_PAGE_SIZE + nextInquiries.items.length)
    transferTargets.value = nextTargets
    if (!nextInquiries.items.some((inquiry) => inquiry.id === selectedInquiryId.value)) {
      selectedInquiryId.value = null
      selectedSalesUserId.value = null
    }
    return true
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
    return false
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
  gmailError.value = ''
  gmailMessage.value = ''
  try {
    if (!account || account.status === 'revoked') {
      const csrf = await inboxApi.getCsrf()
      await channelsApi.createGmailAccount(csrf.csrf_token)
      if (!await loadWorkspace()) {
        gmailError.value = 'Gmail 账号已初始化，但工作台刷新失败，请刷新后重试。'
        return
      }
      account = accounts.value.find((item) => item.channel_type === 'gmail')
      if (!account) throw new Error('Gmail 账号初始化后不可见，请检查授权范围。')
    }
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

/** 组内统一处理后，把该会话的消息从待办列表移除并同步归档箱内容。 */
function archiveGroupMessages(inquiryId: number) {
  messages.value = messages.value.filter((item) => item.inquiry_id !== inquiryId)
  if (archiveOpen.value || processedBoxOpen.value) void loadArchive()
}

async function updateMessageHandling(message: Message, action: 'processed' | 'ignored') {
  // 已归链消息属于询盘会话：按业务规则必须通过询盘统一处理，单独改消息状态会被后端拒绝。
  if (message.inquiry_id !== null) {
    const group = groupedMessageItems.value.find((item) => item.inquiryId === message.inquiry_id)
    const relatedCount = group?.messages.length ?? 1
    handlingSubmitting.value = true
    actionError.value = ''
    actionMessage.value = ''
    try {
      const csrf = await inboxApi.getCsrf()
      const updated = await inboxApi.updateInquiryHandling(message.inquiry_id, action, csrf.csrf_token)
      archiveGroupMessages(message.inquiry_id)
      const messageCount = updated.messages.length || relatedCount
      showActionToast(
        `询盘 #${message.inquiry_id} 会话的 ${messageCount} 条消息已${action === 'processed' ? '处理' : '忽略'}`,
        action,
      )
      void refreshAnalysisCounts()
    } catch (cause) {
      actionError.value = cause instanceof Error ? cause.message : '状态更新失败，请稍后重试。'
    } finally {
      handlingSubmitting.value = false
    }
    return
  }
  handlingSubmitting.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    const updated = await inboxApi.updateMessageHandling(message.id, action, csrf.csrf_token)
    moveMessageToBox(updated)
    showActionToast(action === 'processed' ? '已处理' : '已忽略', action)
    if (archiveOpen.value || processedBoxOpen.value) await loadArchive()
    await refreshAnalysisCounts()
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
    const updated = await inboxApi.updateInquiryHandling(selectedInquiry.value.id, action, csrf.csrf_token)
    actionMessage.value = action === 'processed' ? '询盘已标记为已处理。' : '询盘已忽略。'
    // 保持当前页面位置：本地替换或移除该询盘，不整页刷新。
    const matchesFilter = !inquiryHandlingFilter.value || inquiryHandlingFilter.value === updated.handling_status
    inquiries.value = matchesFilter
      ? inquiries.value.map((item) => (item.id === updated.id ? updated : item))
      : inquiries.value.filter((item) => item.id !== updated.id)
    if (!inquiries.value.some((inquiry) => inquiry.id === selectedInquiryId.value)) {
      selectedInquiryId.value = inquiries.value[0]?.id ?? null
      selectedSalesUserId.value = null
    }
    await refreshAnalysisCounts()
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '状态更新失败，请稍后重试。'
  } finally {
    handlingSubmitting.value = false
  }
}

async function transferSelectedInquiry() {
  if (!selectedInquiry.value || selectedSalesUserId.value === null || selectedBusinessType.value === null) {
    actionError.value = '请选择业务类型和业务员。'
    actionMessage.value = ''
    return
  }

  transferSubmitting.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.transferInquiry(selectedInquiry.value.id, selectedSalesUserId.value, selectedBusinessType.value, csrf.csrf_token)
    actionMessage.value = '客户链路已分配，正在刷新授权范围内的数据。'
    selectedSalesUserId.value = null
    selectedBusinessType.value = null
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
  void (async () => {
    const loaded = await loadWorkspace()
    if (!loaded) return
    await nextTick()
    if ('requestIdleCallback' in window) {
      window.requestIdleCallback(() => void refreshAnalysisCounts(), { timeout: 2500 })
    } else {
      window.setTimeout(() => void refreshAnalysisCounts(), 800)
    }
  })()
})
</script>

<template>
  <main class="workspace">
    <Transition name="action-toast">
      <div v-if="actionToast" class="action-toast" :class="`toast-${actionToast.kind}`" role="status" aria-live="polite">
        <span class="toast-mark" aria-hidden="true">✓</span>
        <span>{{ actionToast.text }}</span>
      </div>
    </Transition>
    <div v-if="operationLogOpen" class="operation-log-backdrop" @click.self="operationLogOpen = false">
      <section class="operation-log-dialog" role="dialog" aria-modal="true" aria-labelledby="operation-log-title">
        <header>
          <div><p class="eyebrow">操作回溯</p><h2 id="operation-log-title">{{ operationLogInquiryId === null ? '我的操作记录' : `链路 #${operationLogInquiryId} 操作记录` }}</h2></div>
          <button class="secondary" type="button" aria-label="关闭操作记录" @click="operationLogOpen = false">关闭</button>
        </header>
        <p v-if="operationLogLoading" class="empty">正在加载…</p>
        <p v-else-if="operationLogs.length === 0" class="empty">暂无操作记录。</p>
        <div v-else class="operation-log-table-wrap">
          <table class="operation-log-table">
            <thead><tr><th>操作账号</th><th>操作名称</th><th>对象</th><th>时间</th><th>结果</th></tr></thead>
            <tbody>
              <tr v-for="record in operationLogs" :key="record.id">
                <td>{{ record.actor_name }}</td>
                <td>{{ record.operation_name }}</td>
                <td>
                  <button v-if="record.object_type === 'message' && record.object_id !== null" class="operation-object-link" type="button" @click="openOperationLogObject(record)">消息 #{{ record.object_id }} · 查看概要与处理</button>
                  <span v-else>{{ record.object_type === 'inquiry' ? '链路' : '消息' }}{{ record.object_id ? ` #${record.object_id}` : '' }}</span>
                  <small v-if="record.detail">{{ record.detail }}</small>
                </td>
                <td>{{ formatTime(record.created_at) }}</td>
                <td><span class="operation-result" :class="`result-${record.result}`">{{ record.result === 'success' ? '成功' : record.result === 'timeout' ? '超时' : '失败' }}</span></td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
    <header class="topbar">
      <div>
        <p class="eyebrow">{{ profileOpen ? '个人设置' : '运营工作台' }}</p>
        <h1>{{ profileOpen ? '渠道连接' : '消息与客户' }}</h1>
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
        <section class="profile-operations">
          <div><h3>账号操作记录</h3><p>查看当前账号执行的操作及结果。</p></div>
          <button class="secondary" type="button" @click="openOperationLogs()">查看操作记录</button>
        </section>
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
                class="secondary"
                type="button"
                :disabled="refetchCheckingAccountIds.has(channelAccount(channelType)?.id || 0)"
                @click="runRefetchCheck(channelAccount(channelType)?.id || 0)"
              >
                {{ refetchCheckingAccountIds.has(channelAccount(channelType)?.id || 0) ? '自检中…' : '回源自检' }}
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
            <div
              v-if="refetchChecks[channelAccount(channelType)?.id || 0]"
              class="refetch-check-result"
              :class="refetchChecks[channelAccount(channelType)?.id || 0]?.ready ? 'ok' : 'warn'"
            >
              <strong>{{ refetchChecks[channelAccount(channelType)?.id || 0]?.ready ? '实时回源链路可用' : '实时回源不可用' }}</strong>
              <p>{{ refetchChecks[channelAccount(channelType)?.id || 0]?.recommended_action }}</p>
              <ul>
                <li v-for="step in refetchChecks[channelAccount(channelType)?.id || 0]?.steps" :key="step.name">
                  {{ step.ok ? '✓' : '✗' }} {{ step.name }}：{{ step.detail }}
                </li>
              </ul>
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
    <section v-else class="content-grid" :class="{ 'has-selected-inquiry': isInquiryView && selectedInquiry }" data-ui="inbox">
      <nav class="workspace-tabs" aria-label="工作台视图">
        <button type="button" :class="{ active: workspaceView === 'messages' }" @click="switchWorkspaceView('messages')">消息收件箱</button>
        <button type="button" :class="{ active: workspaceView === 'review' }" @click="switchWorkspaceView('review')">待分配</button>
        <button type="button" :class="{ active: workspaceView === 'customers' }" @click="switchWorkspaceView('customers')">客户链路</button>
        <button type="button" :class="{ active: workspaceView === 'customerMessages' }" @click="switchWorkspaceView('customerMessages')">客户消息</button>
      </nav>
      <section class="inbox-panel panel" :class="{ 'is-refreshing': filterLoading, 'inquiry-sidebar': isInquiryView && selectedInquiry }">
        <div v-if="isInquiryView" class="panel-heading">
          <div>
            <p class="eyebrow">运营收件箱</p>
            <h2>{{ workspaceView === 'review' ? '待分配客户' : '已分配客户链路' }}</h2>
            <p v-if="workspaceView === 'review'">按已确认的邮箱或手机号汇总客户，选择业务类型与负责人完成分配。</p>
          </div>
          <span class="count">{{ selectedInquiry ? `第 ${inquiryPage} / ${inquiryTotalPages} 页` : `共 ${inquiryTotalCount} 条 · 第 ${inquiryPage} / ${inquiryTotalPages} 页` }}</span>
        </div>

        <div v-if="isInquiryView" class="inbox-filters">
          <div class="filter-group">
            <span>处理状态</span>
            <select v-model="inquiryHandlingFilter" aria-label="询盘人工状态" @change="resetInquiryFilters">
              <option value="">全部处理状态</option><option value="pending">待处理</option><option value="processed">已处理</option><option value="ignored">已忽略</option>
            </select>
          </div>
        </div>
        <p v-if="isInquiryView && filterLoading" class="refresh-state" role="status">正在刷新当前筛选结果…</p>
        <p v-if="isInquiryView && inquiries.length === 0" class="empty">当前没有符合条件的客户链路。</p>
        <template v-if="isInquiryView">
        <button
          v-for="inquiry in inquiries"
          :key="inquiry.id"
          class="inquiry-row"
          :class="{ selected: inquiry.id === selectedInquiryId }"
          type="button"
          @click="selectInquiry(inquiry.id)"
        >
          <span class="row-topline">
            <strong>{{ inquiry.contact_sources[0]?.customer_nickname || inquiry.contact_sources[0]?.raw_customer_contact || `链路 #${inquiry.id}` }}</strong>
            <span class="status">{{ workspaceView === 'review' ? '待分配' : '已分配' }}</span>
          </span>
          <span class="channel">{{ [...new Set(inquiry.contact_sources.map((source) => source.channel_type).filter(Boolean))].join(' / ') || '来源按授权范围隐藏' }}</span>
          <span class="preview">{{ inquiry.messages.length }} 条当前授权可见的关联消息</span>
        </button>
        <div class="pagination-bar inquiry-pagination">
          <span class="page-progress-label">第 {{ inquiryPage }} / {{ inquiryTotalPages }} 页</span>
          <nav class="page-dots" aria-label="询盘分页">
            <button
              v-for="pageNumber in inquiryTotalPages"
              :key="pageNumber"
              class="page-dot"
              :class="{ active: pageNumber === inquiryPage }"
              type="button"
              :aria-label="`第 ${pageNumber} 页`"
              :aria-current="pageNumber === inquiryPage ? 'page' : undefined"
              :disabled="filterLoading"
              @click="goToInquiryPage(pageNumber)"
            ><span></span></button>
          </nav>
        </div>
        </template>

        <div v-if="!isInquiryView" class="subsection">
          <div class="panel-heading compact message-heading">
            <div>
              <p class="eyebrow">逐条处理</p>
              <h2>{{ workspaceView === 'customerMessages' ? '已分配客户的消息' : '全部消息' }}</h2>
            </div>
            <span class="count">{{ messages.length }} 条</span>
          </div>
          <div class="inbox-filters">
            <div v-if="workspaceView === 'messages'" class="filter-group">
              <span>客户归属</span>
              <select v-model="messageAssignmentFilter" aria-label="客户归属筛选" @change="loadWorkspace">
                <option value="all">全部消息</option><option value="assigned">已归属客户</option><option value="unassigned">未归属客户</option>
              </select>
            </div>
            <div class="filter-group">
              <span>渠道</span>
              <select v-model="messageChannelAccountFilter" aria-label="消息渠道" @change="loadWorkspace">
                <option value="">全部渠道</option>
                <option value="website_form">官网表单</option>
                <option v-for="account in messageChannelAccounts" :key="account.id" :value="String(account.id)">
                  {{ channelLabel(account.channel_type) }}
                </option>
              </select>
            </div>
            <div class="filter-group">
              <span>状态</span>
              <select v-model="messageIngestionFilter" aria-label="消息入站状态" @change="loadWorkspace">
                <option value="">全部入站</option><option value="received">已接收</option><option value="processed">已处理入站</option><option value="failed">入站失败</option>
              </select>
              <select v-model="messageHandlingFilter" aria-label="消息人工状态" @change="loadWorkspace">
                <option value="all">全部人工</option><option value="pending">待处理</option><option value="processed">已处理</option><option value="ignored">已忽略</option>
              </select>
            </div>
          </div>
          <div class="archive-toolbar">
            <button class="secondary" type="button" @click="processedBoxOpen = !processedBoxOpen; (processedBoxOpen || archiveOpen) ? loadArchive() : undefined">
              {{ processedBoxOpen ? '收起已处理箱' : '已处理箱' }}
            </button>
            <button class="secondary" type="button" @click="archiveOpen = !archiveOpen; (processedBoxOpen || archiveOpen) ? loadArchive() : undefined">
              {{ archiveOpen ? '收起归档箱' : '归档箱' }}
            </button>
          </div>
          <p v-if="providerFallback" class="inline-feedback success">
            <a :href="providerFallback.url" target="_blank" rel="noopener noreferrer">{{ providerFallback.label }}</a>
          </p>
          <p v-if="actionError" class="inline-feedback error" role="alert">{{ actionError }}</p>
          <section v-if="processedBoxOpen" class="archive-box">
            <h3>已处理</h3>
            <p v-if="processedMessages.length === 0" class="empty">已处理箱为空。</p>
            <article v-for="archived in processedMessages" :key="archived.id" class="archive-row">
              <div>
                <strong>{{ messageContactLabel(archived) }}</strong>
                <span>已处理 · {{ formatTime(archived.occurred_at) }}</span>
                <p v-if="archived.overview?.status === 'ready'">中文概要：{{ archived.overview.text }}</p>
              </div>
              <button class="secondary" type="button" :disabled="handlingSubmitting" @click="restoreArchivedMessage(archived.id)">恢复到待处理</button>
            </article>
          </section>
          <section v-if="archiveOpen" class="archive-box">
            <h3>已忽略归档</h3>
            <p v-if="ignoredMessages.length === 0" class="empty">归档箱为空。</p>
            <article v-for="archived in ignoredMessages" :key="archived.id" class="archive-row">
              <div>
                <strong>{{ messageContactLabel(archived) }}</strong>
                <span>已忽略 · {{ formatTime(archived.occurred_at) }}</span>
                <p v-if="archived.overview?.status === 'ready'">中文概要：{{ archived.overview.text }}</p>
              </div>
              <button class="secondary" type="button" :disabled="handlingSubmitting" @click="restoreArchivedMessage(archived.id)">恢复到待处理</button>
            </article>
          </section>
          <p v-if="messages.length === 0" class="empty">当前授权范围内没有符合条件的消息。</p>
          <template v-for="group in groupedMessageItems" :key="group.key">
            <section class="message-group" :class="{ 'has-multiple': group.messages.length > 1 }">
            <div v-if="group.messages.length > 1" class="message-group-bar">
              <span class="group-label">{{ messageGroupLabel(group) }} · {{ group.contactLabel }}</span>
              <button class="link-button" type="button" @click="toggleMessageGroup(group.key)">
                {{ collapsedGroupKeys.has(group.key) ? `展开组内其他 ${group.messages.length - 1} 条` : '收起组内消息' }}
              </button>
            </div>
            <div v-for="message in messagesForGroup(group)" :id="`message-${message.id}`" :key="message.id" class="message-row" :class="{ 'is-grouped': group.messages.length > 1, 'is-focused-message': selectedMessageId === message.id }">
            <div class="message-meta">
              <span class="channel-mark" :class="`channel-${message.channel_type}`">{{ message.channel_type === 'website_form' ? 'WF' : message.channel_type === 'whatsapp' ? 'WS' : message.channel_type === 'outlook' ? 'OL' : 'GM' }}</span>
              <strong>{{ messageContactLabel(message) }}</strong>
              <span v-if="messageSenderLabel(message)" class="sender">发送人：{{ messageSenderLabel(message) }}</span>
              <span class="meta-time">{{ formatTime(message.occurred_at) }}</span>
              <span v-if="group.messages.length > 1" class="state-label group-badge" :title="`属于「${messageGroupLabel(group)}」`">{{ groupBadgeLabel(group, message) }}</span>
              <span class="state-label ingestion-state">入站：{{ ingestionStatusLabel(message.ingestion_status) }}</span>
              <span class="state-label">人工：{{ handlingStatusLabel(message.handling_status) }}</span>
              <span class="state-label" :class="message.link_state === 'manual_review' || message.contact_identity_state !== 'certain' ? 'status-warning' : ''">身份：{{ contactIdentityLabel(message.contact_identity_state) }}</span>
              <span class="state-label" :class="message.link_state === 'manual_review' ? 'status-warning' : ''">归链：{{ linkStateLabel(message.link_state) }}</span>
              <span v-if="message.overview?.status === 'pending'" class="state-label">中文概要：生成中</span>
              <span v-else-if="message.overview?.status === 'failed'" class="status-warning">中文概要：待生成</span>
              <span v-if="accountStatus(message.channel_account_id) === 'blocked'" class="status-warning">渠道阻塞</span><span v-if="accountStatus(message.channel_account_id) === 'revoked'" class="status-warning">渠道已撤销</span>
            </div>
            <template v-if="!expandedMessageIds.has(message.id)">
              <p v-if="message.overview?.status === 'ready'" class="message-overview">中文概要：{{ message.overview.text }}</p>
              <p v-else-if="message.overview?.status === 'failed'" class="message-overview fallback">规则摘录，非 AI 概要：{{ message.display_excerpt || '（无正文）' }}</p>
              <p v-else class="message-preview">{{ message.display_excerpt || '（无正文）' }}</p>
            </template>
            <div v-else class="message-content-view">
              <p v-if="messageContentFor(message.id)" class="message-original-preview">
                <span class="content-label">安全原文预览</span>
                {{ messageContentFor(message.id)?.preview_text || '（无正文）' }}
              </p>
              <p v-else class="message-preview">{{ message.display_excerpt || '（无正文）' }}</p>
              <p v-if="messageContentFor(message.id)?.can_expand && fullMessageContentIds.has(message.id)" class="message-full-content">
                {{ messageContentFor(message.id)?.full_text }}
              </p>
              <button
                v-if="messageContentFor(message.id)?.can_expand"
                class="link-button content-expand-link"
                type="button"
                @click="toggleFullMessageContent(message.id)"
              >
                {{ fullMessageContentIds.has(message.id) ? '收起全文' : '展示全文' }}
              </button>
              <p v-if="messageContentFor(message.id)" class="content-source-note" :class="`tone-${contentSourceState(messageContentFor(message.id)).tone}`" role="status">
                {{ contentSourceState(messageContentFor(message.id)).text }}
              </p>
              <p v-if="messageContentFor(message.id) && contentSourceState(messageContentFor(message.id)).tone === 'warn'" class="content-source-hint">
                可在「我的 / 接入账号」运行「回源自检」定位并按提示重新授权；恢复后查看原文将走实时回源。
              </p>
              <span v-if="messageContentFor(message.id)?.can_expand" class="content-clamp-hint">预览最多显示 8 行；完整内容请展开全文。</span>
            </div>
            <div class="message-actions">
              <button
                v-if="message.overview?.status === 'failed' || message.overview?.status === 'ready'"
                class="action-button action-secondary"
                type="button"
                :disabled="handlingSubmitting"
                @click="retryMessageOverview(message.id)"
              >
                重新生成中文概要
              </button>
              <button v-if="workspaceView === 'messages' || workspaceView === 'customerMessages'"
                class="action-button action-secondary"
                type="button"
                :disabled="contentLoadingMessageIds.has(message.id)"
                @click="toggleOriginalView(message.id)"
              >
                {{ contentLoadingMessageIds.has(message.id) ? '正在读取…' : expandedMessageIds.has(message.id) ? '收起正文' : '查看原文' }}
              </button>
              <button
                v-if="message.link_state !== 'linked' && currentUser?.role !== 'sales'"
                class="action-button action-secondary"
                type="button"
                :disabled="linkReviewLoading || handlingSubmitting"
                @click="toggleLinkReview(message.id)"
              >
                {{ linkReviewLoading && linkReviewMessageId === message.id ? '正在查询…' : linkReviewMessageId === message.id && linkReviewCandidates ? '收起归属候选' : '确认客户归属' }}
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
              <button v-if="workspaceView === 'messages' || workspaceView === 'customerMessages'"
                class="action-button action-secondary"
                type="button"
                :disabled="handlingSubmitting || message.handling_status === 'processed'"
                @click="updateMessageHandling(message, 'processed')"
              >
                {{ message.handling_status === 'processed' ? '系统外已处理' : '系统外已处理…' }}
              </button>
              <button v-if="workspaceView === 'messages' || workspaceView === 'customerMessages'"
                class="action-button action-secondary"
                type="button"
                :disabled="handlingSubmitting || message.handling_status === 'ignored'"
                @click="updateMessageHandling(message, 'ignored')"
              >
                {{ message.handling_status === 'ignored' ? '已忽略' : '忽略' }}
              </button>
            </div>
            <p v-if="messageFeedback[message.id]" class="message-inline-feedback" :class="`feedback-${messageFeedback[message.id].kind}`" role="status" aria-live="polite">
              {{ messageFeedback[message.id].text }}
            </p>
            </div>
            </section>
          </template>
          <div v-if="canLoadMoreMessages || messagePage > 1" class="pagination-bar">
            <button v-if="messagePage > 1" class="secondary" type="button" :disabled="messageLoadingMore" @click="loadPreviousMessages">上一页</button>
            <span>第 {{ messagePage }} 页 · 每页 20 条</span>
            <button v-if="canLoadMoreMessages" class="secondary" type="button" :disabled="messageLoadingMore" @click="loadMoreMessages">下一页</button>
          </div>
        </div>
      </section>

      <section v-if="isInquiryView && selectedInquiry" class="detail-panel panel">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">记录 #{{ selectedInquiry.id }}</p>
            <h2>{{ selectedInquiry.contact_sources[0]?.customer_nickname || selectedInquiry.contact_sources[0]?.raw_customer_contact || `链路 #${selectedInquiry.id}` }}</h2>
          </div>
          <span v-if="selectedInquiry.contact_sources.length > 0" class="status-pill">{{ [...new Set(selectedInquiry.contact_sources.map((source) => source.channel_type).filter(Boolean))].join(' / ') }}</span>
          <button class="detail-close secondary" type="button" @click="selectedInquiryId = null">关闭详情</button>
        </div>
        <div class="detail-navigation">
          <button type="button" class="secondary" :disabled="selectedInquiryIndex <= 0 && inquiryPage === 1" @click="moveInquiry(-1)">上一条</button>
          <span>第 {{ inquiryPage }} / {{ inquiryTotalPages }} 页 · 本页 {{ selectedInquiryIndex + 1 }} / {{ inquiries.length }} 条</span>
          <button type="button" class="secondary" :disabled="selectedInquiryIndex >= inquiries.length - 1 && !inquiryHasMore" @click="moveInquiry(1)">下一条</button>
        </div>

        <div class="facts-grid">
          <div><span>业务类型</span><strong>{{ selectedInquiry.business_type === 'inquiry' ? '询盘' : selectedInquiry.business_type === 'after_sales' ? '售后' : '未分类' }}</strong></div>
          <div><span>阶段/状态</span><strong>{{ selectedInquiry.status === 'new' ? '待人工确认' : statusLabel(selectedInquiry.status) }}</strong></div>
          <div><span>负责人</span><strong>{{ selectedInquiry.assigned_sales_user_id ? `用户 #${selectedInquiry.assigned_sales_user_id}` : '未分配' }}</strong></div>
          <div><span>来源渠道</span><strong>{{ [...new Set(selectedInquiry.messages.map((source) => source.channel_type).filter(Boolean))].join(' / ') || '当前授权可见来源为空' }}</strong></div>
          <div><span>归链阶段</span><strong>{{ lifecycleStageLabel(selectedInquiry.lifecycle_stage) }}</strong></div>
        </div>

        <section class="detail-section">
          <h3>当前授权可见的联系人身份来源</h3>
          <p v-if="selectedInquiry.contact_sources.length === 0" class="empty">没有当前可见的联系人来源。</p>
          <dl v-for="(source, index) in selectedInquiry.contact_sources" :key="`${source.channel_account_id}-${index}`" class="contact-list">
            <div><dt>来源</dt><dd>{{ source.channel_type || '未知渠道' }} · 账号 #{{ source.channel_account_id ?? '不可见' }}</dd></div>
            <div><dt>联系人</dt><dd>{{ source.customer_nickname || source.raw_customer_contact || '未提供' }}</dd></div>
            <div><dt>身份状态</dt><dd>{{ contactIdentityLabel(source.contact_identity_state) }}</dd></div>
          </dl>
          <p class="muted">联系方式仅来自当前授权可见消息；撤权来源不会显示。原文须从下方对应消息单独授权回溯。</p>
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
          <h3>关联客户消息</h3>
          <p class="muted">客户消息概要、渠道和人工处理状态。</p>
          <p v-if="selectedInquiry.messages.length === 0" class="empty">当前没有可见关联消息。</p>
          <ol v-else class="timeline linked-message-timeline">
            <li v-for="linkedMessage in selectedInquiry.messages" :key="linkedMessage.id">
              <span>
                {{ channelLabel(linkedMessage.channel_type) }} · {{ linkedMessage.direction === 'inbound' ? '客户入站' : '系统出站' }} · {{ formatTime(linkedMessage.occurred_at) }}
              </span>
               <strong>消息 #{{ linkedMessage.id }} · {{ handlingStatusLabel(linkedMessage.handling_status) }} · 概要 {{ linkedMessage.overview_status === 'ready' ? '已生成' : linkedMessage.overview_status === 'pending' ? '生成中' : '待生成' }}</strong>
              <small>发送人/联系人：{{ selectedInquiry.contact_sources.find((source) => source.channel_account_id === linkedMessage.channel_account_id)?.customer_nickname || selectedInquiry.contact_sources.find((source) => source.channel_account_id === linkedMessage.channel_account_id)?.raw_customer_contact || '当前来源未提供' }} · 渠道账号：{{ linkedMessage.channel_account_external_id || accountLabel(linkedMessage.channel_account_id) }}</small>
              <p class="linked-message-overview">{{ linkedMessage.overview_text || (linkedMessage.overview_status === 'pending' ? '中文概要正在生成。' : linkedMessage.overview_status === 'failed' ? '中文概要生成失败，可在消息收件箱重试。' : '暂无中文概要。') }}</p>
              <button class="secondary" type="button" @click="openCustomerMessage(linkedMessage.id)">查看客户消息</button>
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
          <button class="secondary operation-log-button" type="button" @click="openOperationLogs(selectedInquiry.id)">查看此链路操作记录</button>
          <p v-if="actionError" class="action-error">{{ actionError }}</p>
          <div v-if="selectedInquiry.status === 'new'" class="transfer-form">
            <label for="transfer-business-type">业务类型</label>
            <select id="transfer-business-type" v-model="selectedBusinessType">
              <option :value="null">请选择类型</option><option value="inquiry">询盘</option><option value="after_sales">售后</option>
            </select>
            <label for="transfer-target">分配负责人</label>
            <select id="transfer-target" v-model="selectedSalesUserId">
              <option :value="null">请选择业务员</option>
              <option v-for="target in transferTargets" :key="target.id" :value="target.id">
                {{ target.username }}（用户 #{{ target.id }}）
              </option>
            </select>
            <button
              class="primary"
              type="button"
              :disabled="transferSubmitting || selectedSalesUserId === null || selectedBusinessType === null"
              @click="transferSelectedInquiry"
            >
              {{ transferSubmitting ? '分配中…' : '确认分配' }}
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
      <section v-else-if="isInquiryView && inquiries.length === 0" class="detail-panel panel empty-state">
        <h2>暂无可展示的链路</h2>
        <p>授权范围内没有询盘，或后端返回为空。</p>
      </section>
      </section>
    </template>
  <Transition name="link-dialog">
    <div
      v-if="linkReviewMessageId !== null"
      class="link-review-backdrop"
      @click.self="closeLinkReview"
      @keydown.esc.window="closeLinkReview"
    >
      <section class="link-review-dialog" role="dialog" aria-modal="true" aria-labelledby="link-review-title" tabindex="-1">
        <header class="link-review-heading">
          <div>
            <p class="eyebrow">消息 #{{ linkReviewMessageId }} · 客户归属</p>
            <h2 id="link-review-title">选择对应的客户链路</h2>
            <p v-if="linkReviewMessage" class="link-review-subtitle">
              {{ messageContactLabel(linkReviewMessage) }}<span v-if="messageSenderLabel(linkReviewMessage)"> · {{ messageSenderLabel(linkReviewMessage) }}</span>
            </p>
          </div>
          <button class="dialog-close" type="button" aria-label="关闭客户归属窗口" @click="closeLinkReview">关闭 <span aria-hidden="true">×</span></button>
        </header>
        <div class="link-review-content" aria-live="polite">
          <p v-if="linkReviewLoading" class="dialog-state">正在查找当前授权范围内的客户链路…</p>
          <div v-else-if="linkReviewError" class="dialog-state dialog-error" role="alert">
            <p>{{ linkReviewError }}</p>
            <button class="secondary" type="button" @click="retryLinkReview">重试</button>
          </div>
          <template v-else-if="linkReviewCandidates">
            <p v-if="linkReviewCandidates.match_state === 'manual_confirmation_required'" class="review-guidance">
              请核对消息发送人和候选客户的联系方式后再关联。系统不会依据正文或相似姓名自动合并客户。
            </p>
            <p v-else-if="linkReviewCandidates.match_state === 'multiple'" class="review-guidance">找到多个可能的客户，请逐项核对联系方式后选择。</p>
            <p v-else-if="linkReviewCandidates.match_state === 'none'" class="dialog-state">没有找到匹配链路。此消息仍留在消息收件箱中。</p>
            <p v-else-if="linkReviewCandidates.match_state === 'missing_identity' || linkReviewCandidates.match_state === 'unsupported_identity'" class="dialog-state">这条消息没有可用于安全匹配的邮箱或手机号，暂时不能关联。</p>
            <p v-else-if="linkReviewCandidates.match_state === 'linked'" class="dialog-state">这条消息已经关联到客户链路。</p>
            <p v-if="linkReviewCandidates.items.length === 0 && ['manual_confirmation_required', 'multiple'].includes(linkReviewCandidates.match_state)" class="dialog-state">当前授权范围内没有可供确认的客户链路。</p>
            <div v-if="linkReviewCandidates.items.length > 0" class="link-candidate-list">
              <article v-for="candidate in linkReviewCandidates.items" :key="candidate.id" class="link-candidate-row">
                <div class="link-candidate-identity">
                  <strong>{{ candidate.customer_nickname || candidate.customer_contact || `未命名客户 #${candidate.id}` }}</strong>
                  <span>{{ candidate.customer_contact || '联系方式未提供' }}</span>
                  <small>链路 #{{ candidate.id }} · {{ statusLabel(candidate.status) }} · {{ handlingStatusLabel(candidate.handling_status) }}</small>
                </div>
                <button class="primary" type="button" :disabled="handlingSubmitting" @click="confirmMessageLink(candidate.id, linkReviewCandidates?.requires_identity_confirmation === true)">
                  {{ handlingSubmitting ? '正在关联…' : linkReviewCandidates?.requires_identity_confirmation ? '确认身份并关联' : '关联此客户' }}
                </button>
              </article>
            </div>
          </template>
        </div>
        <footer class="link-review-footer">
          <span>关闭窗口不会修改消息或客户资料。</span>
          <button class="secondary" type="button" @click="closeLinkReview">关闭</button>
        </footer>
      </section>
    </div>
  </Transition>
</main>
</template>

<style>
.workspace-tabs { display: flex; gap: 4px; border-bottom: 1px solid #d6dfe2; }
.workspace-tabs button { padding: 12px 18px; color: #52606d; background: transparent; border: 0; border-bottom: 3px solid transparent; cursor: pointer; font-weight: 700; }
.workspace-tabs button.active { color: #165d68; border-bottom-color: #165d68; }
.workspace-tabs button:focus-visible { outline: 2px solid #165d68; outline-offset: -3px; }
.flow-note { margin: 14px 0 0; padding: 10px 12px; color: #46565c; background: #f1f5f5; border-left: 3px solid #147a85; font-size: 13px; line-height: 1.5; }
.inbox-panel > .panel-heading > div > p:not(.eyebrow) { margin: 6px 0 0; color: #687782; font-size: 13px; line-height: 1.5; }
.inquiry-pagination { padding: 16px 26px; border-top: 1px solid #e5eaec; }
.detail-navigation { display: flex; align-items: center; gap: 12px; padding: 10px 0; border-top: 1px solid #e5eaec; border-bottom: 1px solid #e5eaec; }
.detail-navigation span { flex: 1; color: #687782; font-size: 12px; }
@media (max-width: 480px) { .workspace-tabs button { flex: 1; padding: 12px 4px; } }
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
.analysis-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 20px; }
.analysis-lists { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; grid-column: 1 / -1; }
.analysis-list { padding: 16px 18px; min-width: 0; }
.analysis-list ul { margin: 0; padding-left: 18px; }
.analysis-list li { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-top: 1px solid #edf0f5; font-size: 12px; overflow-wrap: anywhere; }
.analysis-list li span:last-child { color: #758198; text-align: right; }
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
.review-guidance { color: #5b6470; font-size: 12px; line-height: 1.6; margin: 0 0 10px; }
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
.refetch-check-result { margin-top: 12px; padding: 10px 12px; border: 1px solid #d7e5e7; border-radius: 4px; background: #f7fafb; font-size: 12px; line-height: 1.6; }
.refetch-check-result.ok { border-color: #b6d8c4; background: #f2faf5; color: #2f6b4f; }
.refetch-check-result.warn { border-color: #e8c4c9; background: #fdf5f6; color: #9a2f3b; }
.refetch-check-result p { margin: 4px 0 0; }
.refetch-check-result ul { margin: 6px 0 0; padding-left: 18px; }
.content-source-hint { margin-top: 4px; color: #9a2f3b !important; font-size: 11px !important; }
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
@media (max-width: 800px) { .channel-grid { grid-template-columns: 1fr; } .analysis-strip { grid-template-columns: repeat(2, 1fr); } .analysis-lists { grid-template-columns: 1fr; } .content-grid { grid-template-columns: 1fr; } .facts-grid { grid-template-columns: repeat(2, 1fr); } }
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
.message-meta .group-badge { background: #e8f1f8; border: 1px solid #c9dcef; border-radius: 999px; padding: 0 8px; color: #1d5fbf; }
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
.content-expand-link { margin-top: 6px; color: #165d68; font-size: 12px; font-weight: 700; }
.message-original-preview { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 8; overflow: hidden; white-space: pre-wrap; }
.message-full-content { white-space: pre-wrap; }
.message-group-bar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; padding: 7px 12px; background: #f2f7f8; border: 1px solid #d7e5e7; border-radius: 4px; }
.message-group-bar .group-label { color: #165d68; font-size: 12px; font-weight: 700; }
.message-group-bar .link-button { color: #165d68; font-size: 12px; font-weight: 700; }
.message-group { margin-top: 14px; padding: 0 14px 4px; border: 1px solid #dce4e7; border-radius: 6px; background: #fff; }
.message-group.has-multiple { background: #fbfcfc; }
.message-group-bar { margin: 0 -14px; padding: 11px 14px; border: 0; border-bottom: 1px solid #dce4e7; border-radius: 5px 5px 0 0; background: #f1f6f6; }
.message-group .message-row:first-of-type { border-top: 0; }
.message-group .message-row:last-child { border-bottom: 0; }
.action-toast { position: fixed; z-index: 1000; top: 22px; left: 50%; display: flex; align-items: center; gap: 11px; max-width: min(390px, calc(100vw - 32px)); padding: 13px 17px; transform: translateX(-50%); color: #263b34; background: #fff; border: 1px solid #dce8e1; border-left: 4px solid #27845d; border-radius: 7px; box-shadow: 0 8px 28px rgb(24 42 34 / 16%); font-size: 14px; font-weight: 650; }
.action-toast.toast-ignored { color: #554629; border-color: #eee4cb; border-left-color: #b48627; }
.toast-mark { display: grid; flex: 0 0 24px; width: 24px; height: 24px; place-items: center; border-radius: 50%; color: #fff; background: #27845d; font-size: 14px; }
.toast-ignored .toast-mark { background: #b48627; }
.action-toast-enter-active, .action-toast-leave-active { transition: opacity 220ms ease, transform 220ms cubic-bezier(.2,.75,.25,1); }
.action-toast-enter-from { opacity: 0; transform: translate(-50%, -16px); }
.action-toast-leave-to { opacity: 0; transform: translate(-50%, -8px); }
.content-label { display: block; margin-bottom: 4px; color: #687782; font-size: 12px; font-weight: 700; }
.content-source-note { color: #687782 !important; font-size: 11px !important; }
.content-source-note.tone-ok { color: #2f6b4f !important; }
.content-source-note.tone-warn { color: #9a2f3b !important; }
.content-clamp-hint { display: block; margin-top: 4px; color: #89939b !important; font-size: 11px !important; }
.message-overview { grid-column: 2; color: #165d68 !important; font-weight: 700; }
.message-overview.fallback { color: #9a2f3b !important; font-weight: 500; }
.archive-toolbar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.archive-box { margin: 12px 0 18px; padding: 14px; background: #f8fbfb; border: 1px solid #d7e5e7; border-radius: 6px; }
.archive-box h3 { margin-bottom: 10px; }
.archive-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0; border-top: 1px solid #e3edef; }
.archive-row span, .archive-row p { display: block; margin: 4px 0 0; color: #687782; font-size: 12px; }
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
  .action-toast { top: 12px; left: 50%; width: max-content; max-width: calc(100vw - 24px); }
}

.content-grid.has-selected-inquiry { display: grid; grid-template-columns: minmax(230px, 300px) minmax(0, 1fr); align-items: start; gap: 18px; }
.has-selected-inquiry > .workspace-tabs { grid-column: 1 / -1; }
.inbox-panel.inquiry-sidebar { position: sticky; top: 16px; align-self: start; max-height: calc(100vh - 32px); overflow-y: auto; scrollbar-width: thin; }
.inquiry-sidebar .panel-heading { padding: 16px; }
.inquiry-sidebar .panel-heading > div > p:not(.eyebrow) { display: none; }
.inquiry-sidebar .panel-heading h2 { font-size: 16px; }
.inquiry-sidebar .count { white-space: nowrap; font-size: 11px; }
.inquiry-sidebar .inbox-filters { padding: 10px 14px; }
.inquiry-sidebar .inquiry-row { padding: 11px 14px; }
.inquiry-sidebar .inquiry-row .channel, .inquiry-sidebar .inquiry-row .preview { display: none; }
.inquiry-sidebar .inquiry-row strong { overflow-wrap: anywhere; }
.inquiry-sidebar .inquiry-pagination { display: grid; gap: 8px; padding: 12px 14px; }
.page-progress-label { margin: 0 !important; color: #52606d; font-size: 12px; text-align: center; }
.page-dots { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; gap: 2px; }
.page-dot { display: grid; flex: 0 0 24px; width: 24px; min-width: 24px !important; height: 24px; place-items: center; padding: 0 !important; border: 0 !important; border-radius: 50%; background: transparent !important; cursor: pointer; }
.page-dot span { width: 7px; height: 7px; border-radius: 50%; background: #aab6ba; transition: width 160ms ease, height 160ms ease, background-color 160ms ease; }
.page-dot.active span { width: 10px; height: 10px; background: #147a85; }
.page-dot:hover span { background: #147a85; }
.page-dot:disabled { cursor: progress; }
.detail-close { flex: 0 0 auto; }
@media (max-width: 800px) {
  .content-grid.has-selected-inquiry { grid-template-columns: 1fr; }
  .has-selected-inquiry > .workspace-tabs { grid-column: 1; }
  .inbox-panel.inquiry-sidebar { position: static; max-height: 38vh; }
}

/* Framed-sheet operations layout: one cool frame, one continuous white work surface. */
:root { color: #20292c; background: #edf2f3; font-family: "IBM Plex Sans", "Noto Sans SC", "Microsoft YaHei", sans-serif; }
body { min-width: 320px; background: #edf2f3; }
.workspace { width: min(1680px, 100% - 32px); padding: 26px 0 32px; }
.topbar { min-height: 52px; margin: 0; padding: 0 12px 18px; }
.topbar h1 { margin: 0; color: #182326; font-size: 22px; font-weight: 600; }
.eyebrow { color: #66777c; letter-spacing: 0; text-transform: none; }
.workspace-tabs { gap: 0; padding: 0 20px; background: #f6f9f9; border: 1px solid #dfe7e8; border-bottom: 0; border-radius: 12px 12px 0 0; }
.workspace-tabs button { min-height: 48px; padding: 10px 16px; color: #657277; border-bottom: 2px solid transparent; font-size: 14px; font-weight: 500; }
.workspace-tabs button.active { color: #1b6c80; border-bottom-color: #1b6c80; }
.content-grid { gap: 0; margin: 0; padding: 8px; background: #f6f9f9; border: 1px solid #dfe7e8; border-top: 0; border-radius: 0 0 12px 12px; }
.inbox-panel, .detail-panel { background: #fff; border: 1px solid #e4eaeb; border-radius: 8px; box-shadow: none; }
.inbox-panel { overflow: hidden; }
.inbox-panel > .panel-heading { padding: 22px 24px 16px; }
.inbox-panel > .panel-heading h2, .detail-panel h2 { color: #1c292d; font-size: 18px; font-weight: 600; }
.inbox-filters { display: flex; align-items: end; gap: 14px; padding: 12px 24px; background: #f8fafb; border-top: 1px solid #edf1f2; border-bottom: 1px solid #e7edef; }
.filter-group { gap: 8px; }
.filter-group > span { color: #66777c; font-size: 12px; font-weight: 500; }
.inbox-filters select, .transfer-form select { min-height: 34px; padding: 6px 28px 6px 9px; color: #253338; background: #fff; border: 1px solid #d4dfe1; border-radius: 5px; font-size: 13px; }
.subsection { padding: 18px 24px 22px; border: 0; }
.message-heading { padding: 0 0 14px !important; }
.message-heading h2 { margin: 0; color: #1e2b2f; font-size: 17px; font-weight: 600; }
.archive-toolbar { margin: 0 0 12px; }
.message-group { margin: 12px 0 0; padding: 0 16px 2px; border: 1px solid #e3eaeb; border-radius: 6px; background: #fff; }
.message-group.has-multiple { background: #fbfcfc; }
.message-group-bar { margin: 0 -16px; padding: 10px 16px; background: #f3f7f7; border-bottom: 1px solid #e3eaeb; border-radius: 5px 5px 0 0; }
.message-group-bar .group-label { color: #314b50; font-weight: 600; }
.message-group.has-multiple { padding-bottom: 8px; border: 2px solid #738c91; border-left: 6px solid #367c72; background: #f3f8f6; }
.message-group.has-multiple > .message-group-bar { margin: 0 -16px; padding: 12px 16px; color: #173d3b; background: #e3efeb; border-bottom: 1px solid #c7dad3; }
.message-group.has-multiple .group-label::before { content: '同一客户链路'; display: inline-block; margin-right: 9px; padding: 3px 7px; color: #fff; background: #367c72; border-radius: 3px; font-size: 11px; }
.message-group.has-multiple .message-row { margin: 0 -8px; padding-right: 10px; padding-left: 10px; background: #f8fbfa; }
.message-group.has-multiple .message-row + .message-row { border-top: 1px dashed #bacbc4; }
.message-group.has-multiple .group-badge { color: #164c43; background: #dcece5; border: 1px solid #b4d0c4; }
.message-inline-feedback { grid-column: 1 / -1 !important; margin: 3px 0 0 !important; padding: 8px 10px; border-left: 3px solid #2d875f; color: #245b43 !important; background: #eef7f1; font-size: 12px; }
.message-inline-feedback.feedback-error { color: #8a322e !important; background: #fff2ef; border-left-color: #bb5348; }
.operation-log-button { margin: 10px 0 4px; }
.profile-operations { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 16px 18px; border-bottom: 1px solid #e4ebea; }
.profile-operations h3, .profile-operations p { margin: 0; }
.profile-operations p { margin-top: 4px; color: #687782; font-size: 13px; }
.operation-object-link { padding: 0; color: #176b70; background: transparent; border: 0; font: inherit; text-align: left; text-decoration: underline; text-underline-offset: 3px; cursor: pointer; }
.operation-object-link:hover { color: #10494d; }
.operation-log-backdrop { position: fixed; z-index: 1200; inset: 0; display: grid; place-items: center; padding: 20px; background: rgba(22, 34, 37, .42); }
.operation-log-dialog { width: min(920px, 100%); max-height: min(78vh, 720px); overflow: hidden; background: #fff; border: 1px solid #d8e1e1; border-radius: 8px; box-shadow: 0 20px 60px rgba(20, 40, 40, .24); }
.operation-log-dialog > header { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 22px; border-bottom: 1px solid #e4ebea; }
.operation-log-dialog h2 { margin: 0; color: #203133; font-size: 18px; }
.operation-log-table-wrap { max-height: calc(min(78vh, 720px) - 80px); overflow: auto; }
.operation-log-table { width: 100%; border-collapse: collapse; font-size: 13px; text-align: left; }
.operation-log-table th, .operation-log-table td { padding: 11px 14px; border-bottom: 1px solid #e8eeee; vertical-align: top; }
.operation-log-table th { position: sticky; top: 0; color: #5c6d70; background: #f5f8f7; font-size: 12px; font-weight: 600; }
.operation-log-table td small { display: block; margin-top: 3px; color: #728184; }
.operation-result { display: inline-block; padding: 3px 7px; border-radius: 3px; color: #236345; background: #eaf5ee; white-space: nowrap; }
.operation-result.result-failure { color: #933b31; background: #fff0ed; }
.operation-result.result-timeout { color: #815d16; background: #fff6dc; }
.message-row { grid-template-columns: minmax(170px, 220px) minmax(0, 1fr) auto; column-gap: 20px; padding: 15px 0; border-color: #e9eeef; }
.message-row.is-focused-message { margin: 0 -8px; padding-right: 8px; padding-left: 8px; background: #eff8f8; outline: 1px solid #93c9cc; outline-offset: -1px; }
.message-row { scroll-margin-top: 100px; }
.message-row.is-focused-message { z-index: 1; background: #e5f3e9; outline: 2px solid #247a57; box-shadow: inset 6px 0 0 #247a57, 0 5px 18px rgba(31, 100, 72, .16); animation: message-focus-arrive 700ms ease-out both; }
.message-row.is-focused-message::after { content: '当前查看'; position: absolute; top: 8px; right: 8px; padding: 3px 8px; color: #fff; background: #247a57; border-radius: 3px; font-size: 11px; font-weight: 700; }
.linked-message-overview { margin: 8px 0; padding: 10px 12px; color: #283b39; background: #f1f7f2; border-left: 3px solid #61916e; line-height: 1.6; white-space: pre-wrap; overflow-wrap: anywhere; }
@keyframes message-focus-arrive { from { background: #d5eddf; transform: translateY(5px); } to { background: #e5f3e9; transform: translateY(0); } }
.message-meta strong, .inquiry-row strong { color: #24373c; }
.message-overview { color: #31515a !important; font-weight: 500; }
.message-row .channel-mark { color: #285761; background: #e9f3f3; }
.message-row .message-actions { gap: 6px; }
.action-button, .secondary, .primary { border-radius: 5px; }
.primary, .action-primary { color: #fff; background: #1b6c80; border-color: #1b6c80; }
.content-grid.has-selected-inquiry { grid-template-columns: minmax(230px, 290px) minmax(0, 1fr); gap: 10px; }
.has-selected-inquiry > .workspace-tabs { grid-column: 1 / -1; }
.inbox-panel.inquiry-sidebar { max-height: calc(100vh - 70px); border-radius: 8px; }
.inquiry-sidebar .panel-heading { padding: 15px; }
.inquiry-row { padding: 12px 15px; border-color: #edf1f2; }
.inquiry-row:hover { background: #f6f9f9; }
.inquiry-row.selected { background: #edf5f5; box-shadow: inset 2px 0 0 #1b6c80; }
.inquiry-row .status { color: #315b62; background: #edf3f3; }
.detail-panel { padding: 20px 24px; }
.detail-section { border-color: #e8edef; }
.detail-section h3 { color: #24373c; font-size: 14px; font-weight: 600; }
.facts-grid > div { background: #f7f9fa; border-color: #e5ebed; border-radius: 5px; }
.transfer-form { grid-template-columns: auto minmax(150px, 1fr) auto minmax(150px, 1fr) auto; align-items: center; }
.transfer-form .primary { grid-column: auto; }
.detail-navigation { border-color: #e6ecee; }
.detail-close { padding: 6px 10px; }
@media (max-width: 800px) {
  .workspace { width: calc(100% - 20px); padding-top: 14px; }
  .workspace-tabs { padding: 0 6px; overflow-x: auto; }
  .workspace-tabs button { flex: 1 0 auto; padding: 10px 12px; white-space: nowrap; }
  .content-grid { padding: 5px; }
  .content-grid.has-selected-inquiry { grid-template-columns: 1fr; }
  .inbox-panel.inquiry-sidebar { max-height: 34vh; }
  .operation-log-dialog { max-height: 82vh; }
  .operation-log-table { min-width: 640px; }
  .subsection { padding: 15px; }
  .inbox-filters { flex-wrap: wrap; padding: 12px 15px; }
  .message-row { grid-template-columns: 1fr; gap: 8px; }
  .message-row .message-meta, .message-row p, .message-row .message-preview, .message-row .message-actions { grid-column: 1; grid-row: auto; }
  .message-row .message-actions { justify-content: flex-start; margin-top: 4px; }
  .transfer-form { grid-template-columns: 1fr; }
  .transfer-form .primary { grid-column: 1; }
}
.message-row { grid-template-columns: minmax(170px, 210px) minmax(0, 1fr) minmax(250px, 290px); column-gap: 20px; }
.message-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-content: start; max-width: none; gap: 6px; margin: 0; }
.message-actions .action-button { min-height: 32px; padding: 6px 8px; font-size: 12px; line-height: 1.25; white-space: normal; }
.link-review-backdrop { position: fixed; z-index: 1200; inset: 0; display: grid; place-items: center; padding: 24px; background: rgb(23 35 39 / 42%); }
.link-review-dialog { display: flex; width: min(760px, 100%); max-height: min(82vh, 720px); flex-direction: column; overflow: hidden; background: #fff; border: 1px solid #dbe4e6; border-radius: 10px; box-shadow: 0 22px 64px rgb(24 42 46 / 24%); outline: none; }
.link-review-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 22px 24px 18px; border-bottom: 1px solid #e8edef; }
.link-review-heading .eyebrow { margin-bottom: 7px; }
.link-review-heading h2 { margin: 0; color: #202d31; font-size: 20px; font-weight: 600; }
.link-review-subtitle { margin: 7px 0 0; color: #5c6d72; font-size: 13px; overflow-wrap: anywhere; }
.dialog-close { display: inline-flex; min-height: 38px; flex: 0 0 auto; align-items: center; gap: 8px; padding: 7px 11px; color: #34464b; background: #f5f8f8; border: 1px solid #d9e2e4; border-radius: 5px; cursor: pointer; font-size: 13px; font-weight: 600; }
.dialog-close span { color: #718186; font-size: 19px; line-height: 1; }
.link-review-content { min-height: 180px; overflow-y: auto; padding: 20px 24px; }
.dialog-state { margin: 0; padding: 18px 16px; color: #55676c; background: #f6f9f9; border: 1px solid #e4ebec; border-radius: 6px; font-size: 14px; line-height: 1.6; }
.dialog-error { color: #812b32; background: #fff7f7; border-color: #f0d5d7; }
.dialog-error p { margin-bottom: 12px; }
.review-guidance { margin: 0 0 14px; padding: 12px 14px; color: #654e19; background: #fbf7ea; border-left: 3px solid #bf9638; font-size: 13px; line-height: 1.6; }
.link-candidate-list { display: grid; gap: 8px; }
.link-candidate-row { display: flex; min-height: 76px; align-items: center; justify-content: space-between; gap: 20px; padding: 14px 16px; background: #fff; border: 1px solid #e2e9eb; border-radius: 6px; }
.link-candidate-identity { display: grid; min-width: 0; gap: 4px; }
.link-candidate-identity strong { color: #24373c; font-size: 14px; overflow-wrap: anywhere; }
.link-candidate-identity span { color: #40565c; font-size: 13px; overflow-wrap: anywhere; }
.link-candidate-identity small { color: #718085; font-size: 12px; }
.link-candidate-row .primary { flex: 0 0 auto; min-height: 36px; padding: 7px 12px; }
.link-review-footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 24px; background: #fafcfc; border-top: 1px solid #e8edef; }
.link-review-footer span { color: #718085; font-size: 12px; }
.link-review-footer .secondary { min-width: 74px; min-height: 36px; }
.link-dialog-enter-active, .link-dialog-leave-active { transition: opacity 180ms ease; }
.link-dialog-enter-active .link-review-dialog, .link-dialog-leave-active .link-review-dialog { transition: transform 180ms cubic-bezier(.2,.75,.25,1); }
.link-dialog-enter-from, .link-dialog-leave-to { opacity: 0; }
.link-dialog-enter-from .link-review-dialog, .link-dialog-leave-to .link-review-dialog { transform: translateY(10px); }
@media (max-width: 700px) {
  .message-row { grid-template-columns: 1fr; gap: 8px; }
  .message-row .message-meta, .message-row p, .message-row .message-preview, .message-row .message-actions { grid-column: 1; grid-row: auto; }
  .link-review-backdrop { align-items: end; padding: 8px; }
  .link-review-dialog { width: 100%; max-height: 88vh; border-radius: 10px 10px 6px 6px; }
  .link-review-heading, .link-review-content { padding-right: 16px; padding-left: 16px; }
  .link-review-heading h2 { font-size: 18px; }
  .link-candidate-row { align-items: stretch; flex-direction: column; gap: 12px; }
  .link-candidate-row .primary { width: 100%; }
  .link-review-footer { padding: 12px 16px; }
}
</style>
