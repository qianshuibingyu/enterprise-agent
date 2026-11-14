<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  ApiError,
  clearCsrfCache,
  inboxApi,
  type AdminChannelAccount,
  type ChannelAccount,
  type EmployeeRecord,
  type Inquiry,
  type InquiryLinkCandidates,
  type InternalAnalysis,
  type Message,
  type OperationLog,
  type RefetchCheck,
  type TransferTarget,
  type WhatsappGroupBinding,
  type WhatsappPhoneCandidate,
} from './api/inbox'
import { channelsApi } from './api/channels'
import type { ChannelType, ConnectionStatus } from './api/channels'
import {
  goBack,
  initRouter,
  isStandalonePage,
  navigate,
  route,
  type AppRoute,
  type RouteChange,
  type WorkspaceView,
} from './router'
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
const workspaceView = ref<WorkspaceView>('messages')
/** Standalone detail pages load their own record instead of relying on the list cache. */
const inquiryDetail = ref<Inquiry | null>(null)
const messageDetail = ref<Message | null>(null)
const messageDetailContent = ref<MessageContent | null>(null)
const messageDetailLoading = ref(false)
const isStandalone = computed(() => isStandalonePage(route.value.page))
const showInquiryDetail = computed(() =>
  selectedInquiry.value !== null && (route.value.page === 'inquiry' || isInquiryView.value),
)
/** Signature of the currently loaded list; unchanged on Back means zero requests. */
let loadedListSignature = ''
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
/** 查看客户消息：只展示运营同事入站时落库的清洗后原文，不跳页、不再点一次「查看原文」。 */
type CustomerMessageContent = Awaited<ReturnType<typeof inboxApi.getMessageContent>>
const customerMessageId = ref<number | null>(null)
const customerMessageContent = ref<CustomerMessageContent | null>(null)
const customerMessageLoading = ref(false)
const customerMessageError = ref('')
const customerMessageCopied = ref(false)
const unauthorized = ref(false)
const unauthorizedStatus = ref<401 | 403 | null>(null)
const gmailMessage = ref('')
const gmailError = ref('')
const whatsappMessage = ref('')
const whatsappError = ref('')
const whatsappQr = ref('')
const whatsappQrExpiresAt = ref('')
const profileOpen = ref(false)
const currentUser = ref<{ id?: number; username: string; role: string; department?: string | null; must_change_password?: boolean } | null>(null)
const employeeAdminOpen = ref(false)
const employeeRecords = ref<EmployeeRecord[]>([])
const employeeError = ref('')
// 员工页的错误是一次性操作反馈：不应长期贴在面板上（尤其下次打开别人的设置时）。
// 统一在这里自动收起，避免「已经改好了但红条还在」的错觉。
let employeeErrorTimer: ReturnType<typeof setTimeout> | null = null
watch(employeeError, (message) => {
  if (employeeErrorTimer) {
    clearTimeout(employeeErrorTimer)
    employeeErrorTimer = null
  }
  if (!message) return
  employeeErrorTimer = setTimeout(() => {
    employeeError.value = ''
    employeeErrorTimer = null
  }, 6000)
})
const employeeChannelFeedback = ref<{ kind: 'success' | 'error'; text: string } | null>(null)
const employeeChannelPending = ref<string | null>(null)
const employeeCreateFeedback = ref<{ kind: 'success' | 'error'; text: string } | null>(null)
const employeeCreating = ref(false)
const employeeCreateFormEl = ref<HTMLFormElement | null>(null)
const employeeTableCardEl = ref<HTMLElement | null>(null)
const employeeForm = ref({ full_name: '', username: '', role: 'sales', department: '', manager_overlay_enabled: false, temporary_password: '' })
const employeeGrantDepartmentById = ref<Record<number, string>>({})
const employeeManagerTargetById = ref<Record<number, number | ''>>({})
const employeeManagerPermissionById = ref<Record<number, string>>({})
const employeeResetPasswordById = ref<Record<number, string>>({})
// 重置密码是「一次性的定点操作」，结果必须贴着按钮反馈：顶部红字经常在视口外，
// 点了没反应是这里最容易踩的坑。
const employeeResetFeedback = ref<{ userId: number; kind: 'success' | 'error'; text: string } | null>(null)
const employeeResetPendingId = ref<number | null>(null)
let employeeResetFeedbackTimer: ReturnType<typeof setTimeout> | null = null
function flashEmployeeReset(userId: number, kind: 'success' | 'error', text: string) {
  employeeResetFeedback.value = { userId, kind, text }
  if (employeeResetFeedbackTimer) {
    clearTimeout(employeeResetFeedbackTimer)
    employeeResetFeedbackTimer = null
  }
  if (kind !== 'success') return
  // 成功提示会自动收起；失败提示保留，直到下一次操作。
  employeeResetFeedbackTimer = setTimeout(() => {
    employeeResetFeedback.value = null
    employeeResetFeedbackTimer = null
  }, 10000)
}
const employeeSearch = ref('')
const employeeRoleFilter = ref('all')
const employeeStatusFilter = ref('all')
const expandedEmployeeId = ref<number | null>(null)
const employeeConfirmDeactivateId = ref<number | null>(null)
const employeeConfirmReactivateId = ref<number | null>(null)
const adminChannelAccounts = ref<AdminChannelAccount[]>([])
const adminChannelAccountsLoading = ref(false)
const adminChannelFeedback = ref<{ kind: 'success' | 'error'; title: string; text: string } | null>(null)
const regrantingAccountId = ref<number | null>(null)
const transferTargetUserId = ref<number | ''>('')
const selectedAdminChannelAccountIds = ref<number[]>([])
const channelTransferSubmitting = ref(false)
const adminChannelSelectionInitialized = ref(false)

const adminChannelStatusLabels: Record<string, string> = {
  not_ready: '待授权', connected: '已连接', connected_pending_inbound: '待入站验证',
  verified_inbound: '已验证入站', revoked: '已撤销',
}

const transferableEmployees = computed(() =>
  employeeRecords.value.filter((item) => item.is_active && isOperatingRole(item.role)),
)
const adminOwnedAccountCount = computed(() =>
  adminChannelAccounts.value.filter((account) => adminChannelOwnerIsAdmin(account.owner_user_id)).length,
)
const allAdminChannelAccountsSelected = computed(() =>
  adminChannelAccounts.value.length > 0 &&
  selectedAdminChannelAccountIds.value.length === adminChannelAccounts.value.length,
)

function adminChannelOwnerIsAdmin(ownerId: number) {
  return employeeRecords.value.find((item) => item.id === ownerId)?.role === 'admin'
}
function toggleAdminChannelAccount(accountId: number, checked: boolean) {
  selectedAdminChannelAccountIds.value = checked
    ? [...new Set([...selectedAdminChannelAccountIds.value, accountId])]
    : selectedAdminChannelAccountIds.value.filter((id) => id !== accountId)
}
function toggleAllAdminChannelAccounts(checked: boolean) {
  selectedAdminChannelAccountIds.value = checked ? adminChannelAccounts.value.map((item) => item.id) : []
}
function onToggleAdminChannelAccount(event: Event, accountId: number) {
  toggleAdminChannelAccount(accountId, (event.target as HTMLInputElement).checked)
}
function onToggleAllAdminChannelAccounts(event: Event) {
  toggleAllAdminChannelAccounts((event.target as HTMLInputElement).checked)
}
function accountOwnedByTransferTarget(ownerId: number) {
  const targetId = Number(transferTargetUserId.value)
  return targetId > 0 && ownerId === targetId
}

const employeeRoleLabels: Record<string, string> = {
  admin: '管理员', sales: '业务员', staff: '运营', operations: '运营', ops: '运营', manager: '经理（旧记录）',
  engineering: '工程', procurement: '采购', production: '生产',
}
const employeeChannelOptions = [
  { key: 'gmail', label: 'Gmail', hint: '邮件渠道' },
  { key: 'outlook', label: 'Outlook', hint: '邮件渠道' },
  { key: 'whatsapp', label: 'WhatsApp', hint: '即时消息渠道' },
]
const employeeRoleOptions = [
  { value: 'admin', label: '管理员' }, { value: 'sales', label: '业务员' }, { value: 'staff', label: '运营' },
  { value: 'engineering', label: '工程' }, { value: 'procurement', label: '采购' }, { value: 'production', label: '生产' },
]

function employeeRoleLabel(role: string) {
  return employeeRoleLabels[role] ?? role
}
function isOperatingRole(role: string) {
  return ['staff', 'operations', 'ops'].includes(role)
}
const employeeCreateRoleOptions = computed(() =>
  employeeRoleOptions.filter((option) => option.value !== 'admin'),
)
const employeeStats = computed(() => ({
  total: employeeRecords.value.length,
  active: employeeRecords.value.filter((item) => item.is_active).length,
  pendingPassword: employeeRecords.value.filter((item) => item.is_active && item.must_change_password).length,
  inactive: employeeRecords.value.filter((item) => !item.is_active).length,
}))
const departmentSuggestions = computed(() => {
  const values = new Set<string>()
  for (const item of employeeRecords.value) {
    if (item.department) values.add(item.department)
    for (const grant of item.department_grants) values.add(grant)
  }
  return [...values].sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
})
// 有效员工表只放能登录、能配置的账号；停用账号只出现在下方归档区。
const filteredEmployees = computed(() => {
  const keyword = employeeSearch.value.trim().toLowerCase()
  return employeeRecords.value.filter((item) => {
    if (!item.is_active) return false
    if (keyword && !`${item.full_name ?? ''} ${item.username} ${item.department ?? ''}`.toLowerCase().includes(keyword)) return false
    if (employeeRoleFilter.value !== 'all' && item.role !== employeeRoleFilter.value) return false
    if (employeeStatusFilter.value === 'pending' && !item.must_change_password) return false
    return true
  })
})
// 归档区与上方筛选完全独立：筛选岗位或搜索不应让已停用账号的数量和内容跟着跳。
const activeEmployees = computed(() => filteredEmployees.value)
const inactiveEmployees = computed(() => employeeRecords.value.filter((item) => !item.is_active))
const activeEmployeeCount = computed(() => employeeRecords.value.filter((item) => item.is_active).length)
const employeeFilterActive = computed(() =>
  employeeSearch.value.trim() !== '' || employeeRoleFilter.value !== 'all' || employeeStatusFilter.value !== 'all',
)
function toggleEmployeeDetail(userId: number) {
  const target = employeeRecords.value.find((item) => item.id === userId)
  if (!target || !target.is_active) {
    employeeError.value = '已停用的账号不能修改授权，请先在下方「已停用的员工」里启用账号。'
    expandedEmployeeId.value = null
    return
  }
  if (expandedEmployeeId.value !== userId) employeeError.value = ''
  expandedEmployeeId.value = expandedEmployeeId.value === userId ? null : userId
  employeeConfirmDeactivateId.value = null
  employeeConfirmReactivateId.value = null
}
function clearEmployeeFilters() {
  employeeSearch.value = ''
  employeeRoleFilter.value = 'all'
  employeeStatusFilter.value = 'all'
}
const managerPermissionOptions = [
  { value: 'password_reset', label: '重置密码' },
  { value: 'deactivate', label: '停用账号' },
  { value: 'reactivate', label: '恢复账号' },
  { value: 'adjust_grants', label: '调整经理授权' },
  { value: 'retry', label: '重试概要生成' },
]
const managerEligibleTargets = (manager: EmployeeRecord) => employeeRecords.value.filter((item) =>
  item.id !== manager.id && item.role !== 'admin' && item.department === manager.department && item.is_active,
)
function setEmployeeGrantDepartment(userId: number, event: Event) {
  const value = (event.target as HTMLInputElement).value
  employeeGrantDepartmentById.value = { ...employeeGrantDepartmentById.value, [userId]: value }
}
function setEmployeeResetPassword(userId: number, event: Event) {
  const value = (event.target as HTMLInputElement).value
  employeeResetPasswordById.value = { ...employeeResetPasswordById.value, [userId]: value }
}
const isAdmin = computed(() => currentUser.value?.role === 'admin')
const canOperateChannels = computed(() => ['staff', 'operations', 'ops'].includes(currentUser.value?.role ?? ''))

/** 批量处理：会话分组只是展示合并，以前没有整组/整页入口，运营只能逐条点。 */
const selectedMessageIds = ref<number[]>([])
const bulkActionRunning = ref(false)
const bulkActionNotice = ref('')
const bulkActionError = ref('')
const canBulkHandle = computed(() =>
  !isAdmin.value && (workspaceView.value === 'messages' || workspaceView.value === 'customerMessages'),
)
/** 已终态、出站消息不是待办。撤回消息仍可选中：运营需要能一键批量「忽略」。 */
const selectableMessages = computed(() => {
  if (!canBulkHandle.value) return []
  return messages.value.filter((message) =>
    message.handling_status === 'pending'
    && message.direction === 'inbound',
  )
})
const selectableMessageIds = computed(() => selectableMessages.value.map((message) => message.id))
const selectableIdSet = computed(() => new Set(selectableMessageIds.value))
const selectedMessageCount = computed(() =>
  selectedMessageIds.value.filter((id) => selectableIdSet.value.has(id)).length,
)
const allVisibleSelected = computed(() =>
  selectableMessageIds.value.length > 0
  && selectableMessageIds.value.every((id) => selectedMessageIds.value.includes(id)),
)

function isMessageSelected(messageId: number) {
  return selectedMessageIds.value.includes(messageId)
}
function canBulkSelect(message: Message) {
  return canBulkHandle.value && selectableIdSet.value.has(message.id)
}
function toggleMessageSelection(messageId: number) {
  selectedMessageIds.value = selectedMessageIds.value.includes(messageId)
    ? selectedMessageIds.value.filter((id) => id !== messageId)
    : [...selectedMessageIds.value, messageId]
}
function toggleSelectAllVisible() {
  selectedMessageIds.value = allVisibleSelected.value ? [] : [...selectableMessageIds.value]
}
function clearMessageSelection() {
  selectedMessageIds.value = []
}
function groupSelectableIds(group: MessageGroup) {
  return group.messages.map((message) => message.id).filter((id) => selectableIdSet.value.has(id))
}
function isGroupFullySelected(group: MessageGroup) {
  const ids = groupSelectableIds(group)
  return ids.length > 0 && ids.every((id) => selectedMessageIds.value.includes(id))
}
function toggleSelectGroup(group: MessageGroup) {
  const ids = groupSelectableIds(group)
  selectedMessageIds.value = isGroupFullySelected(group)
    ? selectedMessageIds.value.filter((id) => !ids.includes(id))
    : [...new Set([...selectedMessageIds.value, ...ids])]
}
/** 一次请求处理整页或整组；后端逐条复用单条处理的权限与终态规则。 */
async function runBulkMessageAction(action: 'processed' | 'ignored', explicitIds?: number[]) {
  const candidates = [...new Set(explicitIds ?? selectedMessageIds.value)]
    .filter((id) => selectableIdSet.value.has(id))
  // 撤回消息没有可处理的正文，不能批量「标记已处理」；但可以批量「忽略」。
  const targetIds = action === 'processed'
    ? candidates.filter((id) => messages.value.find((item) => item.id === id)?.content_state !== 'revoked')
    : candidates
  if (targetIds.length === 0 || bulkActionRunning.value) {
    if (candidates.length > 0 && targetIds.length === 0) {
      bulkActionNotice.value = '选中的都是已撤回消息，不能标记已处理；请使用「批量忽略」清理。'
    }
    return
  }
  bulkActionRunning.value = true
  bulkActionNotice.value = ''
  bulkActionError.value = ''
  actionError.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    const result = await inboxApi.bulkUpdateMessageHandling(targetIds, action, csrf.csrf_token)
    const updatedIds = new Set(result.updated_message_ids)
    const updatedInquiryIds = new Set(result.updated_inquiry_ids)
    // 询盘整组处理会连带处理同链路的兄弟消息，一并从待办列表移除。
    messages.value = messages.value.filter((message) =>
      !updatedIds.has(message.id)
      && !(message.inquiry_id !== null && updatedInquiryIds.has(message.inquiry_id)),
    )
    selectedMessageIds.value = selectedMessageIds.value.filter((id) => !targetIds.includes(id))
    const label = action === 'processed' ? '已处理' : '已忽略'
    const affected = result.updated_message_ids.length + result.updated_inquiry_ids.length
    const reasons = [...new Set(result.skipped.map((item) => item.detail))].slice(0, 2).join('；')
    bulkActionNotice.value = result.skipped.length > 0
      ? `已${label} ${affected} 项；跳过 ${result.skipped.length} 项${reasons ? `（${reasons}）` : ''}。`
      : `已${label} ${affected} 项。`
    showActionToast(bulkActionNotice.value, action)
    if (archiveOpen.value || processedBoxOpen.value) void loadArchive()
    scheduleAnalysisRefresh()
  } catch (cause) {
    bulkActionError.value = cause instanceof Error ? cause.message : '批量处理失败，请稍后重试。'
  } finally {
    bulkActionRunning.value = false
  }
}
watch([workspaceView, messageHandlingFilter, messagePage], clearMessageSelection)
const logoutError = ref('')
const refetchChecks = ref<Record<number, RefetchCheck>>({})
const refetchCheckingAccountIds = ref<Set<number>>(new Set())
let whatsappPollTimer: number | undefined

/** WhatsApp group -> customer phone bindings: 100% operator-confirmed. */
const groupBindingOpen = ref(false)
const groupBindings = ref<WhatsappGroupBinding[]>([])
let groupBindingsLoaded = false
const groupBindingCandidates = ref<WhatsappPhoneCandidate[]>([])
const groupBindingLoading = ref(false)
const groupBindingError = ref('')
const groupBindingSubmitting = ref(false)
const groupBindingSelectedPhone = ref('')
const groupBindingPhoneInput = ref('')
const groupBindingNote = ref('')
const groupBindingFeedback = ref<{ text: string; kind: 'success' | 'error' } | null>(null)
let groupBindingRequestId = 0

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
  revoked: '连接已断开并清理；已收集的历史消息会归档保留。',
}

// A user can own several shells of the same channel type (revoked leftovers
// and a live transferred account). Always show the usable one, never the dead
// shell with the lowest id — that used to make "开始授权" fail with 403.
const realAccounts = computed(() => {
  const result = new Map<ChannelType, ChannelAccount>()
  for (const account of accounts.value) {
    if (!managedChannelTypes.includes(account.channel_type as ChannelType)) continue
    const key = account.channel_type as ChannelType
    const current = result.get(key)
    if (!current) {
      result.set(key, account)
      continue
    }
    const currentUsable = current.status !== 'revoked'
    const nextUsable = account.status !== 'revoked'
    if ((!currentUsable && nextUsable) || (currentUsable === nextUsable && account.id < current.id)) {
      result.set(key, account)
    }
  }
  return result
})

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
  if (!window.confirm(`确认撤销并清理本地 ${label} 连接？未产生消息的空账号会被彻底删除；已收集的历史消息会归档保留。`)) return
  try {
    const csrf = await inboxApi.getCsrf()
    if (channelType === 'whatsapp') {
      await channelsApi.disconnectWhatsApp(account.id, csrf.csrf_token)
    } else {
      await channelsApi.revoke(account.id, csrf.csrf_token)
    }
    // Only the account list needs to change. A full workspace refetch used to
    // turn an already-successful cleanup into a visible failure.
    accounts.value = await channelsApi.accounts()
    const note = '连接已清理；可立即重新授权。如需撤销 provider 侧授权，请到对应账号设置中操作。'
    if (channelType === 'whatsapp') whatsappMessage.value = `WhatsApp ${note}`
    if (channelType === 'gmail') gmailMessage.value = `Gmail ${note}`
    if (channelType === 'outlook') outlookAuthorizationMessage.value = `Outlook ${note}`
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : `${label} 断开失败。`
    if (channelType === 'whatsapp') whatsappError.value = message
    if (channelType === 'gmail') gmailError.value = message
    if (channelType === 'outlook') outlookAuthorizationError.value = message
  }
}

const selectedInquiry = computed(() =>
  inquiryDetail.value ?? inquiries.value.find((inquiry) => inquiry.id === selectedInquiryId.value) ?? null,
)
const linkReviewMessage = computed(() => messages.value.find((message) => message.id === linkReviewMessageId.value) ?? null)
const selectedInquiryIndex = computed(() => inquiries.value.findIndex((item) => item.id === selectedInquiryId.value))
const isInquiryView = computed(() => workspaceView.value === 'review' || workspaceView.value === 'customers')
const standaloneTitle = computed(() => {
  if (route.value.page === 'inquiry') return `客户链路 #${route.value.id ?? ''}`
  if (route.value.page === 'message') return `消息 #${route.value.id ?? ''}`
  if (route.value.page === 'logs') return route.value.logsInquiry === null ? '我的操作记录' : `链路 #${route.value.logsInquiry} 操作记录`
  if (route.value.page === 'settings') return '接入账号与个人设置'
  if (route.value.page === 'groupBinding') return '群聊客户归属确认'
  return ''
})

/** The list view a Back / breadcrumb should land on for the current standalone page. */
function parentRoute(): Partial<AppRoute> {
  return { page: route.value.view, id: null, logsInquiry: null, groupJid: null }
}

function closeStandalonePage() {
  goBack(parentRoute())
}

/** Each tab is an addressable page; view state lives in the URL, not only in refs. */
function switchWorkspaceView(view: WorkspaceView) {
  if (isAdmin.value && view !== 'customers') return
  if (['sales', 'engineering', 'procurement', 'production'].includes(currentUser.value?.role ?? '') && view !== 'customers') return
  navigate({
    page: view,
    view,
    id: null,
    logsInquiry: null,
    mpage: 1,
    ipage: 1,
    mh: 'pending',
    mi: '',
    ma: view === 'customerMessages' ? 'assigned' : 'all',
    mc: '',
    ih: view === 'review' ? 'pending' : '',
    box: '',
    groupJid: null,
  })
}

/** A message opened from logs / an inquiry is its own page, not an in-page jump. */
/**
 * 「查看客户消息」= 就地查看这条消息的安全文本（运营同事入站清洗后的原文）。
 * 之前是跳到消息详情整页，还要再点一次「查看原文」，等于把一步操作拆成两次跳转。
 */
/**
 * 后端回源确认「其实有原文」后，会持久化修复该行。这里同步纠正本地状态，
 * 否则弹窗显示完整原文、背后的链路却仍写着「已撤回 / 原文不再可用」。
 */
function applyRecoveredMessageBody(messageId: number, content: CustomerMessageContent) {
  if (content.content_state !== 'ready') return
  const text = content.parsed_content?.display_text || content.preview_text || ''
  if (!text) return
  const excerpt = text.length > 280 ? `${text.slice(0, 279).trimEnd()}…` : text
  const linked = inquiryDetail.value?.messages.find((item) => item.id === messageId)
  if (linked && linked.content_state === 'revoked') {
    linked.content_state = 'ready'
    linked.safe_content_status = 'ready'
    linked.safe_text = text
    linked.safe_text_truncated = false
    linked.overview_status = 'not_generated'
    linked.overview_text = null
  }
  const row = messages.value.find((item) => item.id === messageId)
  if (row && row.content_state === 'revoked') {
    row.content_state = 'ready'
    row.display_text = text
    row.display_excerpt = excerpt
    row.overview = null
  }
}

async function openCustomerMessage(messageId: number) {
  customerMessageId.value = messageId
  customerMessageContent.value = null
  customerMessageError.value = ''
  customerMessageCopied.value = false
  customerMessageLoading.value = true
  try {
    const content = await inboxApi.getMessageContent(messageId)
    if (customerMessageId.value !== messageId) return
    customerMessageContent.value = content
    const wasRevoked = inquiryDetail.value?.messages.some(
      (item) => item.id === messageId && item.content_state === 'revoked',
    ) || messages.value.some(
      (item) => item.id === messageId && item.content_state === 'revoked',
    )
    if (wasRevoked && content.content_state === 'ready') {
      applyRecoveredMessageBody(messageId, content)
      // 后端已重新生成中文概述，拉一次链路详情把小字概要同步回来。
      if (selectedInquiryId.value !== null) void loadInquiryDetail(selectedInquiryId.value, applyToken)
    }
  } catch (cause) {
    if (customerMessageId.value !== messageId) return
    customerMessageError.value = cause instanceof Error ? cause.message : '读取客户消息失败，请稍后重试。'
  } finally {
    if (customerMessageId.value === messageId) customerMessageLoading.value = false
  }
}

function retryCustomerMessage() {
  if (customerMessageId.value === null) return
  void openCustomerMessage(customerMessageId.value)
}

function closeCustomerMessage() {
  customerMessageId.value = null
  customerMessageContent.value = null
  customerMessageError.value = ''
  customerMessageCopied.value = false
  customerMessageLoading.value = false
}

const customerMessageRevoked = computed(() => customerMessageContent.value?.content_state === 'revoked')

const customerMessageText = computed(() => {
  const content = customerMessageContent.value
  if (!content) return ''
  return content.parsed_content?.display_text || content.preview_text || ''
})

async function copyCustomerMessage() {
  const text = customerMessageText.value
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    customerMessageCopied.value = true
  } catch {
    customerMessageCopied.value = false
    customerMessageError.value = '浏览器未允许写入剪贴板，请手动选择文本复制。'
  }
}

function goToInquiryPage(page: number, preferredIndex?: number) {
  const targetPage = Math.max(1, Math.min(page, inquiryTotalPages.value))
  if (targetPage === inquiryPage.value || filterLoading.value) return
  const keepDetailOpen = selectedInquiryId.value !== null
  pendingInquirySelection = keepDetailOpen ? (preferredIndex ?? Math.max(0, selectedInquiryIndex.value)) : null
  navigate({ ipage: targetPage }, true)
}

function resetInquiryFilters() {
  pendingInquirySelection = null
  navigate({ ipage: 1, ih: '', id: null }, true)
}

async function moveInquiry(delta: number) {
  const index = selectedInquiryIndex.value + delta
  if (index >= 0 && index < inquiries.value.length) {
    selectInquiry(inquiries.value[index].id)
  } else if (delta > 0 && inquiryHasMore.value) {
    goToInquiryPage(inquiryPage.value + 1, 0)
  } else if (delta < 0 && inquiryPage.value > 1) {
    goToInquiryPage(inquiryPage.value - 1, INQUIRY_PAGE_SIZE - 1)
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
  navigate({ page: 'inquiry', id })
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

/** 全文展开态：只有该消息可展开且用户点了「展示全文」才成立。 */
function isMessageExpanded(messageId: number) {
  return Boolean(messageContentFor(messageId)?.can_expand) && fullMessageContentIds.value.has(messageId)
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

/** The analysis endpoint runs ~20 SQL statements (two full-table loads).
 *  Debounce it so a burst of operator actions triggers at most one request,
 *  and never on the critical path of a click. */
let analysisRefreshTimer: number | undefined
function scheduleAnalysisRefresh() {
  if (analysisRefreshTimer !== undefined) window.clearTimeout(analysisRefreshTimer)
  analysisRefreshTimer = window.setTimeout(() => {
    analysisRefreshTimer = undefined
    void refreshAnalysisCounts()
  }, 4000)
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

async function loadEmployees() {
  if (!isAdmin.value) return
  try {
    employeeRecords.value = await inboxApi.getEmployees()
    employeeError.value = ''
  } catch (cause) {
    employeeError.value = cause instanceof Error ? cause.message : '员工列表加载失败。'
  }
  await loadAdminChannelAccounts()
}

async function loadAdminChannelAccounts() {
  if (!isAdmin.value) return
  adminChannelAccountsLoading.value = true
  try {
    adminChannelAccounts.value = await inboxApi.listAdminChannelAccounts()
    const validIds = adminChannelAccounts.value.map((item) => item.id)
    selectedAdminChannelAccountIds.value = adminChannelSelectionInitialized.value
      ? validIds.filter((id) => selectedAdminChannelAccountIds.value.includes(id))
      : adminChannelAccounts.value.filter((item) => adminChannelOwnerIsAdmin(item.owner_user_id)).map((item) => item.id)
    adminChannelSelectionInitialized.value = true
  } catch (cause) {
    adminChannelFeedback.value = { kind: 'error', title: '加载失败', text: cause instanceof Error ? cause.message : '渠道账号列表加载失败。' }
  } finally {
    adminChannelAccountsLoading.value = false
  }
}

function adminChannelOwner(ownerId: number) {
  const employee = employeeRecords.value.find((item) => item.id === ownerId)
  return employee ? `${employee.username} · #${ownerId}` : `用户 #${ownerId}`
}

async function regrantChannelHistory(account: AdminChannelAccount) {
  if (!isAdmin.value || regrantingAccountId.value !== null) return
  regrantingAccountId.value = account.id
  adminChannelFeedback.value = null
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.regrantChannelHistory(account.id, csrf.csrf_token)
    await loadEmployees()
    adminChannelFeedback.value = {
      kind: 'success',
      title: '恢复成功',
      text: `已恢复 ${account.channel_type} 账号 #${account.id} 的历史访问。请让该员工刷新页面后重新点击「开始授权」。`,
    }
  } catch (cause) {
    adminChannelFeedback.value = { kind: 'error', title: '恢复失败', text: cause instanceof Error ? cause.message : '恢复历史访问失败。' }
  } finally {
    regrantingAccountId.value = null
  }
}

function openEmployeeAdminFromChannels() {
  profileOpen.value = false
  navigate({ page: 'customers', view: 'customers', id: null }, true)
  employeeAdminOpen.value = true
  void loadEmployees()
}

async function transferChannelAccountsOwner(accountIds: number[]) {
  if (!isAdmin.value || channelTransferSubmitting.value) return
  const targetId = Number(transferTargetUserId.value)
  const ids = [...new Set(accountIds)]
  if (!targetId) {
    adminChannelFeedback.value = { kind: 'error', title: '无法转移', text: '请先在上方选择接收渠道账号的运营员工。' }
    return
  }
  if (ids.length === 0) {
    adminChannelFeedback.value = { kind: 'error', title: '无法转移', text: '请先勾选需要转移归属的渠道账号。' }
    return
  }
  channelTransferSubmitting.value = true
  adminChannelFeedback.value = null
  try {
    const csrf = await inboxApi.getCsrf()
    const result = await inboxApi.transferChannelAccountsOwner(ids, targetId, csrf.csrf_token)
    await loadEmployees()
    const parts = [`已将 ${result.transferred.length} 个渠道账号转给 ${result.owner_username}。`]
    if (result.preauthorizations_granted.length > 0) {
      parts.push(`已自动补齐渠道预授权：${result.preauthorizations_granted.join('、')}。`)
    }
    if (result.retired_shells.length > 0) {
      const removed = result.retired_shells.filter((item) => item.deleted).map((item) => `#${item.id}`)
      const archived = result.retired_shells.filter((item) => !item.deleted).map((item) => `#${item.id}`)
      if (removed.length > 0) parts.push(`已彻底清除 ${removed.length} 个未连接/已撤销的旧账号（${removed.join('、')}）。`)
      if (archived.length > 0) parts.push(`另有 ${archived.length} 个旧账号含历史消息，已停用并归档（${archived.join('、')}），数据保留。`)
    }
    if (result.skipped.length > 0) {
      parts.push(`跳过 ${result.skipped.length} 个（${result.skipped.map((item) => `#${item.id} ${item.reason}`).join('；')}）。`)
    }
    parts.push('历史消息无需重连，让该员工刷新页面后即可在渠道工作台看到并处理。')
    adminChannelFeedback.value = {
      kind: result.transferred.length > 0 ? 'success' : 'error',
      title: result.transferred.length > 0 ? '归属转移完成' : '未转移任何账号',
      text: parts.join(''),
    }
  } catch (cause) {
    adminChannelFeedback.value = { kind: 'error', title: '转移失败', text: cause instanceof Error ? cause.message : '渠道账号归属转移失败。' }
  } finally {
    channelTransferSubmitting.value = false
  }
}

function focusEmployeeCreateField(name: string) {
  const field = employeeCreateFormEl.value?.elements.namedItem(name)
  if (field instanceof HTMLElement) field.focus()
}

function scrollToEmployeeTable() {
  employeeTableCardEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

async function createEmployee() {
  if (!isAdmin.value || employeeCreating.value) return
  const fullName = employeeForm.value.full_name.trim()
  const username = employeeForm.value.username.trim()
  const role = employeeForm.value.role
  const department = employeeForm.value.department.trim()
  const temporaryPassword = employeeForm.value.temporary_password
  if (!fullName) {
    employeeCreateFeedback.value = { kind: 'error', text: '请先填写员工姓名（例如 张三），它会显示在员工列表和询盘负责人处。' }
    focusEmployeeCreateField('full_name')
    return
  }
  if (!username) {
    employeeCreateFeedback.value = { kind: 'error', text: '请先填写用户名（例如 zhang.san），再创建员工。' }
    focusEmployeeCreateField('username')
    return
  }
  if (!department) {
    employeeCreateFeedback.value = { kind: 'error', text: '所有账号都必须填写所属部门。' }
    focusEmployeeCreateField('department')
    return
  }
  if (temporaryPassword.length < 6 || temporaryPassword.length > 15) {
    employeeCreateFeedback.value = { kind: 'error', text: '临时密码长度必须为 6–15 位，请重新输入。' }
    focusEmployeeCreateField('temporary_password')
    return
  }
  employeeCreating.value = true
  employeeCreateFeedback.value = null
  employeeError.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    const created = await inboxApi.createEmployee(
      { full_name: fullName, username, role, department, manager_overlay_enabled: employeeForm.value.manager_overlay_enabled, temporary_password: temporaryPassword },
      csrf.csrf_token,
    )
    employeeForm.value = { full_name: '', username: '', role: 'sales', department: '', manager_overlay_enabled: false, temporary_password: '' }
    employeeSearch.value = ''
    employeeRoleFilter.value = 'all'
    employeeStatusFilter.value = 'all'
    await loadEmployees()
    const identity = created?.id ? `（编号 #${created.id}）` : ''
    const displayName = created?.full_name || created?.username || username
    employeeCreateFeedback.value = {
      kind: 'success',
      text: `员工「${displayName}」${identity}已创建，并已出现在下方员工列表中。请将临时密码通过安全渠道告知本人；对方首次登录须先修改密码。`,
    }
  } catch (cause) {
    employeeCreateFeedback.value = { kind: 'error', text: cause instanceof Error ? cause.message : '创建员工失败，请稍后重试。' }
  } finally {
    employeeCreating.value = false
  }
}

function changeEmployeeRole(user: EmployeeRecord, event: Event) {
  const role = (event.target as HTMLSelectElement).value
  const department = user.department || ''
  if (!department) {
    employeeError.value = '所有账号都必须填写所属部门。'
    return
  }
  void updateEmployee(user, role, department, undefined, employee.manager_overlay_enabled)
}

function changeEmployeeDepartment(user: EmployeeRecord, event: Event) {
  const department = (event.target as HTMLInputElement).value.trim()
  if (!department) {
    employeeError.value = '所有账号都必须填写所属部门。'
    void loadEmployees()
    return
  }
  void updateEmployee(user, user.role, department, undefined, user.manager_overlay_enabled)
}

function changeEmployeeManagerOverlay(user: EmployeeRecord, event: Event) {
  const enabled = (event.target as HTMLInputElement).checked
  void updateEmployee(user, user.role, user.department, undefined, enabled)
}

function changeEmployeeFullName(user: EmployeeRecord, event: Event) {
  const fullName = (event.target as HTMLInputElement).value.trim()
  if (!fullName) {
    employeeError.value = '员工姓名不能为空。'
    void loadEmployees()
    return
  }
  if (fullName === (user.full_name || '')) return
  void updateEmployee(user, user.role, user.department, fullName, user.manager_overlay_enabled)
}

async function updateEmployee(user: EmployeeRecord, role: string, department: string | null, fullName?: string, managerOverlayEnabled?: boolean) {
  if (!isAdmin.value) return
  employeeError.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.mapEmployee(user.id, { role, department, full_name: fullName, manager_overlay_enabled: managerOverlayEnabled ?? user.manager_overlay_enabled }, csrf.csrf_token)
    await loadEmployees()
  } catch (cause) {
    employeeError.value = cause instanceof Error ? cause.message : '更新员工失败。'
  }
}

/** 改派下拉的人群标签：姓名为主，账号作为副标识，避免同名人选错。 */
function transferTargetLabel(target: TransferTarget) {
  const name = target.full_name || target.username
  return name === target.username ? name : `${name}（${target.username}）`
}

/** 员工展示名：优先姓名，回退用户名。 */
function employeeDisplayName(employee: EmployeeRecord) {
  return employee.full_name || employee.username
}

async function grantManagerPermission(manager: EmployeeRecord) {
  const targetUserId = Number(employeeManagerTargetById.value[manager.id] || 0)
  const permission = employeeManagerPermissionById.value[manager.id] || ''
  if (!isAdmin.value || !targetUserId || !permission || !manager.department) return
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.grantManagerPermission(manager.id, targetUserId, manager.department, permission, csrf.csrf_token)
    await loadEmployees()
  } catch (cause) {
    employeeError.value = cause instanceof Error ? cause.message : '经理权限授予失败。'
  }
}

async function revokeManagerPermission(manager: EmployeeRecord, grant: EmployeeRecord['manager_grants'][number]) {
  if (!isAdmin.value) return
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.revokeManagerPermission(manager.id, grant.target_user_id, grant.permission, csrf.csrf_token)
    await loadEmployees()
  } catch (cause) {
    employeeError.value = cause instanceof Error ? cause.message : '经理权限撤销失败。'
  }
}

async function grantEmployeeDepartment(userId: number) {
  const department = employeeGrantDepartmentById.value[userId]?.trim() || ''
  if (!isAdmin.value || !department) return
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.grantDepartment(userId, department, csrf.csrf_token)
    employeeGrantDepartmentById.value = { ...employeeGrantDepartmentById.value, [userId]: '' }
    await loadEmployees()
  } catch (cause) {
    employeeError.value = cause instanceof Error ? cause.message : '部门授权失败。'
  }
}

async function revokeEmployeeDepartment(userId: number, department: string) {
  if (!isAdmin.value) return
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.revokeDepartment(userId, department, csrf.csrf_token)
    await loadEmployees()
  } catch (cause) {
    employeeError.value = cause instanceof Error ? cause.message : '撤销部门授权失败。'
  }
}

async function changeEmployeeChannel(user: EmployeeRecord, channel: string, grant: boolean) {
  if (!isAdmin.value) return
  const operationKey = `${user.id}:${channel}`
  if (employeeChannelPending.value) return
  employeeChannelPending.value = operationKey
  employeeChannelFeedback.value = null
  try {
    const csrf = await inboxApi.getCsrf()
    if (grant) await inboxApi.grantChannel(user.id, channel, csrf.csrf_token)
    else await inboxApi.revokeChannel(user.id, channel, csrf.csrf_token)
    await loadEmployees()
    const channelLabel = employeeChannelOptions.find((item) => item.key === channel)?.label ?? channel
    employeeChannelFeedback.value = {
      kind: 'success',
      text: `已${grant ? '授予' : '撤销'} ${user.username} 的 ${channelLabel} 渠道预授权。`,
    }
  } catch (cause) {
    employeeChannelFeedback.value = {
      kind: 'error',
      text: cause instanceof Error ? cause.message : '渠道预授权变更失败。',
    }
  } finally {
    employeeChannelPending.value = null
  }
}

async function resetEmployee(user: EmployeeRecord) {
  if (!isAdmin.value || employeeResetPendingId.value !== null) return
  const temporaryPassword = employeeResetPasswordById.value[user.id] ?? ''
  employeeResetFeedback.value = null
  if (temporaryPassword.length < 6 || temporaryPassword.length > 15) {
    flashEmployeeReset(user.id, 'error', `请先填写 6–15 位新临时密码，再点击「重置密码」。`)
    employeeResetPasswordById.value = { ...employeeResetPasswordById.value, [user.id]: '' }
    return
  }
  employeeResetPendingId.value = user.id
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.resetEmployeePassword(user.id, temporaryPassword, csrf.csrf_token)
    employeeResetPasswordById.value = { ...employeeResetPasswordById.value, [user.id]: '' }
    await loadEmployees()
    employeeError.value = ''
    flashEmployeeReset(
      user.id,
      'success',
      `已重置 ${employeeDisplayName(user)}（${user.username}）的登录密码。请把新临时密码单独告知本人，其下次登录必须先修改密码。`,
    )
  } catch (cause) {
    flashEmployeeReset(user.id, 'error', cause instanceof Error ? cause.message : '密码重置失败，请重试。')
  } finally {
    employeeResetPendingId.value = null
  }
}

async function deactivateEmployee(user: EmployeeRecord) {
  if (!isAdmin.value) return
  if (employeeConfirmDeactivateId.value !== user.id) {
    employeeConfirmDeactivateId.value = user.id
    return
  }
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.deactivateEmployee(user.id, csrf.csrf_token)
    employeeConfirmDeactivateId.value = null
    if (expandedEmployeeId.value === user.id) expandedEmployeeId.value = null
    await loadEmployees()
  } catch (cause) {
    employeeError.value = cause instanceof Error ? cause.message : '停用员工失败。'
  }
}

async function reactivateEmployee(user: EmployeeRecord) {
  if (!isAdmin.value) return
  if (employeeConfirmReactivateId.value !== user.id) {
    employeeConfirmReactivateId.value = user.id
    return
  }
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.reactivateEmployee(user.id, csrf.csrf_token)
    employeeConfirmReactivateId.value = null
    employeeError.value = ''
    await loadEmployees()
  } catch (cause) {
    employeeError.value = cause instanceof Error ? cause.message : '启用员工失败。'
  }
}

function openOperationLogs(inquiryId?: number) {
  navigate({ page: 'logs', id: null, logsInquiry: inquiryId ?? null })
}

/** Load logs for the standalone logs page (also used by its retry button). */
async function fetchOperationLogs(inquiryId: number | null) {
  operationLogLoading.value = true
  try {
    operationLogs.value = await inboxApi.getOperationLogs(inquiryId ?? undefined)
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '操作记录加载失败。'
  } finally {
    operationLogLoading.value = false
  }
}

function openOperationLogObject(record: OperationLog) {
  if (isAdmin.value || record.object_type !== 'message' || record.object_id === null) return
  navigate({ page: 'message', id: record.object_id })
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
  if (!canOperateChannels.value && !isAdmin.value) return
  try {
    const [processed, ignored] = await Promise.all([
      inboxApi.getMessages(queryString({ handling_status: 'processed', page: '1', page_size: '50', sort: 'occurred_at', descending: 'true' })),
      inboxApi.getMessages(queryString({ handling_status: 'ignored', page: '1', page_size: '50', sort: 'occurred_at', descending: 'true' })),
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
    await refreshList()
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
    actionMessage.value = '消息已恢复到待处理；链路状态仅在当前账号有权查看该链路时同步恢复。'
    // Archive + list refresh happen in the background; the button returns immediately.
    void loadArchive()
    void refreshList('list')
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

function accountLabel(accountId: number | undefined) {
  if (accountId === undefined) return '账号不可见'
  const account = accountById.value.get(accountId)
  return account?.external_account_id || (account ? `${channelLabel(account.channel_type)} #${account.id}` : `账号 #${accountId}`)
}

function accountStatus(accountId: number | undefined) {
  if (accountId === undefined) return undefined
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

/**
 * 客户双端删除/撤回的协议消息没有正文，不是「待处理」的工作项。
 * 列表、链路详情、消息详情共用这一个状态口径。
 */
function messageStatusLabel(message: { content_state?: string | null; safe_content_status?: string | null; handling_status: string }) {
  return message.content_state === 'revoked' || message.safe_content_status === 'revoked'
    ? '已撤回'
    : handlingStatusLabel(message.handling_status)
}

/** 中文概述只是辅助信息：正文之后以一行小字补充，不再作为首屏主内容。 */
function linkedOverviewText(linkedMessage: Inquiry['messages'][number]) {
  if (linkedMessage.overview_text) return linkedMessage.overview_text
  if (linkedMessage.overview_status === 'pending') return '正在生成。'
  if (linkedMessage.overview_status === 'failed') return '生成失败，可在消息收件箱重试。'
  return '暂无中文概述。'
}

function adminMessageStatus(linkedMessage: Inquiry['messages'][number]) {
  if (linkedMessage.safe_content_status === 'revoked' || linkedMessage.overview_status === 'not_applicable_revoked') {
    return { text: '用户已撤回，无需生成中文概要。', tone: 'neutral' as const }
  }
  if (linkedMessage.safe_content_status === 'ready') {
    if (linkedMessage.overview_status === 'ready') {
      return { text: '安全正文展示成功 · 中文概要生成成功。', tone: 'success' as const }
    }
    if (linkedMessage.overview_status === 'failed') return { text: '安全正文展示成功 · 中文概要生成失败。', tone: 'failure' as const }
    if (linkedMessage.overview_status === 'pending') return { text: '安全正文展示成功 · 中文概要生成中。', tone: 'neutral' as const }
    return { text: '安全正文展示成功 · 中文概要尚未生成。', tone: 'neutral' as const }
  }
  if (linkedMessage.overview_status === 'failed') return { text: '中文概要生成失败。', tone: 'failure' as const }
  if (linkedMessage.overview_status === 'pending') return { text: '中文概要生成中。', tone: 'neutral' as const }
  return { text: '中文概要状态未知。', tone: 'neutral' as const }
}

function inquiryEventLabel(eventType: string) {
  const labels: Record<string, string> = {
    inquiry_created: '客户链路已创建',
    inquiry_transferred: '已分配负责人',
    inquiry_processed: '标记为已处理',
    inquiry_ignored: '已忽略此链路',
    inquiry_reactivated: '客户链路已恢复',
    inquiry_message_linked: '关联客户消息',
    manual_link: '人工确认并关联身份',
  }
  return labels[eventType] ?? eventType
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

/** 诊断结果的三种语义：可用 / 尚未关联（非故障）/ 需要处理。 */
function refetchTone(check: RefetchCheck | undefined) {
  if (!check) return ''
  if (check.ready || check.severity === 'ok') return 'ok'
  return check.severity === 'not_ready' ? 'info' : 'warn'
}

const refetchFailureTitles: Record<string, string> = {
  credentials_missing: '尚未保存授权凭据',
  credential_decrypt_failed: '凭据无法解密',
  oauth_config_missing: 'OAuth 配置不完整',
  authorization_expired: '授权已失效，需要重新授权',
  provider_unavailable: 'provider 返回错误',
  network_unavailable: '服务器暂时无法访问 provider',
  session_offline: 'WhatsApp 设备尚未关联',
  bridge_unreachable: 'WhatsApp bridge 不可达',
  adapter_not_configured: 'WhatsApp bridge 未配置',
  unsupported_channel: '该渠道不支持实时回源',
  unknown: '回源链路出现未知错误',
}

function refetchTitle(check: RefetchCheck | undefined) {
  if (!check) return ''
  if (check.ready) return '实时回源链路可用'
  return refetchFailureTitles[check.failure_kind || 'unknown'] || '实时回源不可用'
}

/** 只展示定位所需的非敏感信息：失败域名、错误类型与传输层原因。 */
function refetchMeta(check: RefetchCheck | undefined) {
  if (!check || check.ready) return ''
  const parts: string[] = []
  if (check.network?.host) parts.push(`失败域名 ${check.network.host}`)
  if (check.network?.label) parts.push(check.network.label)
  if (check.error_class) parts.push(check.error_class)
  return parts.join(' · ')
}

async function logoutSystemAccount() {
  logoutError.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.logout(csrf.csrf_token)
  } catch (cause) {
    // A session the server already rejects is effectively logged out too.
    if (!(cause instanceof ApiError && [401, 403, 404].includes(cause.status))) {
      logoutError.value = cause instanceof Error ? cause.message : '退出登录失败，请稍后重试。'
      return
    }
  }
  clearCsrfCache()
  currentUser.value = null
  // Assigning a URL that differs only by the fragment is a same-document
  // navigation: the SPA would stay mounted and never show the login gate.
  history.replaceState(null, '', window.location.pathname + window.location.search)
  window.location.reload()
}

/**
 * `full` = first paint (accounts + user + list), `list` = only the list the
 * current page needs, `base` = accounts + user only (standalone detail pages).
 * Previously every filter change and every action re-issued 3-4 requests and
 * waited serially for a 200-row archive fetch on top of that.
 */
async function loadWorkspace(mode: 'full' | 'list' | 'base' = 'list'): Promise<boolean> {
  const initialLoad = currentUser.value === null
  if (initialLoad) loading.value = true
  filterLoading.value = true
  error.value = ''
  unauthorized.value = false

  try {
    const emptyMessagePage = { items: [] as Message[], page: messagePage.value, page_size: 20, has_more: false }
    const emptyInquiryPage = { items: [] as Inquiry[], page: inquiryPage.value, page_size: INQUIRY_PAGE_SIZE, has_more: false, total_count: 0 }
    const loadList = mode !== 'base'
    const needAccounts = mode !== 'list' || accounts.value.length === 0
    if (currentUser.value === null) {
      currentUser.value = await inboxApi.getCurrentUser()
      const role = currentUser.value.role
      const restrictedRole = role === 'sales' || ['engineering', 'procurement', 'production'].includes(role)
      const allowedView = role === 'admin'
        ? route.value.view === 'customers'
        : restrictedRole ? route.value.view === 'customers' : true
      const initialListMismatch = !isStandalonePage(route.value.page) && route.value.page !== route.value.view
      const knownRole = ['admin', 'sales', 'engineering', 'procurement', 'production', 'staff', 'operations', 'ops'].includes(role)
      if (!knownRole || !allowedView || initialListMismatch
        || (role === 'admin' && !['customers', 'inquiry', 'settings'].includes(route.value.page))
        || (restrictedRole && !canOperateChannels.value && !['customers', 'inquiry'].includes(route.value.page))
        || (!canOperateChannels.value && role !== 'admin' && ['settings', 'groupBinding', 'logs', 'message'].includes(route.value.page))) {
        navigate({ page: 'customers', view: 'customers', id: null, logsInquiry: null }, true)
        return false
      }
    }
    const needTargets = loadList && isInquiryView.value && (canOperateChannels.value || isAdmin.value) && (mode === 'full' || transferTargets.value.length === 0)
    const [nextChannelAccounts, nextMessages, nextInquiries, nextTargets, nextUser, nextGroupBindings] = await Promise.all([
      needAccounts && (canOperateChannels.value || isAdmin.value) ? channelsApi.accounts() : Promise.resolve(accounts.value),
      loadList && !isInquiryView.value ? inboxApi.getMessages(queryString({
        handling_status: messageHandlingFilter.value,
        assignment_status: workspaceView.value === 'customerMessages' ? 'assigned' : messageAssignmentFilter.value,
        ingestion_status: messageIngestionFilter.value,
        ...messageChannelFilterParams(),
        needs_review: '',
        page: String(messagePage.value), page_size: '20', sort: 'occurred_at', descending: 'true',
      })) : Promise.resolve(emptyMessagePage),
      loadList && isInquiryView.value ? inboxApi.getInquiries(queryString({
        status: isAdmin.value ? '' : workspaceView.value === 'customers' ? 'assigned' : workspaceView.value === 'review' ? 'new' : '',
        handling_status: inquiryHandlingFilter.value,
        page: String(inquiryPage.value), page_size: String(INQUIRY_PAGE_SIZE), sort: 'updated_at', descending: 'true',
      })) : Promise.resolve(emptyInquiryPage),
      needTargets ? inboxApi.getTransferTargets().catch((cause) => {
        if (cause instanceof ApiError && cause.status === 403) return [] as TransferTarget[]
        throw cause
      }) : Promise.resolve(transferTargets.value),
      Promise.resolve(currentUser.value!),
      // Small, cached, fetched in parallel: no extra serial round trip on first paint.
      // The standalone binding page loads bindings + candidates together itself.
      groupBindingsLoaded || route.value.page === 'groupBinding' || !canOperateChannels.value || isAdmin.value
        ? Promise.resolve(null)
        : inboxApi.getWhatsappGroupBindings().catch(() => [] as WhatsappGroupBinding[]),
    ])
    currentUser.value = nextUser
    accounts.value = nextChannelAccounts
    transferTargets.value = nextTargets
    if (nextGroupBindings !== null) {
      groupBindings.value = nextGroupBindings
      groupBindingsLoaded = true
    }
    if (loadList) {
      messages.value = nextMessages.items
      messagePage.value = nextMessages.page
      messageHasMore.value = nextMessages.has_more
      expandedMessageIds.value = new Set()
      fullMessageContentIds.value = new Set()
      messageContent.value = {}
      contentLoadingMessageIds.value = new Set()
      inquiries.value = nextInquiries.items
      inquiryHasMore.value = nextInquiries.has_more
      inquiryTotalCount.value = nextInquiries.total_count ?? (nextInquiries.has_more ? inquiryPage.value * INQUIRY_PAGE_SIZE + 1 : (inquiryPage.value - 1) * INQUIRY_PAGE_SIZE + nextInquiries.items.length)
      // Archive boxes are secondary data: never hold up the primary list.
      if (archiveOpen.value || processedBoxOpen.value) void loadArchive()
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

/** In-place refresh after a mutation; keeps URL and loaded-list signature intact. */
function refreshList(mode: 'full' | 'list' = 'list'): Promise<boolean> {
  return loadWorkspace(mode)
}

function listSignature(r: AppRoute): string {
  // Boxes are archive-only; toggling them must not refetch the primary list.
  return [r.view, r.mpage, r.ipage, r.mh, r.mi, r.ma, r.mc, r.ih].join('|')
}

let applyToken = 0
let pendingInquirySelection: number | null = null

/* ---- WhatsApp 群聊客户归属：纯人工绑定，绝不参与自动归链 ---- */

/** 群 JID 优先用与 bridge 一致的解析，兜底从分组 key 反解。 */
function groupJidOf(group: MessageGroup): string | null {
  if (group.scope !== 'group') return null
  const parsed = whatsappGroupJid(group.messages[0])
  if (parsed) return parsed
  const fallback = group.key.replace(/^group:[^:]+:/, '')
  return fallback || null
}

function groupBindingFor(group: MessageGroup): WhatsappGroupBinding | null {
  const jid = groupJidOf(group)
  if (!jid) return null
  return groupBindings.value.find((binding) => binding.group_jid === jid) ?? null
}

function openGroupBinding(group: MessageGroup) {
  const jid = groupJidOf(group)
  if (!jid) return
  navigate({ page: 'groupBinding', groupJid: jid })
}

const activeGroupJid = computed(() =>
  route.value.page === 'groupBinding' ? route.value.groupJid : null,
)
const activeGroupBinding = computed(() => {
  const jid = activeGroupJid.value
  return jid ? groupBindings.value.find((binding) => binding.group_jid === jid) ?? null : null
})
/** 手输优先于候选点选，两者互斥，避免运营误以为选中的候选生效。 */
const bindingPhone = computed(() => groupBindingPhoneInput.value.trim() || groupBindingSelectedPhone.value)

async function loadGroupBindingPage(jid: string | null, token: number) {
  if (!jid) {
    groupBindingError.value = '缺少群 JID，请从群聊分组卡片上的「确认群聊客户归属」进入此页面。'
    return
  }
  const requestId = ++groupBindingRequestId
  groupBindingLoading.value = true
  groupBindingError.value = ''
  groupBindingFeedback.value = null
  groupBindingSelectedPhone.value = ''
  groupBindingPhoneInput.value = ''
  groupBindingNote.value = ''
  try {
    const [bindings, candidates] = await Promise.all([
      inboxApi.getWhatsappGroupBindings(),
      inboxApi.getWhatsappPhoneCandidates(),
    ])
    if (token !== applyToken || requestId !== groupBindingRequestId) return
    groupBindings.value = bindings
    groupBindingsLoaded = true
    groupBindingCandidates.value = candidates
  } catch (cause) {
    if (token !== applyToken || requestId !== groupBindingRequestId) return
    groupBindingError.value = cause instanceof Error ? cause.message : '群聊归属信息加载失败。'
  } finally {
    if (token === applyToken && requestId === groupBindingRequestId) groupBindingLoading.value = false
  }
}

function selectGroupBindingCandidate(phone: string) {
  groupBindingSelectedPhone.value = groupBindingSelectedPhone.value === phone ? '' : phone
  groupBindingPhoneInput.value = ''
}

function onGroupBindingPhoneInput() {
  if (groupBindingPhoneInput.value.trim()) groupBindingSelectedPhone.value = ''
}

async function submitGroupBinding() {
  const jid = activeGroupJid.value
  const phone = bindingPhone.value
  if (!jid || !phone || groupBindingSubmitting.value) return
  groupBindingSubmitting.value = true
  groupBindingFeedback.value = null
  try {
    const csrf = await inboxApi.getCsrf()
    const updated = await inboxApi.bindWhatsappGroup(jid, phone, csrf.csrf_token, groupBindingNote.value.trim() || undefined)
    groupBindings.value = [...groupBindings.value.filter((item) => item.id !== updated.id), updated]
    groupBindingsLoaded = true
    groupBindingFeedback.value = {
      text: `已由人工确认：该群归属 ${updated.normalized_phone}。未改动任何消息，也未创建或修改询盘链路。`,
      kind: 'success',
    }
    groupBindingPhoneInput.value = ''
    groupBindingSelectedPhone.value = ''
    groupBindingNote.value = ''
  } catch (cause) {
    groupBindingFeedback.value = {
      text: cause instanceof Error ? cause.message : '绑定失败，请稍后重试。',
      kind: 'error',
    }
  } finally {
    groupBindingSubmitting.value = false
  }
}

async function removeGroupBinding() {
  const binding = activeGroupBinding.value
  if (!binding || groupBindingSubmitting.value) return
  groupBindingSubmitting.value = true
  groupBindingFeedback.value = null
  try {
    const csrf = await inboxApi.getCsrf()
    await inboxApi.unbindWhatsappGroup(binding.id, csrf.csrf_token)
    groupBindings.value = groupBindings.value.filter((item) => item.id !== binding.id)
    groupBindingsLoaded = true
    groupBindingFeedback.value = { text: '已解除该群的客户绑定，历史消息与链路未受影响。', kind: 'success' }
  } catch (cause) {
    groupBindingFeedback.value = {
      text: cause instanceof Error ? cause.message : '解绑失败，请稍后重试。',
      kind: 'error',
    }
  } finally {
    groupBindingSubmitting.value = false
  }
}

/** A directly opened detail URL never loaded the list, so targets may be empty. */
async function loadTransferTargets() {
  if (!canOperateChannels.value && !isAdmin.value) return
  try {
    transferTargets.value = await inboxApi.getTransferTargets()
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 403) transferTargets.value = []
  }
}

async function loadInquiryDetail(id: number, token: number) {
  try {
    const [inquiry] = await Promise.all([
      inboxApi.getInquiry(id),
      (canOperateChannels.value || isAdmin.value) && transferTargets.value.length === 0 ? loadTransferTargets() : Promise.resolve(),
    ])
    if (token !== applyToken) return
    inquiryDetail.value = inquiry
  } catch (cause) {
    if (token !== applyToken) return
    actionError.value = cause instanceof Error ? cause.message : '链路加载失败。'
  }
}

async function loadMessageDetail(id: number, token: number) {
  if ((!canOperateChannels.value && !isAdmin.value) || (isAdmin.value && !['messages', 'message'].includes(route.value.page))) return
  messageDetailLoading.value = true
  try {
    const message = await inboxApi.getMessage(id)
    if (token !== applyToken) return
    messageDetail.value = message
  } catch (cause) {
    if (token !== applyToken) return
    actionError.value = cause instanceof Error ? cause.message : '消息加载失败。'
  } finally {
    if (token === applyToken) messageDetailLoading.value = false
  }
}

/** Full original text is fetched only when the operator asks for it. */
async function loadMessageDetailContent() {
  if (!messageDetail.value || (!canOperateChannels.value && !isAdmin.value)) return
  const id = messageDetail.value.id
  messageDetailLoading.value = true
  try {
    messageDetailContent.value = await inboxApi.getMessageContent(id)
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '原文查看失败，请稍后重试。'
  } finally {
    messageDetailLoading.value = false
  }
}

async function reactivateSelectedInquiry() {
  if (!selectedInquiry.value) return
  handlingSubmitting.value = true
  actionError.value = ''
  actionMessage.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    const updated = await inboxApi.reactivateInquiry(selectedInquiry.value.id, csrf.csrf_token)
    inquiryDetail.value = updated
    actionMessage.value = '链路已恢复到待处理状态，可继续分配或处理。'
  } catch (cause) {
    actionError.value = cause instanceof Error ? cause.message : '链路恢复失败。'
  } finally {
    handlingSubmitting.value = false
  }
}

async function updateDetailMessageHandling(action: 'processed' | 'ignored') {
  if (!messageDetail.value) return
  const id = messageDetail.value.id
  await updateMessageHandling(messageDetail.value, action)
  await loadMessageDetail(id, applyToken)
}

async function restoreDetailMessage() {
  if (!messageDetail.value) return
  const id = messageDetail.value.id
  await restoreArchivedMessage(id)
  await loadMessageDetail(id, applyToken)
}

/** v-model changes are written back to the URL so refresh / Back keep filters. */
function onMessageFilterChange() {
  navigate({
    mh: messageHandlingFilter.value,
    mi: messageIngestionFilter.value,
    ma: messageAssignmentFilter.value,
    mc: messageChannelAccountFilter.value,
    mpage: 1,
  }, true)
}

function onInquiryFilterChange() {
  navigate({ ih: inquiryHandlingFilter.value, ipage: 1 }, true)
}

function toggleBox(box: 'processed' | 'ignored') {
  if (!canOperateChannels.value && !isAdmin.value) return
  const next = route.value.box === box ? '' : box
  navigate({ box: next }, true)
  if (next) void loadArchive()
}

function goToMessagePage(page: number) {
  if (page < 1 || (page > messagePage.value && !canLoadMoreMessages.value)) return
  navigate({ mpage: page }, true)
}

/** Single entry point for URL -> UI state. Back/forward with an unchanged list
 *  signature reuses already loaded data and issues zero HTTP requests. */
async function applyRoute(r: AppRoute, info: RouteChange) {
  const token = ++applyToken
  workspaceView.value = r.view
  messagePage.value = r.mpage
  inquiryPage.value = r.ipage
  messageHandlingFilter.value = r.mh
  messageIngestionFilter.value = r.mi
  messageAssignmentFilter.value = r.ma
  messageChannelAccountFilter.value = r.mc
  inquiryHandlingFilter.value = r.ih
  processedBoxOpen.value = (canOperateChannels.value || isAdmin.value) && r.box === 'processed'
  archiveOpen.value = (canOperateChannels.value || isAdmin.value) && r.box === 'ignored'
  profileOpen.value = r.page === 'settings'
  operationLogOpen.value = r.page === 'logs'
  operationLogInquiryId.value = r.logsInquiry
  groupBindingOpen.value = r.page === 'groupBinding'
  selectedInquiryId.value = null
  selectedMessageId.value = r.page === 'message' ? r.id : null
  selectedSalesUserId.value = null
  selectedBusinessType.value = null
  inquiryDetail.value = null
  messageDetail.value = null
  messageDetailContent.value = null
  closeLinkReview()
  actionError.value = ''
  actionMessage.value = ''

  const standalone = isStandalonePage(r.page)
  const role = currentUser.value?.role ?? ''
  const restrictedRole = role === 'sales' || ['engineering', 'procurement', 'production'].includes(role)
  const knownRole = ['admin', 'sales', 'engineering', 'procurement', 'production', 'staff', 'operations', 'ops'].includes(role)
  const allowedView = role === 'admin'
    ? r.view === 'customers'
    : restrictedRole ? r.view === 'customers' : true
  const listPageMismatch = !standalone && r.page !== r.view
  if (currentUser.value && (!knownRole || !allowedView || listPageMismatch
    || (restrictedRole && !canOperateChannels.value && !['customers', 'inquiry'].includes(r.page))
    || (isAdmin.value && !['customers', 'inquiry', 'settings'].includes(r.page))
    || (!canOperateChannels.value && !isAdmin.value && ['settings', 'groupBinding', 'logs', 'message'].includes(r.page)))) {
    navigate({ page: 'customers', view: 'customers', id: null, logsInquiry: null, box: '' }, true)
    return
  }
  if (!currentUser.value) {
    const ok = await loadWorkspace('base')
    if (token !== applyToken || !ok || !currentUser.value) return
    const bootRole = currentUser.value.role
    const bootRestricted = bootRole === 'sales' || ['engineering', 'procurement', 'production'].includes(bootRole)
    const bootKnown = ['admin', 'sales', 'engineering', 'procurement', 'production', 'staff', 'operations', 'ops'].includes(bootRole)
    const bootAllowedView = bootRole === 'admin'
      ? ['messages', 'customers'].includes(r.view)
      : bootRestricted ? r.view === 'customers' : true
    if (!bootKnown || !bootAllowedView
      || (bootRestricted && !canOperateChannels.value && !['customers', 'inquiry'].includes(r.page))
      || (isAdmin.value && !['customers', 'inquiry', 'messages', 'message', 'settings'].includes(r.page))
      || (!canOperateChannels.value && !isAdmin.value && ['settings', 'groupBinding', 'logs', 'message'].includes(r.page))) {
      navigate({ page: 'customers', view: 'customers', id: null, logsInquiry: null, box: '' }, true)
      return
    }
  }
  const signature = listSignature(r)
  if (!standalone) {
    if (info.initial || signature !== loadedListSignature) {
      const ok = await loadWorkspace(info.initial ? 'full' : 'list')
      if (token !== applyToken) return
      if (!ok) return
      loadedListSignature = signature
    }
    if (pendingInquirySelection !== null) {
      const index = Math.min(pendingInquirySelection, inquiries.value.length - 1)
      selectedInquiryId.value = inquiries.value[index]?.id ?? null
      pendingInquirySelection = null
    }
  } else if (info.initial) {
    const ok = await loadWorkspace('base')
    if (token !== applyToken || !ok) return
    loading.value = false
  }

  if (r.page === 'inquiry' && r.id !== null) await loadInquiryDetail(r.id, token)
  else if (r.page === 'message' && r.id !== null) await loadMessageDetail(r.id, token)
  else if (r.page === 'logs') await fetchOperationLogs(r.logsInquiry)
  else if (r.page === 'groupBinding') await loadGroupBindingPage(r.groupJid, token)
  else if (r.page === 'settings' && accounts.value.length === 0) await loadWorkspace('base')

  if (info.initial && !isAdmin.value && canOperateChannels.value) window.setTimeout(() => void refreshAnalysisCounts(), 1200)
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
  let account = channelAccount('whatsapp')
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
  let account = channelAccount('gmail')
  gmailError.value = ''
  gmailMessage.value = ''
  try {
    if (!account || account.status === 'revoked') {
      const csrf = await inboxApi.getCsrf()
      const created = await channelsApi.createGmailAccount(csrf.csrf_token)
      // The create response already contains the account id. Relying on a full
      // workspace refetch here used to abort authorization whenever any
      // unrelated list request failed, even though the account existed.
      accounts.value = [
        ...accounts.value.filter((item) => item.id !== created.id && item.channel_type !== 'gmail'),
        created,
      ]
      account = created
    }
    if (!account) throw new Error('Gmail 账号初始化后不可见，请检查授权范围。')
    const csrf = await inboxApi.getCsrf()
    const result = await channelsApi.startGmailAuthorization(account.id, csrf.csrf_token)
    window.location.assign(result.authorization_url)
  } catch (cause) {
    gmailError.value = cause instanceof Error ? cause.message : 'Gmail 授权启动失败。'
  }
}

function readGmailCallbackState() {
  if (!canOperateChannels.value && !isAdmin.value) return
  const params = new URLSearchParams(window.location.search)
  const gmail = params.get('gmail')
  if (gmail === 'connected') gmailMessage.value = 'Gmail 授权完成。'
  if (gmail === 'error') gmailError.value = params.get('message') || 'Gmail 授权失败。'
  const outlook = params.get('outlook')
  if (outlook === 'connected') outlookAuthorizationMessage.value = 'Outlook 授权完成。'
  if (outlook === 'error') outlookAuthorizationError.value = params.get('message') || 'Outlook 授权失败。'
}

async function startOutlookAuthorization() {
  let account = channelAccount('outlook')
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
      const created = await channelsApi.createOutlookAccount(csrf.csrf_token)
      accounts.value = [
        ...accounts.value.filter((item) => item.id !== created.id && item.channel_type !== 'outlook'),
        created,
      ]
      account = created
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
    await refreshList()
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
  if (message.inquiry_id !== null && !isAdmin.value) {
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
      scheduleAnalysisRefresh()
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
    if (archiveOpen.value || processedBoxOpen.value) void loadArchive()
    scheduleAnalysisRefresh()
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
    // 独立详情页直接替换详情对象；列表页则本地替换，不整页刷新。
    if (inquiryDetail.value?.id === updated.id) {
      inquiryDetail.value = updated
    } else {
      const matchesFilter = !inquiryHandlingFilter.value || inquiryHandlingFilter.value === updated.handling_status
      inquiries.value = matchesFilter
        ? inquiries.value.map((item) => (item.id === updated.id ? updated : item))
        : inquiries.value.filter((item) => item.id !== updated.id)
      if (!inquiries.value.some((inquiry) => inquiry.id === selectedInquiryId.value)) {
        selectedInquiryId.value = inquiries.value[0]?.id ?? null
        selectedSalesUserId.value = null
      }
    }
    scheduleAnalysisRefresh()
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
    actionMessage.value = isAdmin.value ? '客户链路已改派。' : '客户链路已分配。'
    selectedSalesUserId.value = null
    selectedBusinessType.value = null
    if (route.value.page === 'inquiry' && route.value.id !== null) {
      await loadInquiryDetail(route.value.id, applyToken)
    } else {
      await refreshList('list')
    }
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
  initRouter((r, info) => { void applyRoute(r, info) })
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
    <header class="topbar">
      <div>
        <p class="eyebrow">{{ isStandalone ? '页面导航' : '运营工作台' }}</p>
        <h1>{{ isStandalone ? standaloneTitle : '消息与客户' }}</h1>
      </div>
      <div class="topbar-actions">
        <span v-if="currentUser" class="current-user">{{ currentUser.username }}（{{ currentUser.role }}）</span>
        <button class="link-button logout-link" type="button" @click="logoutSystemAccount">
          退出登录
        </button>
        <button v-if="isAdmin" class="secondary" type="button" @click="employeeAdminOpen = true; void loadEmployees()">员工管理</button>
        <button v-if="canOperateChannels || isAdmin" class="secondary" type="button" @click="profileOpen ? closeStandalonePage() : navigate({ page: 'settings' })">
          {{ profileOpen ? '返回工作台' : isAdmin ? '渠道接入（代连接）' : '我的 / 接入账号' }}
        </button>
        <button class="secondary" type="button" @click="refreshList('full')">刷新</button>
      </div>
    </header>
    <p v-if="logoutError" class="action-error">{{ logoutError }}</p>

    <section v-if="profileOpen && (canOperateChannels || isAdmin)" class="profile-view" data-ui="settings">
      <div class="profile-heading">
        <div>
          <p class="eyebrow">我的 / 账号管理</p>
          <h2>{{ isAdmin ? '渠道接入（管理员代连接）' : '个人渠道连接' }}</h2>
          <p class="profile-lede">{{ isAdmin ? '管理员可代为完成渠道创建、OAuth 授权与扫码配对，但看不到也不处理消息。连接完成后请到「员工管理 → 渠道账号与历史访问」把账号转交给运营。' : '管理当前登录用户本人的授权和连接状态。所有 provider 调用都经过后端，页面只展示非敏感状态。' }}</p>
        </div>
        <button class="link-button back-link" type="button" @click="closeStandalonePage">← 返回上一页</button>
      </div>

      <div class="settings-list">
        <section v-if="isAdmin" class="profile-operations admin-connect-note">
          <div>
            <h3>代连接后请转交给运营</h3>
            <p>这里只做接入，不展示消息栏。授权/配对完成后，去员工管理把该渠道账号转给在岗运营，运营刷新页面即可看到历史消息并继续处理。</p>
          </div>
          <button class="secondary" type="button" @click="openEmployeeAdminFromChannels">去转交账号</button>
        </section>
        <section v-else class="profile-operations">
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
            <p class="next-step">下一步：{{ isAdmin ? '连接完成后到「员工管理 → 渠道账号与历史访问」把账号转交给运营。' : channelAccount(channelType)?.status === 'verified_inbound' ? '继续在收件箱处理已授权范围内的消息。' : channelDetails[channelType].next }}</p>
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
                v-if="channelType === 'outlook' && !isAdmin && channelAccount(channelType)"
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
              :class="refetchTone(refetchChecks[channelAccount(channelType)?.id || 0])"
            >
              <strong>{{ refetchTitle(refetchChecks[channelAccount(channelType)?.id || 0]) }}</strong>
              <p>{{ refetchChecks[channelAccount(channelType)?.id || 0]?.recommended_action }}</p>
              <p v-if="refetchMeta(refetchChecks[channelAccount(channelType)?.id || 0])" class="refetch-meta">
                {{ refetchMeta(refetchChecks[channelAccount(channelType)?.id || 0]) }}
              </p>
              <p
                v-if="!refetchChecks[channelAccount(channelType)?.id || 0]?.ready && refetchChecks[channelAccount(channelType)?.id || 0]?.history_available"
                class="refetch-scope"
              >
                已入库的历史消息仍可正常查看与处理；此提示只影响实时回源校验，不影响询盘处理。
              </p>
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

    <section v-else-if="employeeAdminOpen && isAdmin" class="standalone-page employee-admin-page" role="region" aria-labelledby="employee-admin-title">
      <header class="ea-hero">
        <div class="ea-hero-text">
          <p class="eyebrow">管理员 · 访问控制</p>
          <h2 id="employee-admin-title">员工与授权</h2>
          <p class="ea-hero-lede">集中查看全部员工的岗位、部门与授权状态。新建账号后，员工首次登录必须先修改临时密码。</p>
        </div>
        <div class="ea-hero-actions">
          <button class="secondary" type="button" @click="loadEmployees">刷新列表</button>
          <button class="secondary" type="button" @click="employeeAdminOpen = false">关闭</button>
        </div>
      </header>

      <p v-if="employeeError" class="action-error ea-alert" role="alert">{{ employeeError }}</p>

      <div class="ea-stats" aria-label="员工统计">
        <div class="ea-stat"><span>员工总数</span><strong>{{ employeeStats.total }}</strong><small>含已停用账号</small></div>
        <div class="ea-stat"><span>有效账号</span><strong>{{ employeeStats.active }}</strong><small>当前可登录</small></div>
        <div class="ea-stat"><span>待首次改密</span><strong>{{ employeeStats.pendingPassword }}</strong><small>尚未完成激活</small></div>
        <div class="ea-stat"><span>已停用</span><strong>{{ employeeStats.inactive }}</strong><small>不可登录</small></div>
      </div>

      <section class="ea-card" aria-labelledby="ea-create-title">
        <header class="ea-card-head">
          <div><h3 id="ea-create-title">新建员工</h3><p>填写账号基本信息；创建成功后列表会自动刷新。</p></div>
          <span class="ea-step">01</span>
        </header>
        <form ref="employeeCreateFormEl" class="ea-form" novalidate @submit.prevent="createEmployee">
          <div v-if="employeeCreateFeedback" class="ea-feedback" :class="employeeCreateFeedback.kind" :role="employeeCreateFeedback.kind === 'error' ? 'alert' : 'status'" aria-live="polite">
            <span class="ea-feedback-icon" aria-hidden="true">{{ employeeCreateFeedback.kind === 'success' ? '✓' : '!' }}</span>
            <div class="ea-feedback-body">
              <strong>{{ employeeCreateFeedback.kind === 'success' ? '创建成功' : '暂时无法创建员工' }}</strong>
              <p>{{ employeeCreateFeedback.text }}</p>
            </div>
            <button v-if="employeeCreateFeedback.kind === 'success'" class="link-button ea-feedback-link" type="button" @click="scrollToEmployeeTable">查看员工 ↓</button>
            <button class="ea-feedback-close" type="button" aria-label="关闭提示" @click="employeeCreateFeedback = null">×</button>
          </div>
          <label class="ea-field">
            <span class="ea-label">员工姓名 <em>必填</em></span>
            <input v-model="employeeForm.full_name" name="full_name" required maxlength="64" autocomplete="off" placeholder="例如：张三" />
            <small class="ea-hint">显示在员工列表与询盘负责人处，便于识别真人</small>
          </label>
          <label class="ea-field">
            <span class="ea-label">用户名 <em>必填</em></span>
            <input v-model="employeeForm.username" name="username" required maxlength="64" autocomplete="off" placeholder="例如：zhang.san" />
            <small class="ea-hint">员工登录使用的唯一账号名</small>
          </label>
          <label class="ea-field">
            <span class="ea-label">岗位 <em>必填</em></span>
            <select v-model="employeeForm.role">
              <option v-for="option in employeeCreateRoleOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <small class="ea-hint">决定该员工可访问的业务范围</small>
          </label>
          <label class="ea-field ea-manager-overlay-field">
            <span class="ea-label">经理叠加权限</span>
            <span class="ea-inline-checkbox"><input v-model="employeeForm.manager_overlay_enabled" type="checkbox" /> 启用经理叠加权限</span>
            <small class="ea-hint">基础岗位的数据范围不变；具体操作仍需逐人授予。</small>
          </label>
          <label class="ea-field">
            <span class="ea-label">所属部门 <em>必填</em></span>
            <input v-model="employeeForm.department" name="department" list="ea-department-options" maxlength="64" required placeholder="例如：工程部" />
            <small class="ea-hint">所有岗位账号都必须关联所属部门。</small>
          </label>
          <label class="ea-field">
            <span class="ea-label">临时密码 <em>必填</em></span>
            <input v-model="employeeForm.temporary_password" name="temporary_password" required minlength="6" maxlength="15" type="password" autocomplete="new-password" placeholder="6–15 位" />
            <small class="ea-hint">请通过安全渠道单独告知员工</small>
          </label>
          <div class="ea-form-submit">
            <button class="primary" type="submit" :disabled="employeeCreating">{{ employeeCreating ? '创建中…' : '创建员工' }}</button>
            <span class="ea-hint">{{ employeeCreating ? '正在提交，请勿重复点击' : '创建后员工须在首次登录时改密' }}</span>
          </div>
        </form>
        <datalist id="ea-department-options"><option v-for="department in departmentSuggestions" :key="department" :value="department" /></datalist>
      </section>

      <section ref="employeeTableCardEl" class="ea-card ea-table-card" aria-labelledby="ea-table-title">
        <header class="ea-card-head">
          <div>
            <h3 id="ea-table-title">有效员工</h3>
            <p>有效员工 {{ activeEmployeeCount }} 人<span v-if="inactiveEmployees.length">，另有 {{ inactiveEmployees.length }} 个已停用账号归档在下方</span>（共 {{ employeeRecords.length }} 人）。<span v-if="employeeFilterActive">当前筛选命中 {{ activeEmployees.length }} 人。</span>点击「管理授权」展开该员工的详细设置。</p>
          </div>
          <span class="ea-step">02</span>
        </header>
        <div class="ea-toolbar">
          <label class="ea-field ea-search">
            <span class="ea-label">搜索员工</span>
            <input v-model="employeeSearch" type="search" placeholder="姓名、用户名或部门关键字" />
          </label>
          <label class="ea-field ea-toolbar-select">
            <span class="ea-label">岗位</span>
            <select v-model="employeeRoleFilter">
              <option value="all">全部岗位</option>
              <option v-for="option in employeeRoleOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
          </label>
          <label class="ea-field ea-toolbar-select">
            <span class="ea-label">状态</span>
            <select v-model="employeeStatusFilter">
              <option value="all">全部状态</option>
              <option value="active">有效</option>
              <option value="pending">待首次改密</option>
            </select>
          </label>
          <span class="ea-hint ea-toolbar-hint">已停用账号不在此表，统一在下方归档区</span>
          <button class="link-button ea-clear" type="button" @click="clearEmployeeFilters">清除筛选</button>
          <span class="ea-scroll-hint">← 左右滑动查看完整表格 →</span>
        </div>
        <div class="ea-table-wrap">
          <table class="ea-table">
            <thead>
              <tr>
                <th>员工</th><th>岗位</th><th>所属部门</th><th>账号状态</th><th>部门授权</th><th>渠道预授权</th><th>经理叠加</th><th class="ea-th-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="employee in activeEmployees" :key="employee.id">
                <tr :class="{ 'is-selected': expandedEmployeeId === employee.id }">
                  <td>
                    <div class="ea-person">
                      <span class="ea-avatar">{{ employee.username.slice(0, 1).toUpperCase() }}</span>
                      <span class="ea-person-name">
                      <strong>{{ employeeDisplayName(employee) }}</strong>
                      <small>{{ employee.username }} · 员工编号 #{{ employee.id }}</small>
                    </span>
                    </div>
                  </td>
                  <td><span class="ea-role">{{ employeeRoleLabel(employee.role) }}</span></td>
                  <td>{{ employee.department || '—' }}</td>
                  <td>
                    <div class="ea-pills">
                      <span class="ea-pill is-on">有效</span>
                      <span v-if="employee.must_change_password" class="ea-pill is-warn">待改密</span>
                    </div>
                  </td>
                  <td>
                    <div v-if="employee.department_grants.length" class="ea-chips"><span v-for="grant in employee.department_grants" :key="grant" class="ea-chip">{{ grant }}</span></div>
                    <span v-else class="ea-muted">无</span>
                  </td>
                  <td>
                    <div v-if="employee.channel_preauthorizations.length" class="ea-chips"><span v-for="grant in employee.channel_preauthorizations" :key="grant" class="ea-chip is-blue">{{ grant }}</span></div>
                    <span v-else class="ea-muted">无</span>
                  </td>
                  <td><span class="ea-pill" :class="employee.manager_overlay_enabled ? 'is-warn' : 'is-off'">{{ employee.manager_overlay_enabled ? `叠加 · ${employee.manager_grants.length} 项` : '未启用' }}</span></td>
                  <td class="ea-th-action">
                    <button class="secondary ea-manage" type="button" @click="toggleEmployeeDetail(employee.id)">{{ expandedEmployeeId === employee.id ? '收起' : '管理授权' }}</button>
                  </td>
                </tr>
                <tr v-if="expandedEmployeeId === employee.id && employee.is_active" class="ea-detail-row">
                  <td colspan="8">
                    <div class="ea-detail">
                      <header class="ea-detail-head">
                        <div>
                          <h4>{{ employeeDisplayName(employee) }} · 授权设置</h4>
                          <p class="ea-detail-account">
                            <span>登录账号 <code>{{ employee.username }}</code></span>
                            <span>员工编号 #{{ employee.id }}</span>
                            <span v-if="employee.full_name && employee.full_name !== employee.username">姓名 {{ employee.full_name }}</span>
                          </p>
                          <p>所有修改即时生效；「所属部门」是账号归属，「部门授权」是额外可访问的部门范围。</p>
                        </div>
                        <button class="link-button" type="button" @click="expandedEmployeeId = null">收起设置</button>
                      </header>
                      <p v-if="employeeError" class="action-error ea-alert" role="alert">{{ employeeError }}</p>
                      <div class="ea-detail-grid">
                        <section class="ea-detail-block">
                          <h5>基本信息</h5>
                          <div class="ea-detail-fields">
                            <label class="ea-field">
                              <span class="ea-label">员工姓名</span>
                              <input :value="employee.full_name || employee.username" maxlength="64" placeholder="例如：张三" @change="changeEmployeeFullName(employee, $event)" @keyup.enter="($event.target as HTMLInputElement).blur()" />
                              <small class="ea-hint">显示在员工列表；改完失焦即保存，可随时纠正错别字</small>
                            </label>
                            <label class="ea-field">
                              <span class="ea-label">岗位</span>
                              <select :value="employee.role" :disabled="!employee.is_active" @change="changeEmployeeRole(employee, $event)">
                                <option v-for="option in employeeRoleOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                                <option v-if="employee.role === 'manager'" value="operations">运营</option>
                              </select>
                            </label>
                            <label class="ea-field">
                              <span class="ea-label">所属部门</span>
                              <input :value="employee.department || ''" list="ea-department-options" required placeholder="例如：工程部" @change="changeEmployeeDepartment(employee, $event)" />
                            </label>
                          </div>
                          <p class="ea-block-note">所有岗位均须绑定部门；调岗或改部门会清除现有授权并使旧会话失效。</p>
                        </section>

                        <section class="ea-detail-block">
                          <h5>部门授权</h5>
                          <p class="ea-block-note">允许该员工访问<strong>其他部门</strong>的内部记录。填写已存在的部门名称，例如「工程部」；留空不会授予任何权限。</p>
                          <div v-if="employee.department_grants.length" class="ea-chips ea-chips-removable">
                            <button v-for="grant in employee.department_grants" :key="grant" class="ea-chip is-removable" type="button" :title="`撤销 ${grant} 授权`" @click="revokeEmployeeDepartment(employee.id, grant)">{{ grant }} <span aria-hidden="true">×</span></button>
                          </div>
                          <p v-else class="ea-muted">当前没有额外部门授权。</p>
                          <div class="ea-inline-form">
                            <label class="ea-field">
                              <span class="ea-label">新增部门授权</span>
                              <input :value="employeeGrantDepartmentById[employee.id] || ''" list="ea-department-options" placeholder="输入或选择部门名称，例如：工程部" @input="setEmployeeGrantDepartment(employee.id, $event)" @keyup.enter.prevent="grantEmployeeDepartment(employee.id)" />
                              <small class="ea-hint">可从下拉中选择已有部门，也可输入新部门名称</small>
                            </label>
                            <button class="secondary" type="button" :disabled="!(employeeGrantDepartmentById[employee.id] || '').trim()" @click="grantEmployeeDepartment(employee.id)">授予部门</button>
                          </div>
                          <label class="ea-field ea-manager-overlay-toggle">
                            <span class="ea-inline-checkbox"><input type="checkbox" :checked="employee.manager_overlay_enabled" :disabled="!employee.is_active" @change="changeEmployeeManagerOverlay(employee, $event)" /> 启用经理叠加权限</span>
                            <small class="ea-hint">权限不会仅因岗位名称自动获得；下方按目标员工逐项授予。</small>
                          </label>
                          <div v-if="employee.manager_overlay_enabled" class="ea-manager-grants">
                            <h5>经理逐人授权</h5>
                            <p class="ea-block-note">仅对同部门员工授予下列明确操作；基础岗位的原有数据范围不变。</p>
                            <div v-if="employee.manager_grants.length" class="ea-chips ea-chips-removable">
                              <button v-for="grant in employee.manager_grants" :key="`${grant.target_user_id}:${grant.permission}`" class="ea-chip is-removable" type="button" :title="`撤销员工 #${grant.target_user_id} 的 ${grant.permission} 授权`" @click="revokeManagerPermission(employee, grant)">#{{ grant.target_user_id }} · {{ managerPermissionOptions.find((item) => item.value === grant.permission)?.label || grant.permission }} <span aria-hidden="true">×</span></button>
                            </div>
                            <p v-else class="ea-muted">尚无逐人授权。</p>
                            <div class="ea-inline-form">
                              <label class="ea-field">
                                <span class="ea-label">目标员工</span>
                                <select v-model="employeeManagerTargetById[employee.id]">
                                  <option value="">请选择同部门员工</option>
                                  <option v-for="target in managerEligibleTargets(employee)" :key="target.id" :value="target.id">{{ employeeDisplayName(target) }}（#{{ target.id }}）</option>
                                </select>
                              </label>
                              <label class="ea-field">
                                <span class="ea-label">允许操作</span>
                                <select v-model="employeeManagerPermissionById[employee.id]">
                                  <option value="">请选择明确权限</option>
                                  <option v-for="permission in managerPermissionOptions" :key="permission.value" :value="permission.value">{{ permission.label }}</option>
                                </select>
                              </label>
                              <button class="secondary" type="button" :disabled="!employeeManagerTargetById[employee.id] || !employeeManagerPermissionById[employee.id]" @click="grantManagerPermission(employee)">授予</button>
                            </div>
                          </div>
                        </section>

                        <section v-if="isOperatingRole(employee.role)" class="ea-detail-block">
                          <h5>渠道预授权</h5>
                          <p class="ea-block-note">控制该员工能否<strong>新建</strong>对应类型的渠道账号。已接入的账号和历史消息不受影响。</p>
                          <p class="ea-block-note">若该员工提示「历史访问已撤销，需管理员重新授权」，请到下方<strong>渠道账号与历史访问</strong>恢复；这里的预授权无法解除该标记。</p>
                          <p v-if="employeeChannelFeedback" class="ea-channel-feedback" :class="employeeChannelFeedback.kind" :role="employeeChannelFeedback.kind === 'error' ? 'alert' : 'status'" aria-live="polite">{{ employeeChannelFeedback.text }}</p>
                          <div class="ea-channel-toggles">
                            <div v-for="channel in employeeChannelOptions" :key="channel.key" class="ea-toggle" :class="{ 'is-granted': employee.channel_preauthorizations.includes(channel.key) }">
                              <span class="ea-toggle-dot" aria-hidden="true"></span>
                              <span class="ea-toggle-text"><strong>{{ channel.label }}</strong><small>{{ channel.hint }}</small></span>
                              <span class="ea-toggle-state">{{ employee.channel_preauthorizations.includes(channel.key) ? '已授权' : '未授权' }}</span>
                              <button v-if="employee.channel_preauthorizations.includes(channel.key)" class="ea-channel-action ea-channel-revoke" type="button" :disabled="employeeChannelPending !== null" @click="changeEmployeeChannel(employee, channel.key, false)">{{ employeeChannelPending === `${employee.id}:${channel.key}` ? '处理中…' : '撤销' }}</button>
                              <button v-else class="ea-channel-action" type="button" :disabled="employeeChannelPending !== null" @click="changeEmployeeChannel(employee, channel.key, true)">{{ employeeChannelPending === `${employee.id}:${channel.key}` ? '处理中…' : '授权' }}</button>
                            </div>
                          </div>
                        </section>

                        <section class="ea-detail-block">
                          <h5>账号操作</h5>
                          <p class="ea-block-note">重置密码后，员工下次登录必须修改新密码；停用会立即使该账号无法登录并清除授权。</p>
                          <div class="ea-inline-form">
                            <label class="ea-field">
                              <span class="ea-label">新临时密码</span>
                              <input :value="employeeResetPasswordById[employee.id] || ''" type="password" autocomplete="new-password" minlength="6" maxlength="15" placeholder="6–15 位" @input="setEmployeeResetPassword(employee.id, $event)" @keyup.enter="resetEmployee(employee)" />
                            </label>
                            <button class="secondary" type="button" :disabled="!employee.is_active || employeeResetPendingId === employee.id" @click="resetEmployee(employee)">
                              {{ employeeResetPendingId === employee.id ? '重置中…' : '重置密码' }}
                            </button>
                          </div>
                          <p
                            v-if="employeeResetFeedback && employeeResetFeedback.userId === employee.id"
                            class="ea-inline-feedback"
                            :class="employeeResetFeedback.kind"
                            :role="employeeResetFeedback.kind === 'error' ? 'alert' : 'status'"
                            aria-live="polite"
                          >
                            <span class="ea-inline-feedback-icon" aria-hidden="true">{{ employeeResetFeedback.kind === 'success' ? '✓' : '!' }}</span>
                            <span>{{ employeeResetFeedback.text }}</span>
                          </p>
                          <div class="ea-danger-row">
                            <template v-if="employeeConfirmDeactivateId === employee.id">
                              <span class="ea-confirm-text">确认停用 {{ employeeDisplayName(employee) }}（{{ employee.username }}）？</span>
                              <button class="ea-danger" type="button" @click="deactivateEmployee(employee)">确认停用</button>
                              <button class="link-button" type="button" @click="employeeConfirmDeactivateId = null">取消</button>
                            </template>
                            <button v-else class="link-button ea-danger-link" type="button" :disabled="!employee.is_active" @click="deactivateEmployee(employee)">停用该账号</button>
                          </div>
                        </section>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
              <tr v-if="activeEmployees.length === 0">
                <td colspan="8" class="ea-empty">
                  {{ employeeFilterActive ? '当前筛选下没有符合条件的有效员工。可以清除筛选，或在上方新建员工。' : '还没有有效员工。可以在上方新建员工。' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- 停用账号归档：停用后不能登录、也不能再改岗位/部门/授权，所以不再混在有效员工表里。 -->
      <section v-if="inactiveEmployees.length" class="ea-card ea-archive-card" aria-labelledby="ea-inactive-title">
        <header class="ea-card-head">
          <div>
            <h3 id="ea-inactive-title">已停用的员工（{{ inactiveEmployees.length }}）</h3>
            <p>归档区与上方筛选无关，始终列出全部停用账号。停用会清除权限授权并撤销旧会话；重新启用后账号仍需管理员重新授予授权，历史消息与渠道记录不会丢失。</p>
          </div>
          <span class="ea-archive-count">归档</span>
        </header>
        <div class="ea-table-wrap">
          <table class="ea-table ea-archive-table">
            <thead>
              <tr>
                <th>员工</th><th>岗位</th><th>所属部门</th><th>停用时已清除的授权</th><th class="ea-th-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="employee in inactiveEmployees" :key="employee.id" class="is-inactive">
                <td>
                  <div class="ea-person">
                    <span class="ea-avatar is-off">{{ employee.username.slice(0, 1).toUpperCase() }}</span>
                    <span class="ea-person-name">
                      <strong>{{ employeeDisplayName(employee) }}</strong>
                      <small><span class="ea-pill is-off">已停用</span> {{ employee.username }} · 员工编号 #{{ employee.id }}</small>
                    </span>
                  </div>
                </td>
                <td><span class="ea-role">{{ employeeRoleLabel(employee.role) }}</span></td>
                <td>{{ employee.department || '—' }}</td>
                <td>
                  <span class="ea-muted">停用时已撤销；启用后需重新授权</span>
                </td>
                <td class="ea-th-action">
                  <div class="ea-row-actions">
                    <template v-if="employeeConfirmReactivateId === employee.id">
                      <span class="ea-confirm-text">确认启用 {{ employeeDisplayName(employee) }}（{{ employee.username }}）？启用后即可重新配置授权。</span>
                      <button class="primary ea-manage" type="button" @click="reactivateEmployee(employee)">确认启用</button>
                      <button class="link-button" type="button" @click="employeeConfirmReactivateId = null">取消</button>
                    </template>
                    <button v-else class="secondary ea-manage" type="button" @click="reactivateEmployee(employee)">启用账号</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="ea-card" aria-labelledby="ea-channel-accounts-title">
        <header class="ea-card-head">
          <div>
            <h3 id="ea-channel-accounts-title">渠道账号与历史访问</h3>
            <p>挂在管理员名下的渠道账号，运营看不到也处理不了消息。默认已勾选管理员名下账号，选好接收员工后一键转交，历史消息会随账号一起迁移。转移时会自动清理运营名下未连接/已撤销的旧空壳账号；已撤销但有历史数据的账号需先「恢复历史访问」。</p>
          </div>
          <span class="ea-step">03</span>
        </header>
        <div v-if="adminChannelFeedback" class="ea-feedback ea-feedback-block" :class="adminChannelFeedback.kind" :role="adminChannelFeedback.kind === 'error' ? 'alert' : 'status'" aria-live="polite">
          <span class="ea-feedback-icon" aria-hidden="true">{{ adminChannelFeedback.kind === 'success' ? '✓' : '!' }}</span>
          <div class="ea-feedback-body">
            <strong>{{ adminChannelFeedback.title }}</strong>
            <p>{{ adminChannelFeedback.text }}</p>
          </div>
          <button class="ea-feedback-close" type="button" aria-label="关闭提示" @click="adminChannelFeedback = null">×</button>
        </div>
        <div class="ea-transfer-bar">
          <label class="ea-transfer-field">
            <span class="ea-label">接收员工</span>
            <select v-model.number="transferTargetUserId" :disabled="channelTransferSubmitting">
              <option value="" disabled>请选择运营员工</option>
              <option v-for="employee in transferableEmployees" :key="employee.id" :value="employee.id">{{ employee.username }} · #{{ employee.id }} · {{ employeeRoleLabel(employee.role) }}</option>
            </select>
          </label>
          <div class="ea-transfer-copy">
            <strong>把渠道账号交给运营</strong>
            <p>只列出在岗的运营岗位员工。转移会同步重建渠道授权、保留全部历史消息，并自动补齐对应渠道的预授权；管理员不再持有该渠道，避免两个账号处理同一批消息。</p>
          </div>
          <button class="primary ea-transfer-submit" type="button" :disabled="channelTransferSubmitting || !transferTargetUserId || selectedAdminChannelAccountIds.length === 0" @click="transferChannelAccountsOwner(selectedAdminChannelAccountIds)">
            {{ channelTransferSubmitting ? '转移中…' : `把选中的 ${selectedAdminChannelAccountIds.length} 个账号转给该员工` }}
          </button>
        </div>
        <p v-if="transferableEmployees.length === 0" class="ea-transfer-empty">当前没有在岗的运营岗位员工。请先在上方新建员工或把岗位调整为「运营」，再来转移渠道账号。</p>
        <div class="ea-toolbar">
          <button class="secondary" type="button" :disabled="adminChannelAccountsLoading" @click="loadAdminChannelAccounts">{{ adminChannelAccountsLoading ? '加载中…' : '刷新账号列表' }}</button>
          <span class="ea-hint">共 {{ adminChannelAccounts.length }} 个渠道账号 · {{ adminOwnedAccountCount }} 个仍归属管理员 · 已选 {{ selectedAdminChannelAccountIds.length }} 个 · {{ adminChannelAccounts.filter((item) => item.history_access_revoked).length }} 个待恢复</span>
          <span class="ea-scroll-hint">表格可左右滑动，查看外部映射、连接状态与操作按钮 →</span>
        </div>
        <div class="ea-table-wrap">
          <table class="ea-table ea-channel-accounts-table">
            <thead>
              <tr>
                <th class="ea-th-check"><input type="checkbox" :checked="allAdminChannelAccountsSelected" :disabled="adminChannelAccounts.length === 0" aria-label="全选渠道账号" @change="onToggleAllAdminChannelAccounts"></th>
                <th>账号</th><th>渠道类型</th><th>归属员工</th><th>外部账号映射</th><th>连接状态</th><th>历史访问</th><th class="ea-th-action">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="account in adminChannelAccounts" :key="account.id" :class="{ 'is-revoked': account.history_access_revoked, 'ea-row-checked': selectedAdminChannelAccountIds.includes(account.id) }">
                <td class="ea-th-check"><input type="checkbox" :checked="selectedAdminChannelAccountIds.includes(account.id)" :aria-label="`选择渠道账号 #${account.id}`" @change="onToggleAdminChannelAccount($event, account.id)"></td>
                <td><strong>#{{ account.id }}</strong></td>
                <td><span class="ea-role">{{ account.channel_type }}</span></td>
                <td>
                  <div class="ea-owner">
                    <span>{{ adminChannelOwner(account.owner_user_id) }}</span>
                    <span v-if="adminChannelOwnerIsAdmin(account.owner_user_id)" class="ea-pill is-warn">管理员名下</span>
                  </div>
                </td>
                <td>{{ account.external_account_id || '—' }}</td>
                <td><span class="ea-pill" :class="account.status === 'connected' ? 'is-on' : ''">{{ adminChannelStatusLabels[account.status] || account.status }}</span></td>
                <td>
                  <span v-if="account.history_access_revoked" class="ea-pill is-warn">已撤销</span>
                  <span v-else class="ea-pill is-on">正常</span>
                </td>
                <td class="ea-th-action">
                  <div class="ea-row-actions">
                    <button v-if="account.history_access_revoked" class="primary ea-regrant" type="button" :disabled="regrantingAccountId !== null" @click="regrantChannelHistory(account)">{{ regrantingAccountId === account.id ? '恢复中…' : '恢复历史访问' }}</button>
                    <button class="secondary ea-transfer-one" type="button" :disabled="channelTransferSubmitting || !transferTargetUserId || accountOwnedByTransferTarget(account.owner_user_id)" :title="!transferTargetUserId ? '请先在上方选择接收员工' : '把此账号转给所选运营'" @click="transferChannelAccountsOwner([account.id])">单独转移</button>
                  </div>
                </td>
              </tr>
              <tr v-if="!adminChannelAccountsLoading && adminChannelAccounts.length === 0">
                <td colspan="8" class="ea-empty">暂无渠道账号。运营首次点击「开始授权」后会自动创建。</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="ea-card-foot">转移只改变归属与授权关系，不会删除历史消息，也不会代替运营完成 OAuth 授权；恢复只解除本地的撤销标记并把账号置回「待授权」。</p>
      </section>
    </section>
    <section v-else-if="operationLogOpen" class="standalone-page operation-log-page" role="region" aria-labelledby="operation-log-title">
      <nav class="page-breadcrumb">
        <button class="link-button" type="button" @click="closeStandalonePage">← 返回上一页</button>
        <span>{{ standaloneTitle }}</span>
      </nav>
      <div class="operation-log-dialog">
        <header>
          <div><p class="eyebrow">操作回溯</p><h2 id="operation-log-title">{{ standaloneTitle }}</h2></div>
          <button class="secondary" type="button" @click="closeStandalonePage">关闭</button>
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
      </div>
    </section>

    <section v-else-if="groupBindingOpen" class="standalone-page gb-page" role="region" aria-labelledby="gb-title">
      <nav class="page-breadcrumb">
        <button class="link-button" type="button" @click="closeStandalonePage">← 返回上一页</button>
        <span>{{ standaloneTitle }}</span>
      </nav>
      <div class="gb-dialog">
        <header class="gb-heading">
          <div>
            <p class="eyebrow">WhatsApp 群聊 · 客户归属</p>
            <h2 id="gb-title">确认群聊客户归属</h2>
            <p class="gb-jid">群 JID：<code>{{ activeGroupJid || '未提供' }}</code></p>
          </div>
          <button class="secondary" type="button" @click="closeStandalonePage">关闭</button>
        </header>
        <p class="gb-notice">
          此绑定<strong>完全由运营人员人工确认</strong>。系统不会根据群名、群成员或消息内容推断客户，也不会从通讯录添加好友。
          绑定不会改写历史消息、不会自动创建或合并询盘链路。一个群只对应一个客户。
        </p>
        <div class="gb-content" aria-live="polite">
          <p v-if="!activeGroupJid" class="action-error">{{ groupBindingError || '缺少群 JID，请从群聊分组卡片进入此页面。' }}</p>
          <p v-else-if="groupBindingLoading" class="empty">正在加载归属信息与可用客户手机号…</p>
          <template v-else>
            <section class="gb-section gb-current">
              <h3>当前绑定</h3>
              <template v-if="activeGroupBinding">
                <p class="gb-current-phone">{{ activeGroupBinding.normalized_phone }}</p>
                <p class="muted">绑定人：{{ activeGroupBinding.bound_by || '未知' }} · 时间：{{ formatTime(activeGroupBinding.updated_at) }}<span v-if="activeGroupBinding.note"> · 备注：{{ activeGroupBinding.note }}</span></p>
                <button class="secondary gb-danger" type="button" :disabled="groupBindingSubmitting" @click="removeGroupBinding">解除绑定</button>
              </template>
              <p v-else class="muted">尚未绑定客户。请从下方选择或输入客户手机号。</p>
            </section>
            <section class="gb-section">
              <h3>方式一 · 从当前消息渠道已获取的客户中选择</h3>
              <p class="muted">以下手机号来自你有权访问的 WhatsApp 消息，只是供人工挑选的列表，不代表系统判断该群属于此客户。</p>
              <p v-if="groupBindingError" class="action-error">{{ groupBindingError }}</p>
              <p v-else-if="groupBindingCandidates.length === 0" class="empty">当前授权范围内没有可用的客户手机号，请使用方式二手动输入。</p>
              <div v-else class="gb-candidate-list">
                <button v-for="candidate in groupBindingCandidates" :key="candidate.normalized_phone" class="gb-candidate" :class="{ 'is-selected': groupBindingSelectedPhone === candidate.normalized_phone }" type="button" :aria-pressed="groupBindingSelectedPhone === candidate.normalized_phone" @click="selectGroupBindingCandidate(candidate.normalized_phone)">
                  <strong>{{ candidate.normalized_phone }}</strong>
                  <span>{{ candidate.customer_nickname || '未提供昵称' }}<span v-if="candidate.customer_contact && candidate.customer_contact !== candidate.normalized_phone"> · {{ candidate.customer_contact }}</span></span>
                  <small>最近出现 {{ formatTime(candidate.last_seen_at) }} · 共 {{ candidate.message_count }} 条消息</small>
                </button>
              </div>
            </section>
            <section class="gb-section">
              <h3>方式二 · 直接输入带地区码的手机号</h3>
              <label class="gb-label" for="gb-phone">客户手机号（例如 +8613800138000）</label>
              <input id="gb-phone" v-model="groupBindingPhoneInput" class="gb-input" type="tel" inputmode="tel" autocomplete="off" placeholder="+8613800138000" maxlength="32" @input="onGroupBindingPhoneInput" />
              <p class="muted">手动输入优先于上方候选选择；提交前请核对地区码。后端会按 E.164 校验。</p>
              <label class="gb-label" for="gb-note">备注（可选）</label>
              <input id="gb-note" v-model="groupBindingNote" class="gb-input" type="text" maxlength="255" placeholder="例如：该群为某公司采购对接群" />
            </section>
            <p v-if="groupBindingFeedback" class="gb-feedback" :class="`is-${groupBindingFeedback.kind}`" role="status">{{ groupBindingFeedback.text }}</p>
            <div class="gb-actions">
              <button class="primary" type="button" :disabled="groupBindingSubmitting || !bindingPhone || !activeGroupJid" @click="submitGroupBinding">
                {{ groupBindingSubmitting ? '正在提交…' : activeGroupBinding ? '确认改绑' : '确认绑定' }}
              </button>
              <button class="secondary" type="button" @click="closeStandalonePage">返回，不修改</button>
            </div>
          </template>
        </div>
      </div>
    </section>

    <template v-else>
      <section v-if="loading" class="notice">正在加载授权范围内的数据…</section>
      <section v-else-if="unauthorized" class="notice error">
      {{ unauthorizedStatus === 401 ? '当前会话已失效，请重新登录。' : '当前账号无权访问该运营收件箱。' }}
    </section>
    <section v-else-if="error" class="notice error">
      {{ error }}
      <button class="link-button" type="button" @click="refreshList('full')">重试</button>
    </section>
    <section v-else class="content-grid" :class="{ 'has-selected-inquiry': isInquiryView && selectedInquiry, 'is-standalone': isStandalone }" data-ui="inbox">
      <nav v-if="isStandalone" class="page-breadcrumb page-breadcrumb-full">
        <button class="link-button" type="button" @click="closeStandalonePage">← 返回上一页</button>
        <span>{{ standaloneTitle }}</span>
      </nav>
      <template v-if="!isStandalone">
      <nav class="workspace-tabs" aria-label="工作台视图">
        <button v-if="isAdmin" type="button" class="active" aria-current="page" @click="switchWorkspaceView('customers')">全公司询盘</button>
        <template v-else-if="canOperateChannels">
          <button type="button" :class="{ active: workspaceView === 'messages' }" @click="switchWorkspaceView('messages')">消息收件箱</button>
          <button type="button" :class="{ active: workspaceView === 'review' }" @click="switchWorkspaceView('review')">待分配</button>
          <button type="button" :class="{ active: workspaceView === 'customers' }" @click="switchWorkspaceView('customers')">客户链路</button>
          <button type="button" :class="{ active: workspaceView === 'customerMessages' }" @click="switchWorkspaceView('customerMessages')">客户消息</button>
        </template>
        <template v-else>
          <button type="button" :class="{ active: workspaceView === 'customers' }" @click="switchWorkspaceView('customers')">{{ currentUser?.role === 'sales' ? '我负责的客户' : '部门范围' }}</button>
        </template>
      </nav>
      <section class="inbox-panel panel" :class="{ 'is-refreshing': filterLoading, 'inquiry-sidebar': isInquiryView && selectedInquiry }">
        <div v-if="isInquiryView" class="panel-heading">
          <div>
            <p class="eyebrow">{{ isAdmin ? '全公司审阅' : currentUser?.role === 'sales' ? '业务员工作台' : '运营收件箱' }}</p>
            <h2>{{ isAdmin ? '全公司询盘与处理历史' : workspaceView === 'review' ? '待分配客户' : currentUser?.role === 'sales' ? '转交给我的客户' : '已分配客户链路' }}</h2>
            <p v-if="isAdmin">只读查看全公司询盘与关联历史，并可明确改派负责人。消息明细与处理由运营账号独占，避免两个账号同时处理同一渠道消息。</p>
            <p v-else-if="currentUser?.role === 'sales'">运营转交给你的客户链路都在这里。可查看联系人、联系方式、原始内容与来源渠道；负责人由运营改派，业务员不能改派或删除链路。</p>
            <p v-else-if="!canOperateChannels">当前岗位不参与客户链路处理，这里不展示询盘或客户消息。</p>
            <p v-else-if="workspaceView === 'review'">按已确认的邮箱或手机号汇总客户，选择业务类型与负责人完成分配。</p>
          </div>
          <span class="count">{{ selectedInquiry ? `第 ${inquiryPage} / ${inquiryTotalPages} 页` : `共 ${inquiryTotalCount} 条 · 第 ${inquiryPage} / ${inquiryTotalPages} 页` }}</span>
        </div>

        <div v-if="isInquiryView && !isAdmin" class="inbox-filters">
          <div class="filter-group">
            <span>处理状态</span>
            <select v-model="inquiryHandlingFilter" aria-label="询盘人工状态" @change="onInquiryFilterChange">
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
              <p class="eyebrow">批量 / 逐条处理</p>
              <h2>{{ workspaceView === 'customerMessages' ? '已分配客户的消息' : '全部消息' }}</h2>
            </div>
            <span class="count">{{ messages.length }} 条</span>
          </div>
          <div class="message-tools">
            <section class="message-tool-group message-filter-set" aria-labelledby="message-filter-heading">
              <h3 id="message-filter-heading">筛选条件</h3>
              <div class="inbox-filters">
                <div v-if="workspaceView === 'messages'" class="filter-group">
                  <span>客户归属</span>
                  <select v-model="messageAssignmentFilter" aria-label="客户归属筛选" @change="onMessageFilterChange">
                    <option value="all">全部消息</option><option value="assigned">已归属客户</option><option value="unassigned">未归属客户</option>
                  </select>
                </div>
                <div class="filter-group">
                  <span>渠道</span>
                  <select v-model="messageChannelAccountFilter" aria-label="消息渠道" @change="onMessageFilterChange">
                    <option value="">全部渠道</option>
                    <option value="website_form">官网表单</option>
                    <option v-for="account in messageChannelAccounts" :key="account.id" :value="String(account.id)">
                      {{ channelLabel(account.channel_type) }}
                    </option>
                  </select>
                </div>
                <div class="filter-group">
                  <span>入站状态</span>
                  <select v-model="messageIngestionFilter" aria-label="消息入站状态" @change="onMessageFilterChange">
                    <option value="">全部入站</option><option value="received">已接收</option><option value="processed">已处理入站</option><option value="failed">入站失败</option>
                  </select>
                </div>
                <div class="filter-group">
                  <span>处理状态</span>
                  <select v-model="messageHandlingFilter" aria-label="消息人工处理状态" @change="onMessageFilterChange">
                    <option value="all">全部状态</option><option value="pending">待处理</option><option value="processed">已处理</option><option value="ignored">已忽略</option>
                  </select>
                </div>
              </div>
            </section>
            <section v-if="canOperateChannels" class="message-tool-group message-box-set" aria-labelledby="message-box-heading">
              <h3 id="message-box-heading">消息箱</h3>
              <div class="archive-toolbar">
            <button class="secondary" :class="{ 'is-active': processedBoxOpen }" type="button" :aria-expanded="processedBoxOpen" @click="toggleBox('processed')">
              {{ processedBoxOpen ? '收起已处理箱' : '已处理箱' }}
            </button>
            <button class="secondary" :class="{ 'is-active': archiveOpen }" type="button" :aria-expanded="archiveOpen" @click="toggleBox('ignored')">
              {{ archiveOpen ? '收起归档箱' : '归档箱' }}
            </button>
              </div>
            </section>
          </div>
          <div v-if="canBulkHandle" class="bulk-action-bar">
            <label class="bulk-select-all">
              <input
                type="checkbox"
                :checked="allVisibleSelected"
                :disabled="selectableMessageIds.length === 0 || bulkActionRunning"
                @change="toggleSelectAllVisible"
              />
              <span>全选本页 {{ selectableMessageIds.length }} 条</span>
            </label>
            <span class="bulk-selection-count">已选 {{ selectedMessageCount }} 条</span>
            <div class="bulk-action-buttons">
              <button class="action-button action-primary" type="button" :disabled="bulkActionRunning || selectedMessageCount === 0" @click="runBulkMessageAction('processed')">
                {{ bulkActionRunning ? '处理中…' : '批量标记已处理' }}
              </button>
              <button class="action-button action-secondary" type="button" :disabled="bulkActionRunning || selectedMessageCount === 0" @click="runBulkMessageAction('ignored')">批量忽略</button>
              <button v-if="selectedMessageCount > 0" class="link-button" type="button" @click="clearMessageSelection">取消选择</button>
            </div>
            <p v-if="bulkActionNotice" class="bulk-feedback success" role="status">{{ bulkActionNotice }}</p>
            <p v-if="bulkActionError" class="bulk-feedback error" role="alert">{{ bulkActionError }}</p>
          </div>
          <p v-if="providerFallback" class="inline-feedback success">
            <a :href="providerFallback.url" target="_blank" rel="noopener noreferrer">{{ providerFallback.label }}</a>
          </p>
          <p v-if="actionError" class="inline-feedback error" role="alert">{{ actionError }}</p>
          <section v-if="processedBoxOpen" id="processed-message-box" class="archive-box">
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
          <section v-if="archiveOpen" id="ignored-message-box" class="archive-box">
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
            <div v-if="group.messages.length > 1 || group.scope === 'group'" class="message-group-bar">
              <span class="group-label">
                {{ messageGroupLabel(group) }} · {{ group.contactLabel }}
                <span v-if="group.scope === 'group' && groupBindingFor(group)" class="gb-group-tag is-bound">已归属 {{ groupBindingFor(group)?.normalized_phone }}</span>
                <span v-else-if="group.scope === 'group'" class="gb-group-tag is-unbound">未确认客户归属</span>
              </span>
              <button v-if="group.scope === 'group' && canOperateChannels && currentUser?.role !== 'sales'" class="action-button action-secondary gb-group-entry" type="button" @click="openGroupBinding(group)">
                {{ groupBindingFor(group) ? '修改客户归属' : '确认群聊客户归属' }}
              </button>
              <label v-if="groupSelectableIds(group).length > 0" class="group-select-control">
                <input type="checkbox" :checked="isGroupFullySelected(group)" :disabled="bulkActionRunning" @change="toggleSelectGroup(group)" />
                <span>全选本组 {{ groupSelectableIds(group).length }} 条</span>
              </label>
              <div v-if="groupSelectableIds(group).length > 1" class="group-bulk-actions">
                <button class="action-button action-primary group-bulk-button" type="button" :disabled="bulkActionRunning" @click="runBulkMessageAction('processed', groupSelectableIds(group))">整组已处理</button>
                <button class="action-button action-secondary group-bulk-button" type="button" :disabled="bulkActionRunning" @click="runBulkMessageAction('ignored', groupSelectableIds(group))">整组忽略</button>
              </div>
              <button v-if="group.messages.length > 1" class="link-button" type="button" @click="toggleMessageGroup(group.key)">
                {{ collapsedGroupKeys.has(group.key) ? `展开组内其他 ${group.messages.length - 1} 条` : '收起组内消息' }}
              </button>
            </div>
            <div v-for="message in messagesForGroup(group)" :id="`message-${message.id}`" :key="message.id" class="message-row" :class="{ 'is-grouped': group.messages.length > 1, 'is-focused-message': selectedMessageId === message.id }">
            <div class="message-meta">
              <label v-if="canBulkSelect(message)" class="message-select-control">
                <input
                  type="checkbox"
                  :checked="isMessageSelected(message.id)"
                  :disabled="bulkActionRunning"
                  :aria-label="`选择消息 #${message.id}`"
                  @change="toggleMessageSelection(message.id)"
                />
                <span>选择</span>
              </label>
              <span class="channel-mark" :class="`channel-${message.channel_type}`">{{ message.channel_type === 'website_form' ? 'WF' : message.channel_type === 'whatsapp' ? 'WS' : message.channel_type === 'outlook' ? 'OL' : 'GM' }}</span>
              <strong>{{ messageContactLabel(message) }}</strong>
              <span v-if="messageSenderLabel(message)" class="sender">发送人：{{ messageSenderLabel(message) }}</span>
              <span class="meta-time">{{ formatTime(message.occurred_at) }}</span>
              <span v-if="group.messages.length > 1" class="state-label group-badge" :title="`属于「${messageGroupLabel(group)}」`">{{ groupBadgeLabel(group, message) }}</span>
              <span class="state-label ingestion-state">入站：{{ ingestionStatusLabel(message.ingestion_status) }}</span>
              <span class="state-label" :class="message.content_state === 'revoked' ? 'is-revoked' : ''">人工：{{ messageStatusLabel(message) }}</span>
              <span class="state-label" :class="message.link_state === 'manual_review' || message.contact_identity_state !== 'certain' ? 'status-warning' : ''">身份：{{ contactIdentityLabel(message.contact_identity_state) }}</span>
              <span class="state-label" :class="message.link_state === 'manual_review' ? 'status-warning' : ''">归链：{{ linkStateLabel(message.link_state) }}</span>
              <span v-if="message.content_state !== 'revoked' && message.overview?.status === 'pending'" class="state-label">中文概要：生成中</span>
              <span v-else-if="message.content_state !== 'revoked' && message.overview?.status === 'failed'" class="status-warning">中文概要：待生成</span>
              <span v-if="accountStatus(message.channel_account_id) === 'blocked'" class="status-warning">渠道阻塞</span><span v-if="accountStatus(message.channel_account_id) === 'revoked'" class="status-warning">渠道已撤销</span>
            </div>
            <template v-if="!expandedMessageIds.has(message.id)">
              <div class="message-brief">
                <!-- 主内容始终是清洗后的安全原文；中文概述只在下方一行小字补充。 -->
                <p class="message-preview">{{ message.display_excerpt || '（无正文）' }}</p>
                <small v-if="message.content_state !== 'revoked' && message.overview?.status === 'ready' && message.overview.text" class="message-overview-inline">中文概述：{{ message.overview.text }}</small>
                <small v-else-if="message.content_state !== 'revoked' && message.overview?.status === 'pending'" class="message-overview-inline">中文概述生成中…</small>
                <small v-else-if="message.content_state !== 'revoked' && message.overview?.status === 'failed'" class="message-overview-inline">中文概述生成失败，可在下方重新生成。</small>
              </div>
            </template>
            <div v-else class="message-content-view">
              <template v-if="messageContentFor(message.id)">
                <!-- The label sits outside the clamped paragraph: inside it, the
                     block-level label consumed one of the 8 clamped lines and
                     clipped the last visible line in half. -->
                <span class="content-label">{{ isMessageExpanded(message.id) ? '完整原文' : '安全原文预览' }}</span>
                <!-- Expanded and collapsed are mutually exclusive: rendering the
                     clamped preview next to the full text showed the body twice. -->
                <p v-if="isMessageExpanded(message.id)" class="message-full-content">
                  {{ messageContentFor(message.id)?.full_text || '（无正文）' }}
                </p>
                <p v-else class="message-original-preview">
                  {{ messageContentFor(message.id)?.preview_text || '（无正文）' }}
                </p>
              </template>
              <p v-else class="message-preview">{{ message.display_excerpt || '（无正文）' }}</p>
              <button
                v-if="messageContentFor(message.id)?.can_expand"
                class="link-button content-expand-link"
                type="button"
                @click="toggleFullMessageContent(message.id)"
              >
                {{ isMessageExpanded(message.id) ? '收起全文' : '展示全文' }}
              </button>
              <p v-if="messageContentFor(message.id)" class="content-source-note" :class="`tone-${contentSourceState(messageContentFor(message.id)).tone}`" role="status">
                {{ contentSourceState(messageContentFor(message.id)).text }}
              </p>
              <p v-if="messageContentFor(message.id) && contentSourceState(messageContentFor(message.id)).tone === 'warn'" class="content-source-hint">
                可在「我的 / 接入账号」运行「回源自检」定位并按提示重新授权；恢复后查看原文将走实时回源。
              </p>
              <span v-if="messageContentFor(message.id)?.can_expand && !isMessageExpanded(message.id)" class="content-clamp-hint">预览最多显示 8 行；完整内容请展开全文。</span>
            </div>
            <div class="message-actions" :aria-label="`消息 #${message.id} 的操作`">
              <span class="message-action-label">此消息操作</span>
              <button
                v-if="!isAdmin && message.content_state !== 'revoked' && (message.overview?.status === 'failed' || message.overview?.status === 'ready')"
                class="action-button action-secondary"
                type="button"
                :disabled="handlingSubmitting"
                @click="retryMessageOverview(message.id)"
              >
                重新生成中文概要
              </button>
              <button v-if="!isAdmin && (workspaceView === 'messages' || workspaceView === 'customerMessages')"
                class="action-button action-secondary"
                type="button"
                :disabled="contentLoadingMessageIds.has(message.id)"
                @click="toggleOriginalView(message.id)"
              >
                {{ contentLoadingMessageIds.has(message.id) ? '正在读取…' : expandedMessageIds.has(message.id) ? '收起正文' : '查看原文' }}
              </button>
              <button
                v-if="!isAdmin && message.link_state !== 'linked' && currentUser?.role !== 'sales' && group.scope !== 'group'"
                class="action-button action-secondary"
                type="button"
                :disabled="linkReviewLoading || handlingSubmitting"
                @click="toggleLinkReview(message.id)"
              >
                {{ linkReviewLoading && linkReviewMessageId === message.id ? '正在查询…' : linkReviewMessageId === message.id && linkReviewCandidates ? '收起归属候选' : '确认客户归属' }}
              </button>
              <button
                v-if="!isAdmin"
                class="action-button action-primary"
                :class="{ 'is-opening': providerOpeningMessageId === message.id }"
                type="button"
                :disabled="providerOpeningMessageId === message.id"
                @click="openMessageProvider(message)"
              >
                {{ providerOpeningMessageId === message.id ? '正在打开…' : '去渠道处理' }}
              </button>
              <button v-if="!isAdmin && message.content_state !== 'revoked' && (workspaceView === 'messages' || workspaceView === 'customerMessages')"
                class="action-button action-secondary"
                type="button"
                :disabled="handlingSubmitting || message.handling_status === 'processed'"
                @click="updateMessageHandling(message, 'processed')"
              >
                {{ message.handling_status === 'processed' ? '系统外已处理' : '系统外已处理…' }}
              </button>
              <!-- 撤回消息也必须能「忽略」：误判或已知的撤回不能永远卡在待办里。 -->
              <button v-if="!isAdmin && (workspaceView === 'messages' || workspaceView === 'customerMessages')"
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
            <button v-if="messagePage > 1" class="secondary" type="button" :disabled="filterLoading" @click="goToMessagePage(messagePage - 1)">上一页</button>
            <span>第 {{ messagePage }} 页 · 每页 20 条</span>
            <button v-if="canLoadMoreMessages" class="secondary" type="button" :disabled="filterLoading" @click="goToMessagePage(messagePage + 1)">下一页</button>
          </div>
        </div>
      </section>
      </template>

      <section v-if="showInquiryDetail" class="detail-panel panel" :class="{ standalone: isStandalone }">
        <div class="panel-heading">
          <div>
            <p class="eyebrow">记录 #{{ selectedInquiry.id }}</p>
            <h2>{{ selectedInquiry.contact_sources[0]?.customer_nickname || selectedInquiry.contact_sources[0]?.raw_customer_contact || `链路 #${selectedInquiry.id}` }}</h2>
          </div>
          <span v-if="selectedInquiry.contact_sources.length > 0" class="status-pill">{{ [...new Set(selectedInquiry.contact_sources.map((source) => source.channel_type).filter(Boolean))].join(' / ') }}</span>
          <button class="detail-close secondary" type="button" @click="closeStandalonePage">← 返回上一页</button>
        </div>
        <div v-if="!isStandalone" class="detail-navigation">
          <button type="button" class="secondary" :disabled="selectedInquiryIndex <= 0 && inquiryPage === 1" @click="moveInquiry(-1)">上一条</button>
          <span>第 {{ inquiryPage }} / {{ inquiryTotalPages }} 页 · 本页 {{ selectedInquiryIndex + 1 }} / {{ inquiries.length }} 条</span>
          <button type="button" class="secondary" :disabled="selectedInquiryIndex >= inquiries.length - 1 && !inquiryHasMore" @click="moveInquiry(1)">下一条</button>
        </div>

        <div class="facts-grid">
          <div><span>业务类型</span><strong>{{ selectedInquiry.business_type === 'inquiry' ? '询盘' : selectedInquiry.business_type === 'after_sales' ? '售后' : '未分类' }}</strong></div>
          <div><span>阶段/状态</span><strong>{{ selectedInquiry.status === 'new' ? '待人工确认' : statusLabel(selectedInquiry.status) }}</strong></div>
          <div>
            <span>负责人</span>
            <strong>{{ selectedInquiry.assigned_sales_name || selectedInquiry.assigned_sales_username || (selectedInquiry.assigned_sales_user_id ? `用户 #${selectedInquiry.assigned_sales_user_id}` : '未分配') }}</strong>
            <small v-if="selectedInquiry.assigned_sales_username && selectedInquiry.assigned_sales_name && selectedInquiry.assigned_sales_name !== selectedInquiry.assigned_sales_username" class="fact-account">账号 {{ selectedInquiry.assigned_sales_username }}</small>
          </div>
          <div>
            <span>转交人</span>
            <strong>{{ selectedInquiry.transferred_by_name || selectedInquiry.transferred_by_username || '未转交' }}</strong>
            <small v-if="selectedInquiry.transferred_by_username" class="fact-account">
              账号 {{ selectedInquiry.transferred_by_username }}<template v-if="selectedInquiry.transferred_at"> · {{ formatTime(selectedInquiry.transferred_at) }}</template>
            </small>
          </div>
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
              <div class="timeline-copy">
                <strong>{{ inquiryEventLabel(event.event_type) }}</strong>
                <span v-if="event.from_status || event.to_status" class="timeline-change">
                  {{ event.from_status ? statusLabel(event.from_status) : '新建' }}
                  <span aria-hidden="true">→</span>
                  {{ event.to_status ? statusLabel(event.to_status) : '状态未记录' }}
                </span>
              </div>
              <time>{{ formatTime(event.occurred_at) }}</time>
            </li>
          </ol>
        </section>

        <section class="detail-section">
          <h3>关联客户消息</h3>
          <p class="muted">{{ isAdmin ? '管理员仅查看脱敏后的中文概述、渠道、时间与处理状态；不展示正文、联系人信息或渠道账号标识。' : '以运营同事入站时清洗后的安全原文为主，中文概述只在下方以小字补充；「查看客户消息」可就地打开完整原文。' }}</p>
          <p v-if="selectedInquiry.messages.length === 0" class="empty">当前没有可见关联消息。</p>
          <ol v-else class="timeline linked-message-timeline">
            <li v-for="linkedMessage in selectedInquiry.messages" :key="linkedMessage.id" class="linked-message-item" :class="{ 'is-revoked': linkedMessage.content_state === 'revoked' }">
              <div class="linked-message-copy">
                <span class="linked-message-origin">
                {{ channelLabel(linkedMessage.channel_type) }} · {{ linkedMessage.direction === 'inbound' ? '客户入站' : '系统出站' }} · {{ formatTime(linkedMessage.occurred_at) }}
                </span>
                <strong>消息 #{{ linkedMessage.id }} · <span :class="linkedMessage.content_state === 'revoked' ? 'linked-message-revoked-label' : ''">{{ messageStatusLabel(linkedMessage) }}</span></strong>
                <small v-if="!isAdmin">发送人/联系人：{{ selectedInquiry.contact_sources.find((source) => source.channel_account_id === linkedMessage.channel_account_id)?.customer_nickname || selectedInquiry.contact_sources.find((source) => source.channel_account_id === linkedMessage.channel_account_id)?.raw_customer_contact || '当前来源未提供' }} · 渠道账号：{{ linkedMessage.channel_account_external_id || accountLabel(linkedMessage.channel_account_id) }}</small>
                <!-- 主展示 = 清洗后的安全原文。撤回没有可恢复的正文，直接给出撤回说明。 -->
                <p v-if="isAdmin" class="linked-message-safe-text is-hidden" :class="`is-admin-status-${adminMessageStatus(linkedMessage).tone}`">{{ adminMessageStatus(linkedMessage).text }}</p>
                <pre v-else-if="linkedMessage.safe_text" class="linked-message-safe-text" :class="{ 'is-revoked': linkedMessage.content_state === 'revoked' }">{{ linkedMessage.safe_text }}</pre>
                <p v-else class="linked-message-safe-text is-empty">这条消息没有可展示的正文（可能只有附件）。</p>
                <small v-if="!isAdmin && linkedMessage.safe_text_truncated" class="linked-message-more">仅显示前段原文，完整内容请点「查看客户消息」。</small>
                <!-- 中文概述降级为下方小字；撤回消息不再输出「消息内容为空」的误导性概述。 -->
                <small v-if="!isAdmin && linkedMessage.content_state !== 'revoked'" class="linked-message-overview">中文概述：{{ linkedOverviewText(linkedMessage) }}</small>
              </div>
              <button v-if="!isAdmin" class="secondary" type="button" title="查看这条消息清洗后的安全原文" @click="openCustomerMessage(linkedMessage.id)">查看客户消息</button>
            </li>
          </ol>
        </section>

        <section v-if="!isAdmin" class="detail-section">
          <h3>确定性分析</h3>
          <p v-if="!analysis" class="empty">当前没有分析结果。</p>
          <template v-else>
            <p class="muted">当前阶段：{{ analysis.my_transfers?.find((item) => item.inquiry_id === selectedInquiry.id)?.current_stage ?? statusLabel(selectedInquiry.status) }}</p>
            <p class="muted">最近可用事件时间：{{ formatTime(analysis.my_transfers?.find((item) => item.inquiry_id === selectedInquiry.id)?.recent_event?.occurred_at ?? selectedInquiry.updated_at) }}</p>
            <p class="muted">事件历史：{{ selectedInquiry.timeline_complete ? '已由后端持久化事件提供。' : '当前没有完整的持久化事件历史。' }}</p>
          </template>
        </section>

        <section v-if="canOperateChannels || isAdmin" class="detail-section action-section">
          <h3>{{ isAdmin ? '管理员改派' : '当前可执行操作' }}</h3>
          <button v-if="canOperateChannels" class="secondary operation-log-button" type="button" @click="openOperationLogs(selectedInquiry.id)">查看此链路操作记录</button>
          <div v-if="canOperateChannels && selectedInquiry.handling_status !== 'pending'" class="restore-link-banner">
            <span>当前链路已{{ selectedInquiry.handling_status === 'processed' ? '处理' : '忽略' }}；恢复后才能继续分配或处理。</span>
            <button class="secondary" type="button" :disabled="handlingSubmitting" @click="reactivateSelectedInquiry">恢复链路</button>
          </div>
          <p v-if="actionError" class="action-error">{{ actionError }}</p>
          <p v-if="actionMessage" class="inline-feedback success">{{ actionMessage }}</p>
          <div v-if="selectedInquiry.status === 'new' || (isAdmin && selectedInquiry.status === 'assigned')" class="transfer-form">
            <label for="transfer-business-type">业务类型</label>
            <select id="transfer-business-type" v-model="selectedBusinessType">
              <option :value="null">请选择类型</option><option value="inquiry">询盘</option><option value="after_sales">售后</option>
            </select>
            <label for="transfer-target">分配负责人</label>
            <select id="transfer-target" v-model="selectedSalesUserId">
              <option :value="null">请选择业务员</option>
              <option v-for="target in transferTargets" :key="target.id" :value="target.id">
                {{ transferTargetLabel(target) }}
              </option>
            </select>
            <button
              class="primary"
              type="button"
              :disabled="transferSubmitting || selectedSalesUserId === null || selectedBusinessType === null"
              @click="transferSelectedInquiry"
            >
              {{ transferSubmitting ? '分配中…' : isAdmin && selectedInquiry.status === 'assigned' ? '确认改派' : '确认分配' }}
            </button>
            <p v-if="transferTargets.length === 0" class="muted">当前没有可用的 active sales 目标。</p>
          </div>
          <p v-else-if="selectedInquiry.status !== 'assigned' || !isAdmin" class="muted">当前询盘已转交；运营不能自动改派，需管理员在此明确选择新负责人。</p>
          <div v-if="canOperateChannels" class="actions">
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
      <section v-else-if="route.page === 'message'" class="detail-panel panel standalone message-detail-page">
        <p v-if="messageDetailLoading && !messageDetail" class="empty">正在加载消息…</p>
        <template v-else-if="messageDetail">
          <div class="panel-heading">
            <div>
              <p class="eyebrow">消息 #{{ messageDetail.id }}</p>
              <h2>{{ messageContactLabel(messageDetail) }}</h2>
            </div>
            <span class="status-pill">{{ channelLabel(messageDetail.channel_type) }}</span>
          </div>
          <div class="facts-grid">
            <div><span>发送人</span><strong>{{ messageSenderLabel(messageDetail) }}</strong></div>
            <div><span>时间</span><strong>{{ formatTime(messageDetail.occurred_at) }}</strong></div>
            <div><span>人工状态</span><strong :class="messageDetail.content_state === 'revoked' ? 'is-revoked-text' : ''">{{ messageStatusLabel(messageDetail) }}</strong></div>
            <div><span>归链状态</span><strong>{{ linkStateLabel(messageDetail.link_state) }}</strong></div>
          </div>
          <section class="detail-section">
            <h3>安全原文（清洗后）</h3>
            <p v-if="messageDetailContent" class="message-original">{{ messageDetailContent.parsed_content.display_text || messageDetailContent.preview_text }}</p>
            <p v-else class="message-original">{{ messageDetail.display_excerpt || '（无正文）' }}</p>
            <button v-if="!isAdmin && !messageDetailContent" class="secondary" type="button" :disabled="messageDetailLoading" @click="loadMessageDetailContent">
              {{ messageDetailLoading ? '加载中…' : '查看完整原文' }}
            </button>
          </section>
          <section class="detail-section">
            <h3>中文概述（辅助）</h3>
            <p v-if="messageDetail.content_state === 'revoked'" class="message-overview-inline">客户已撤回这条消息，不再生成中文概述。</p>
            <p v-else-if="messageDetail.overview?.status === 'ready'" class="message-overview-inline">中文概述：{{ messageDetail.overview.text }}</p>
            <p v-else class="message-overview-inline">暂无中文概述。</p>
          </section>
          <p v-if="actionError" class="action-error">{{ actionError }}</p>
          <p v-if="actionMessage" class="inline-feedback success">{{ actionMessage }}</p>
          <div class="actions">
            <button v-if="messageDetail.content_state !== 'revoked'" class="secondary" type="button" :disabled="handlingSubmitting || messageDetail.handling_status === 'processed'" @click="updateDetailMessageHandling('processed')">标记已处理</button>
            <button class="secondary" type="button" :disabled="handlingSubmitting || messageDetail.handling_status === 'ignored'" @click="updateDetailMessageHandling('ignored')">忽略</button>
            <button v-if="!isAdmin && messageDetail.handling_status !== 'pending'" class="secondary" type="button" :disabled="handlingSubmitting" @click="restoreDetailMessage">恢复到待处理</button>
          </div>
          <p class="muted">{{ isAdmin ? '管理员仅处理已入站消息；不能发送客户消息或执行渠道授权。' : '页面不代替后端授权，不会自动发送、自动转交或修改客户数据。' }}</p>
        </template>
        <p v-else class="empty">消息不存在，或当前账号无权访问。</p>
      </section>
      <section v-else-if="!isStandalone && isInquiryView && inquiries.length === 0" class="detail-panel panel empty-state">
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
  <Transition name="link-dialog">
    <div
      v-if="customerMessageId !== null"
      class="link-review-backdrop"
      @click.self="closeCustomerMessage"
      @keydown.esc.window="closeCustomerMessage"
    >
      <section class="link-review-dialog customer-message-dialog" role="dialog" aria-modal="true" aria-labelledby="customer-message-title" tabindex="-1">
        <header class="link-review-heading">
          <div>
            <p class="eyebrow">消息 #{{ customerMessageId }} · 客户消息<span v-if="customerMessageRevoked" class="customer-message-revoked-tag">已撤回</span></p>
            <h2 id="customer-message-title">安全文本（清洗后的原文）</h2>
            <p v-if="customerMessageRevoked" class="link-review-subtitle">客户已双端删除／撤回这条消息，渠道侧也读不回可恢复的正文；这不是「消息为空」，无需按询盘处理。</p>
            <p v-else class="link-review-subtitle">运营同事入站时落库的清洗后正文，就是这条消息本身的内容。</p>
          </div>
          <button class="dialog-close" type="button" aria-label="关闭客户消息窗口" @click="closeCustomerMessage">关闭 <span aria-hidden="true">×</span></button>
        </header>
        <div class="link-review-content" aria-live="polite">
          <p v-if="customerMessageLoading" class="dialog-state">正在读取安全文本…</p>
          <div v-else-if="customerMessageError" class="dialog-state dialog-error" role="alert">
            <p>{{ customerMessageError }}</p>
            <button class="secondary" type="button" @click="retryCustomerMessage">重试</button>
          </div>
          <p v-else-if="!customerMessageText" class="dialog-state">这条消息没有可展示的正文（可能只有附件或客户已撤回）。</p>
          <pre v-else class="customer-message-text" :class="{ 'is-revoked': customerMessageRevoked }">{{ customerMessageText }}</pre>
          <p v-if="customerMessageContent && customerMessageContent.source.kind === 'cached_safe_text'" class="customer-message-source">
            渠道实时回读不可用，以上为入站时保存的快照{{ customerMessageContent.source.snapshot_at ? `（${formatTime(customerMessageContent.source.snapshot_at)}）` : '' }}。
          </p>
        </div>
        <footer class="link-review-footer">
          <span>{{ customerMessageRevoked ? '客户已撤回，原文不可恢复；不能标记已处理，但仍可在消息列表点「忽略」清理。' : '仅显示清洗后的安全文本，不含渠道原始数据；不代替渠道授权。' }}</span>
          <div class="customer-message-actions">
            <button class="secondary" type="button" :disabled="!customerMessageText || customerMessageRevoked" @click="copyCustomerMessage">{{ customerMessageCopied ? '已复制' : '复制文本' }}</button>
            <button class="secondary" type="button" @click="closeCustomerMessage">关闭</button>
          </div>
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
.facts-grid .fact-account { display: block; margin-top: 4px; color: #9aa5b5; font-size: 12px; }
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
.refetch-check-result.warn { border-color: #e2c9a4; background: #fdf8f0; color: #7a5220; }
.refetch-check-result.info { border-color: #c7d8e8; background: #f4f8fc; color: #2c4a67; }
.refetch-check-result p { margin: 4px 0 0; }
.refetch-check-result ul { margin: 6px 0 0; padding-left: 18px; }
.refetch-check-result .refetch-meta { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; letter-spacing: .01em; opacity: .85; overflow-wrap: anywhere; }
.refetch-check-result .refetch-scope { padding-top: 6px; border-top: 1px dashed currentColor; opacity: .85; }
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
/* Direct children only: .message-content-view is itself a grid, so an
   unscoped `p` rule put the preview, the source note and the warning into the
   same row and made the text overlap. */
.message-row > p { grid-column: 2; grid-row: 1; margin: 0; color: #344047; line-height: 1.55; }
.message-row .message-actions { grid-column: 3; grid-row: 1 / span 2; justify-content: flex-end; align-items: flex-start; margin-top: 0; }
.message-row .channel-mark { display: inline-flex; width: fit-content; margin-top: 2px; padding: 3px 6px; color: #1d5fbf; background: #e8f0fb; border-radius: 3px; font-size: 11px; font-weight: 800; }
.message-row > .message-preview { grid-column: 2; }
/* 收起态的「安全原文 + 小字概述」作为一个网格项，避免两段 <p> 都落到 row1 col2 重叠。 */
.message-row > .message-brief { grid-column: 2; grid-row: 1; display: grid; gap: 4px; min-width: 0; }
.message-brief > .message-preview { margin: 0; color: #344047; font-size: 13px; line-height: 1.55; overflow-wrap: anywhere; }
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
  .message-row .message-meta, .message-row > p, .message-row > .message-preview, .message-row > .message-brief, .message-row .message-actions, .message-row .channel-mark { grid-column: 1; grid-row: auto; }
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
  .message-row .message-meta, .message-row > p, .message-row > .message-preview, .message-row > .message-brief, .message-row .message-actions { grid-column: 1; grid-row: auto; }
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
.admin-connect-note { background: #f4f8ff; border: 1px solid #d6e3fb; border-radius: 12px; border-bottom: 1px solid #d6e3fb; }
.admin-connect-note h3 { color: #1c3f7c; }
.admin-connect-note p { color: #4b6288; line-height: 1.7; }
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
/* 客户链路：主展示是清洗后的安全原文，中文概述只在下方以小字补充。 */
.linked-message-safe-text { margin: 4px 0 0; padding: 11px 13px; color: #223439; background: #fff; border: 1px solid #dfe8e9; border-left: 3px solid #367c72; border-radius: 4px; font-family: inherit; font-size: 13.5px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; max-height: 16em; overflow: auto; }
.linked-message-safe-text.is-revoked { color: #8a5a20; background: #fff8ec; border-left-color: #d69a3c; }
.linked-message-safe-text.is-hidden, .linked-message-safe-text.is-empty { color: #52666b; background: transparent; border-style: dashed; font-size: 12.5px; }
.linked-message-safe-text.is-hidden.is-admin-status-success { color: #18794e; background: #f0faf4; border-color: #b7e4c7; border-left-color: #23945f; }
.linked-message-safe-text.is-hidden.is-admin-status-failure { color: #b42318; background: #fff4f2; border-color: #f4c7c3; border-left-color: #d92d20; }
.linked-message-item.is-revoked { background: #fffaf1; border-color: #eeddbd; }
.linked-message-revoked-label { color: #a05d16; font-weight: 700; }
.linked-message-more { display: block; font-size: 11.5px; }
.linked-message-copy > .linked-message-overview { display: block; margin: 6px 0 0; padding: 0; color: #52666b; background: transparent; border: 0; font-size: 12px; font-weight: 400; line-height: 1.55; white-space: pre-wrap; overflow-wrap: anywhere; }
.message-overview-inline { margin: 5px 0 0; color: #52666b; font-size: 12px; line-height: 1.55; }
.state-label.is-revoked, .is-revoked-text { color: #a05d16; }
.customer-message-revoked-tag { display: inline-block; margin-left: 8px; padding: 1px 6px; color: #8a5a20; background: #fff1d9; border-radius: 3px; font-size: 11px; font-weight: 700; }
.customer-message-text.is-revoked { color: #8a5a20; background: #fff8ec; border-color: #ead7b4; }
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
  .message-row .message-meta, .message-row > p, .message-row > .message-preview, .message-row > .message-brief, .message-row .message-actions { grid-column: 1; grid-row: auto; }
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
.customer-message-dialog { width: min(720px, 100%); }
.customer-message-text { margin: 0; padding: 16px 18px; color: #202d31; background: #f8fafb; border: 1px solid #e2e9eb; border-radius: 6px; font-family: inherit; font-size: 14px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.customer-message-source { margin: 12px 0 0; color: #718085; font-size: 12px; line-height: 1.6; }
.customer-message-actions { display: flex; gap: 8px; flex: 0 0 auto; }
.link-dialog-enter-active, .link-dialog-leave-active { transition: opacity 180ms ease; }
.link-dialog-enter-active .link-review-dialog, .link-dialog-leave-active .link-review-dialog { transition: transform 180ms cubic-bezier(.2,.75,.25,1); }
.link-dialog-enter-from, .link-dialog-leave-to { opacity: 0; }
.link-dialog-enter-from .link-review-dialog, .link-dialog-leave-to .link-review-dialog { transform: translateY(10px); }
@media (max-width: 700px) {
  .message-row { grid-template-columns: 1fr; gap: 8px; }
  .message-row .message-meta, .message-row > p, .message-row > .message-preview, .message-row > .message-brief, .message-row .message-actions { grid-column: 1; grid-row: auto; }
  .link-review-backdrop { align-items: end; padding: 8px; }
  .link-review-dialog { width: 100%; max-height: 88vh; border-radius: 10px 10px 6px 6px; }
  .link-review-heading, .link-review-content { padding-right: 16px; padding-left: 16px; }
  .link-review-heading h2 { font-size: 18px; }
  .link-candidate-row { align-items: stretch; flex-direction: column; gap: 12px; }
  .link-candidate-row .primary { width: 100%; }
  .link-review-footer { padding: 12px 16px; }
}

/* URL-addressable standalone pages (inquiry / message / logs / settings). */
.page-breadcrumb { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 12px 18px; margin-bottom: 16px; background: #fff; border: 1px solid #e4eaeb; border-radius: 10px; }
.page-breadcrumb button { font-size: 13px; }
.page-breadcrumb span { color: #435159; font-size: 14px; font-weight: 600; }
.page-breadcrumb-full { grid-column: 1 / -1; margin-bottom: 4px; }
.standalone-page { width: min(1152px, 100%); margin: 24px auto 0; }
.operation-log-page .operation-log-dialog { width: 100%; max-height: none; box-shadow: none; }
.content-grid.is-standalone { display: block; padding: 0; background: transparent; border: 0; border-radius: 0; }
.detail-panel.standalone { width: 100%; }
.message-detail-page .message-original { white-space: pre-wrap; word-break: break-word; padding: 14px; margin: 0; background: #f7faf9; border: 1px solid #e4eaeb; border-radius: 8px; font-size: 13px; line-height: 1.7; }
.restore-link-banner { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 12px 14px; margin: 10px 0; color: #8a4b12; background: #fff7e8; border: 1px solid #f0d9ac; border-radius: 8px; font-size: 13px; }
@media (max-width: 700px) {
  .page-breadcrumb { padding: 10px 12px; }
  .restore-link-banner { flex-direction: column; align-items: flex-start; }
}

/* Admin employee management: labelled forms, roomy cards and a full roster table. */
.employee-admin-page { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; margin-bottom: 48px; }
.ea-hero { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 26px 28px; background: #fff; border: 1px solid #e2e7f0; border-radius: 16px; box-shadow: 0 10px 30px rgba(30, 45, 75, .06); }
.ea-hero-text h2 { margin: 0 0 8px; font-size: 26px; font-weight: 650; letter-spacing: -.02em; }
.ea-hero-lede { max-width: 640px; margin: 0; color: #667287; font-size: 14px; line-height: 1.7; }
.ea-hero-actions { display: flex; flex: 0 0 auto; flex-wrap: wrap; gap: 10px; }
.ea-hero-actions .secondary { padding: 10px 16px; }
.ea-alert { margin: 0; }
.ea-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }
.ea-stat { display: grid; gap: 6px; padding: 18px 20px; background: #fff; border: 1px solid #e2e7f0; border-radius: 14px; box-shadow: 0 6px 18px rgba(30, 45, 75, .04); }
.ea-stat > span { color: #6c7890; font-size: 12px; font-weight: 650; }
.ea-stat strong { color: #172033; font-size: 28px; line-height: 1.15; }
.ea-stat small { color: #8a95a8; font-size: 12px; }
.ea-card { overflow: hidden; background: #fff; border: 1px solid #e2e7f0; border-radius: 16px; box-shadow: 0 10px 30px rgba(30, 45, 75, .06); }
.ea-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 22px 26px 18px; border-bottom: 1px solid #edf0f5; }
.ea-card-head h3 { margin: 0 0 6px; color: #172033; font-size: 17px; font-weight: 650; }
.ea-card-head p { margin: 0; color: #758198; font-size: 13px; line-height: 1.6; }
.ea-step { display: grid; flex: 0 0 auto; width: 34px; height: 34px; place-items: center; color: #3158c9; background: #edf2ff; border-radius: 10px; font-size: 12px; font-weight: 700; }
.ea-form { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); align-items: start; gap: 18px 20px; padding: 24px 26px 26px; }
.ea-field { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.ea-label { color: #3f4b5e; font-size: 12px; font-weight: 650; }
.ea-label em { margin-left: 6px; padding: 2px 6px; color: #7a4d00; background: #fff1c7; border-radius: 4px; font-size: 10px; font-style: normal; font-weight: 700; }
.ea-field input, .ea-field select { width: 100%; min-height: 42px; padding: 10px 12px; color: #172033; background: #fff; border: 1px solid #d7dfe9; border-radius: 9px; font: inherit; font-size: 14px; outline: none; transition: border-color .15s, box-shadow .15s; }
.ea-field input:focus, .ea-field select:focus { border-color: #3158c9; box-shadow: 0 0 0 3px rgba(49, 88, 201, .12); }
.ea-field input::placeholder { color: #a3adbd; }
.ea-field input:disabled, .ea-field select:disabled { color: #8b96a8; background: #f5f7fa; cursor: not-allowed; }
.ea-hint { color: #8a95a8; font-size: 11.5px; line-height: 1.5; }
.ea-form-submit { display: flex; grid-column: 1 / -1; align-items: center; gap: 16px; padding-top: 4px; }
.ea-form-submit .primary { padding: 11px 22px; font-weight: 650; }
.ea-form-submit .primary:disabled { opacity: .6; cursor: not-allowed; }
.ea-feedback { display: flex; grid-column: 1 / -1; align-items: flex-start; gap: 12px; padding: 14px 16px; margin: 0 0 2px; border: 1px solid; border-radius: 11px; font-size: 13px; line-height: 1.65; }
.ea-feedback.success { color: #14603f; background: #f0fbf5; border-color: #b9e6cf; }
.ea-inline-feedback { display: flex; align-items: flex-start; gap: 8px; margin: 10px 0 0; padding: 9px 12px; border: 1px solid; border-radius: 9px; font-size: 12.5px; line-height: 1.65; }
.ea-inline-feedback.success { color: #14603f; background: #f0fbf5; border-color: #b9e6cf; }
.ea-inline-feedback.error { color: #8f2f3c; background: #fff7f8; border-color: #f2c9cf; }
.ea-inline-feedback-icon { display: grid; flex: 0 0 auto; width: 18px; height: 18px; margin-top: 1px; place-items: center; color: #fff; border-radius: 50%; font-size: 11px; font-weight: 700; }
.ea-inline-feedback.success .ea-inline-feedback-icon { background: #1f9d63; }
.ea-inline-feedback.error .ea-inline-feedback-icon { background: #d1495b; }
.ea-feedback.error { color: #8f2f3c; background: #fff7f8; border-color: #f2c9cf; }
.ea-feedback-icon { display: grid; flex: 0 0 auto; width: 22px; height: 22px; place-items: center; color: #fff; border-radius: 50%; font-size: 13px; font-weight: 700; }
.ea-feedback.success .ea-feedback-icon { background: #1f9d63; }
.ea-feedback.error .ea-feedback-icon { background: #d1495b; }
.ea-feedback-body { flex: 1 1 auto; min-width: 0; }
.ea-feedback-body strong { display: block; margin-bottom: 2px; font-size: 13px; font-weight: 700; }
.ea-feedback-body p { margin: 0; }
.ea-feedback-link { flex: 0 0 auto; padding-top: 2px; font-size: 12px; white-space: nowrap; }
.ea-feedback-close { flex: 0 0 auto; width: 24px; height: 24px; padding: 0; color: inherit; background: transparent; border: 0; border-radius: 6px; font-size: 18px; line-height: 1; cursor: pointer; opacity: .6; }
.ea-feedback-close:hover { opacity: 1; background: rgba(0, 0, 0, .05); }
.ea-feedback-block { grid-column: auto; margin: 18px 26px 0; }
.ea-channel-accounts-table { min-width: 960px; }
.ea-regrant { padding: 8px 13px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.ea-regrant:disabled { opacity: .6; cursor: not-allowed; }
.ea-transfer-bar { display: grid; grid-template-columns: minmax(210px, 260px) minmax(0, 1fr) auto; align-items: end; gap: 18px 22px; padding: 22px 26px; background: #f7f9ff; border-bottom: 1px solid #e6ebf7; }
.ea-transfer-field { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.ea-transfer-field select { width: 100%; min-height: 44px; padding: 10px 12px; color: #172033; background: #fff; border: 1px solid #cfd9ec; border-radius: 9px; font: inherit; font-size: 14px; outline: none; }
.ea-transfer-field select:focus { border-color: #3158c9; box-shadow: 0 0 0 3px rgba(49, 88, 201, .12); }
.ea-transfer-copy { padding-bottom: 2px; }
.ea-transfer-copy strong { display: block; margin-bottom: 5px; color: #253550; font-size: 13px; font-weight: 650; }
.ea-transfer-copy p { margin: 0; color: #73819a; font-size: 12px; line-height: 1.7; }
.ea-transfer-submit { min-height: 44px; padding: 11px 20px; font-size: 13px; font-weight: 650; white-space: nowrap; }
.ea-transfer-submit:disabled, .ea-transfer-one:disabled { opacity: .55; cursor: not-allowed; }
.ea-transfer-empty { margin: 0; padding: 12px 26px; color: #8a5a00; background: #fff8e8; border-bottom: 1px solid #f0e0bb; font-size: 12.5px; line-height: 1.6; }
.ea-table tbody tr.ea-row-checked:not(.is-revoked) { background: #fbfcff; }
.ea-th-check { width: 44px; text-align: center; white-space: nowrap; }
.ea-th-check input[type="checkbox"] { width: 16px; height: 16px; accent-color: #3158c9; cursor: pointer; }
.ea-owner { display: flex; flex-direction: column; align-items: flex-start; gap: 5px; }
.ea-row-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
.ea-transfer-one { padding: 8px 12px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.ea-card-foot { margin: 0; padding: 14px 26px 20px; color: #8a95a8; border-top: 1px solid #edf0f5; font-size: 12px; line-height: 1.65; }
.ea-table tbody tr.is-revoked { background: #fff9f9; }
.ea-toolbar { display: flex; flex-wrap: wrap; align-items: flex-end; gap: 14px; padding: 20px 26px; background: #fafbfd; border-bottom: 1px solid #edf0f5; }
.ea-search { flex: 1 1 260px; max-width: 340px; }
.ea-toolbar-select { width: 160px; }
.ea-toolbar-hint { flex: 0 0 auto; max-width: 170px; padding-bottom: 12px; }
.ea-clear { padding-bottom: 12px; font-size: 12px; }
.ea-scroll-hint { display: none; width: 100%; color: #8a95a8; font-size: 11.5px; }
.ea-table-wrap { overflow-x: auto; }
.ea-table { width: 100%; min-width: 940px; border-collapse: collapse; font-size: 13px; text-align: left; }
.ea-table th, .ea-table td { padding: 15px 18px; border-bottom: 1px solid #edf0f5; vertical-align: middle; }
.ea-table th { position: sticky; top: 0; z-index: 1; color: #5c6b80; background: #f5f7fb; font-size: 12px; font-weight: 650; white-space: nowrap; }
.ea-table tbody tr:not(.ea-detail-row):hover { background: #f8faff; }
.ea-table tbody tr.is-selected { background: #eef3ff; }
.ea-table tbody tr.is-inactive { color: #98a2b3; }
.ea-th-action { text-align: right; white-space: nowrap; }
.ea-person { display: flex; align-items: center; gap: 11px; }
.ea-avatar { display: grid; flex: 0 0 36px; width: 36px; height: 36px; place-items: center; color: #3158c9; background: #eaf0ff; border-radius: 10px; font-size: 15px; font-weight: 700; }
.ea-person-name { display: grid; gap: 2px; min-width: 0; }
.ea-person-name strong { font-size: 14px; font-weight: 650; overflow-wrap: anywhere; }
.ea-person-name small { color: #8a95a8; font-size: 11px; }
.ea-role { display: inline-block; padding: 4px 10px; color: #165d68; background: #eaf5f5; border-radius: 6px; font-size: 12px; font-weight: 600; white-space: nowrap; }
.ea-pills, .ea-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.ea-pill { padding: 3px 9px; border-radius: 999px; font-size: 11px; font-weight: 650; white-space: nowrap; }
.ea-pill.is-on { color: #176b43; background: #e4f6eb; }
.ea-pill.is-off { color: #5f6368; background: #e9ecef; }
.ea-pill.is-warn { color: #8a5a00; background: #fff2cc; }
.ea-chip { padding: 3px 9px; color: #3d4b5c; background: #eef1f6; border-radius: 6px; font-size: 11px; font-weight: 600; white-space: nowrap; }
.ea-chip.is-blue { color: #2450a6; background: #e9f0ff; }
.ea-chip.is-purple { color: #6a3fa0; background: #f1eafb; }
.ea-chip.is-removable { border: 1px solid #d7dfe9; cursor: pointer; }
.ea-chip.is-removable:hover { color: #9a2f3b; background: #fff0f2; border-color: #efc7cd; }
.ea-chip.is-removable span { margin-left: 4px; font-size: 13px; }
.ea-muted { color: #9aa5b5; font-size: 12px; }
.ea-archive-card { border-color: #e4e8f0; background: #fbfcfe; }
.ea-archive-card .ea-table { min-width: 760px; }
.ea-archive-card .ea-table th { background: #f1f3f8; }
.ea-archive-count { flex: 0 0 auto; padding: 5px 12px; color: #5f6368; background: #eceff4; border-radius: 999px; font-size: 12px; font-weight: 650; }
.ea-avatar.is-off { color: #7b8494; background: #eceff4; }
.ea-manage { padding: 8px 14px; font-size: 12px; }
.ea-detail-row > td { padding: 0; background: #f7f9fd; border-bottom: 2px solid #dfe6f5; }
.ea-detail { padding: 24px 26px 28px; }
.ea-detail-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.ea-detail-head h4 { margin: 0 0 5px; font-size: 16px; font-weight: 650; }
.ea-detail-head p { margin: 0; color: #758198; font-size: 12.5px; line-height: 1.6; }
/* 账户名是唯一登录凭据，展开设置后必须一眼能看到，否则改错人也不知道。 */
.ea-detail-account { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin: 0 0 6px !important; color: #4a5568; font-size: 12.5px; }
.ea-detail-account code { padding: 2px 8px; color: #172033; background: #eef1f7; border: 1px solid #e2e7f0; border-radius: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12.5px; font-weight: 650; letter-spacing: .01em; }
.ea-detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.ea-detail-block { display: flex; flex-direction: column; gap: 12px; padding: 20px; background: #fff; border: 1px solid #e4e9f2; border-radius: 12px; }
.ea-detail-block h5 { margin: 0; color: #172033; font-size: 14px; font-weight: 650; }
.ea-block-note { margin: 0; color: #6c7890; font-size: 12px; line-height: 1.7; }
.ea-block-note strong { color: #3158c9; }
.ea-detail-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.ea-inline-form { display: flex; align-items: flex-end; gap: 10px; }
.ea-inline-form .ea-field { flex: 1 1 auto; }
.ea-inline-form .secondary { flex: 0 0 auto; min-height: 42px; }
.ea-chips-removable { margin: 2px 0; }
.ea-channel-toggles { display: grid; gap: 9px; }
.ea-channel-feedback { margin: 0; padding: 9px 11px; border: 1px solid; border-radius: 8px; font-size: 12px; }
.ea-channel-feedback.success { color: #176b43; background: #f0faf4; border-color: #8fc9ae; }
.ea-channel-feedback.error { color: #9a2f3b; background: #fff5f6; border-color: #efc7cd; }
.ea-toggle { display: flex; align-items: center; gap: 12px; width: 100%; padding: 11px 13px; color: #3f4b5e; background: #fafbfd; border: 1px solid #dfe5ee; border-radius: 10px; text-align: left; }
.ea-toggle.is-granted { background: #f0faf4; border-color: #8fc9ae; }
.ea-channel-action { flex: 0 0 auto; padding: 6px 11px; color: #2450a6; background: #fff; border: 1px solid #cbd6e8; border-radius: 7px; cursor: pointer; font-size: 12px; }
.ea-channel-action:hover:not(:disabled) { background: #f2f6ff; border-color: #3158c9; }
.ea-channel-action:disabled { cursor: wait; opacity: .65; }
.ea-channel-revoke { color: #9a2f3b; border-color: #efc7cd; }
.ea-channel-revoke:hover:not(:disabled) { background: #fff5f6; border-color: #d98c96; }
.ea-toggle-dot { flex: 0 0 12px; width: 12px; height: 12px; background: #cbd4e1; border-radius: 50%; box-shadow: inset 0 0 0 2px #fff; }
.ea-toggle.is-granted .ea-toggle-dot { background: #2e9c68; }
.ea-toggle-text { display: grid; flex: 1; gap: 2px; }
.ea-toggle-text strong { font-size: 13px; font-weight: 650; }
.ea-toggle-text small { color: #8a95a8; font-size: 11px; }
.ea-toggle-state { color: #7b8798; font-size: 11px; font-weight: 650; white-space: nowrap; }
.ea-toggle.is-granted .ea-toggle-state { color: #176b43; }
.ea-danger-row { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; padding-top: 4px; border-top: 1px dashed #e6ebf2; }
.ea-danger-link, .ea-danger { color: #9a2f3b; }
.ea-danger { padding: 9px 14px; font-size: 13px; font-weight: 650; background: #fff5f6; border: 1px solid #efc7cd; border-radius: 9px; cursor: pointer; }
.ea-danger:hover { background: #ffe9ec; }
.ea-confirm-text { color: #9a2f3b; font-size: 12.5px; font-weight: 600; }
.ea-empty { padding: 46px 20px; color: #8a95a8; text-align: center; }
@media (max-width: 980px) {
  .ea-form { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ea-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ea-detail-grid { grid-template-columns: 1fr; }
  .ea-transfer-bar { grid-template-columns: minmax(200px, 260px) minmax(0, 1fr); }
  .ea-transfer-submit { grid-column: 1 / -1; justify-self: start; }
}
@media (max-width: 620px) {
  .employee-admin-page { gap: 14px; padding: 0 12px; }
  .ea-hero { flex-direction: column; padding: 20px; }
  .ea-form { grid-template-columns: 1fr; padding: 20px; }
  .ea-card-head, .ea-toolbar, .ea-detail { padding-left: 18px; padding-right: 18px; }
  .ea-transfer-bar { grid-template-columns: 1fr; gap: 14px; padding: 18px; }
  .ea-transfer-submit { grid-column: 1; width: 100%; white-space: normal; }
  .ea-transfer-empty { padding: 12px 18px; }
  .ea-row-actions { justify-content: flex-start; }
  .ea-detail-fields, .ea-inline-form { flex-direction: column; align-items: stretch; }
  .ea-inline-form .secondary { width: 100%; }
  .ea-stat { padding: 14px 16px; }
  .ea-scroll-hint { display: block; }
  .ea-feedback { flex-wrap: wrap; gap: 8px 10px; padding: 12px 14px; }
  .ea-feedback-body { flex: 1 1 calc(100% - 60px); }
  .ea-feedback-link { margin-left: 34px; }
  .ea-feedback-block { margin: 14px 16px 0; }
  .ea-card-foot { padding-left: 18px; padding-right: 18px; }
}
@media (max-width: 700px) {
  /* Higher specificity than the shared stylesheet so header buttons wrap instead of overflowing. */
  .workspace > .topbar { flex-direction: column; flex-wrap: wrap; align-items: flex-start; gap: 12px; }
  .workspace > .topbar .topbar-actions { width: 100%; flex-wrap: wrap; gap: 8px; }
}

/* Conversation group headers: give the label room to breathe. */
.message-group .message-group-bar { gap: 16px; }
.message-group .message-group-bar .group-label { display: inline-flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 13px; line-height: 1.65; }
.message-group .message-group-bar .gb-group-tag { margin-left: 0; }

/* 批量处理：整页 / 整组一次提交，同一会话不再需要逐条点。 */
.bulk-action-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; margin: 14px 0 4px; padding: 10px 14px; background: #f1f7f8; border: 1px solid #d7e5e7; border-radius: 6px; }
.bulk-select-all, .group-select-control, .message-select-control { display: inline-flex; align-items: center; gap: 6px; color: #165d68; font-size: 12px; font-weight: 700; cursor: pointer; }
.bulk-select-all input, .group-select-control input, .message-select-control input { flex: 0 0 auto; width: 15px; height: 15px; margin: 0; accent-color: #247a57; cursor: pointer; }
.bulk-select-all input:disabled + span, .group-select-control input:disabled + span, .message-select-control input:disabled + span { opacity: .55; }
.bulk-selection-count { color: #314b50; font-size: 12px; font-weight: 700; white-space: nowrap; }
.bulk-action-buttons { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-left: auto; }
.bulk-feedback { flex-basis: 100%; margin: 0; font-size: 12px; line-height: 1.6; }
.bulk-feedback.success { color: #176b43; }
.bulk-feedback.error { color: #9a2f3b; }
.message-group .message-group-bar { flex-wrap: wrap; }
.message-group .message-group-bar .group-label { flex: 1 1 240px; }
.group-bulk-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.group-bulk-button { min-height: 28px; padding: 4px 10px; font-size: 12px; }
.message-select-control { color: #314b50; font-size: 11px; font-weight: 600; }
.message-select-control input { width: 14px; height: 14px; }
@media (max-width: 720px) {
  .bulk-action-bar { gap: 8px 12px; }
  .bulk-action-buttons { width: 100%; margin-left: 0; }
  .message-group .message-group-bar .group-label { flex-basis: 100%; }
}
</style>

<style src="./operations-refresh.css"></style>
