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
import {
  fakeAuthorize,
  fakeChannels,
  fakeRevoke,
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
const channels = ref<FakeChannel[]>(fakeChannels.map((channel) => ({ ...channel })))
const error = ref('')
const actionMessage = ref('')
const actionError = ref('')
const handlingSubmitting = ref(false)
const unauthorized = ref(false)
const gmailMessage = ref('')
const gmailError = ref('')

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

async function loadWorkspace() {
  loading.value = true
  error.value = ''
  actionError.value = ''
  unauthorized.value = false

  try {
    const [nextAccounts, nextMessages, nextInquiries, nextAnalysis, nextTargets] = await Promise.all([
      inboxApi.getAccounts(),
      inboxApi.getMessages(),
      inboxApi.getInquiries(),
      inboxApi.getInternalAnalysis(),
      inboxApi.getTransferTargets().catch((cause) => {
        if (cause instanceof ApiError && cause.status === 403) return []
        throw cause
      }),
    ])
    accounts.value = nextAccounts
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

async function startGmailAuthorization() {
  const account = accounts.value.find((item) => item.channel_type === 'gmail')
  if (!account) {
    gmailError.value = '当前授权范围没有 Gmail 账号。'
    gmailMessage.value = ''
    return
  }
  gmailError.value = ''
  gmailMessage.value = ''
  try {
    const csrf = await inboxApi.getCsrf()
    const result = await channelsApi.startGmailAuthorization(account.id, csrf.csrf_token)
    window.location.assign(result.authorization_url)
  } catch (cause) {
    if (cause instanceof Error) gmailError.value = cause.message
    else gmailError.value = 'Gmail 授权启动失败。'
  }
}

function readGmailCallbackState() {
  const params = new URLSearchParams(window.location.search)
  const state = params.get('gmail')
  if (state === 'connected') gmailMessage.value = 'Gmail 授权完成，连接状态正在刷新。'
  if (state === 'error') gmailError.value = params.get('message') || 'Gmail 授权失败。'
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
    outlookMessage.value = `Outlook 主动读取完成：新增或确认 ${result.length} 条消息。`
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
        <p class="eyebrow">运营工作台</p>
        <h1>客户链路</h1>
      </div>
      <button class="secondary" type="button" @click="loadWorkspace">刷新</button>
    </header>

    <p class="test-badge">TEST_ONLY / fixture 数据视图：不代表真实 provider 已连接或真实消息已验收</p>

    <section class="channel-center panel">
      <div class="panel-heading">
        <div>
          <p class="eyebrow">接入渠道</p>
          <h2>Provider-neutral 连接中心</h2>
        </div>
        <span class="test-chip">TEST_ONLY</span>
      </div>
      <div class="channel-grid">
        <article v-for="channel in channels" :key="channel.channel_type" class="channel-card">
          <div class="row-topline">
            <strong>{{ channel.display_name }}</strong>
            <span class="status">{{ channelStatusLabel(channel.status) }}</span>
          </div>
          <p class="channel-provider">{{ channel.provider }} · {{ channel.runtime }}</p>
          <p class="muted">{{ channel.message }}</p>
          <div class="channel-actions">
            <button
              class="secondary"
              type="button"
              :disabled="channel.status === 'connected' || channel.status === 'blocked'"
              @click="authorizeFakeChannel(channel.channel_type)"
            >
              Fake 授权
            </button>
            <button
              class="link-button"
              type="button"
              :disabled="channel.status === 'revoked' || channel.status === 'not_connected'"
              @click="revokeFakeChannel(channel.channel_type)"
            >
              撤销 fake
            </button>
          </div>
        </article>
      </div>
      <p v-if="gmailMessage" class="action-success">{{ gmailMessage }}</p>
      <p v-if="gmailError" class="action-error">{{ gmailError }}</p>
      <button class="secondary" type="button" @click="startGmailAuthorization">
        连接 Gmail（Google OAuth）
      </button>
      <p v-if="outlookMessage" class="action-success">{{ outlookMessage }}</p>
      <p v-if="outlookError" class="action-error">{{ outlookError }}</p>
      <button class="secondary" type="button" :disabled="outlookReading" @click="readOutlookMessages">
        {{ outlookReading ? '读取 Outlook 中…' : '主动读取 Outlook 邮件' }}
      </button>
      <p class="muted">真实 WhatsApp QR、Google OAuth 和 Outlook MCP 授权不由 fake fixture 执行；长期 token、QR 和 auth state 不进入浏览器存储。</p>
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
          <span class="preview">{{ inquiry.raw_message }}</span>
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
            <p>{{ message.raw_content }}</p>
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
            <div><dt>原始内容</dt><dd>{{ selectedInquiry.raw_message }}</dd></div>
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
.eyebrow { margin: 0 0 6px; color: #6c7890; font-size: 12px; font-weight: 700; letter-spacing: .12em; text-transform: uppercase; }
h1, h2, h3, p { margin-top: 0; }
h1 { margin-bottom: 0; font-size: clamp(28px, 4vw, 42px); }
h2 { margin-bottom: 0; font-size: 20px; }
h3 { margin-bottom: 14px; font-size: 15px; }
.test-badge, .test-chip { color: #7a4d00; background: #fff1c7; border: 1px solid #f0d789; }
.test-badge { padding: 10px 14px; border-radius: 10px; font-size: 13px; }
.test-chip { padding: 5px 8px; border-radius: 999px; font-size: 11px; font-weight: 800; }
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
.empty-state { display: grid; min-height: 280px; place-content: center; text-align: center; }
@media (max-width: 800px) { .channel-grid { grid-template-columns: 1fr; } .analysis-strip { grid-template-columns: repeat(2, 1fr); } .content-grid { grid-template-columns: 1fr; } .facts-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 480px) { .analysis-strip { grid-template-columns: 1fr; } .transfer-form { grid-template-columns: 1fr; } .transfer-form .primary { grid-column: 1; } }
@media (max-width: 480px) { .workspace { width: min(100% - 24px, 1240px); padding-top: 22px; } .detail-panel { padding: 20px; } .facts-grid { grid-template-columns: 1fr; } .attachment-list li { display: grid; gap: 5px; } }
</style>
