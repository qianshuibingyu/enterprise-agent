import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const app = await readFile(path.join(here, 'App.vue'), 'utf8')
const router = await readFile(path.join(here, 'router.ts'), 'utf8')
const backendRoutes = await readFile(path.join(here, '../../backend/app/business_routes.py'), 'utf8')
const backendAuthz = await readFile(path.join(here, '../../backend/app/authorization.py'), 'utf8')
const backendAuthRoutes = await readFile(path.join(here, '../../backend/app/auth_routes.py'), 'utf8')
const backendChannelRoutes = await readFile(path.join(here, '../../backend/app/channel_routes.py'), 'utf8')
const backendWhatsappRoutes = await readFile(path.join(here, '../../backend/app/whatsapp_routes.py'), 'utf8')
const backendCleanup = await readFile(path.join(here, '../../backend/app/channel_cleanup.py'), 'utf8')
const backendAuthzSource = backendAuthz
const inboxApi = await readFile(path.join(here, 'api/inbox.ts'), 'utf8')
const channelsApiSource = await readFile(path.join(here, 'api/channels.ts'), 'utf8')
const loginGate = await readFile(path.join(here, 'LoginGate.vue'), 'utf8')

test('workspace bootstraps identity before role-scoped requests', () => {
  assert.match(app, /if \(!currentUser\.value\) \{\s*const ok = await loadWorkspace\('base'\)/)
  assert.match(app, /const knownRole = \['admin', 'sales', 'engineering', 'procurement', 'production', 'staff', 'operations', 'ops'\]/)
})

test('admin is read-only for inquiries and never sees message operations', () => {
  assert.match(app, /role === 'admin'\s*\?\s*route\.value\.view === 'customers'/)
  assert.match(app, /v-if="!isAdmin && \(workspaceView === 'messages' \|\| workspaceView === 'customerMessages'\)"/)
  assert.doesNotMatch(app, /switchWorkspaceView\('messages'\)">公司消息/)
  assert.match(app, /section v-if="canOperateChannels \|\| isAdmin" class="detail-section action-section"/)
  assert.match(app, /管理员仅查看脱敏后的中文概述、渠道、时间与处理状态/)
  assert.match(app, /function adminMessageStatus\(linkedMessage: Inquiry\['messages'\]\[number\]\)/)
  assert.match(app, /安全正文展示成功 · 中文概要生成成功/)
  assert.match(app, /用户已撤回，无需生成中文概要。/)
  assert.match(app, /tone: 'success' as const/)
  assert.match(app, /tone: 'failure' as const/)
  assert.match(app, /is-admin-status-success \{ color: #18794e/)
  assert.match(app, /is-admin-status-failure \{ color: #b42318/)
  assert.match(app, /<p v-if="isAdmin" class="linked-message-safe-text is-hidden" :class="`is-admin-status-\$\{adminMessageStatus\(linkedMessage\)\.tone\}`">\{\{ adminMessageStatus\(linkedMessage\)\.text \}\}<\/p>/)
  assert.doesNotMatch(app, /v-else-if="isAdmin" class="linked-message-overview"/)
  assert.doesNotMatch(app, /中文概述：\{\{ linkedMessage\.overview_text/)
  assert.doesNotMatch(app, /已生成（管理员不可见）/)
  assert.match(app, /<small v-if="!isAdmin">发送人\/联系人：/)
  assert.match(backendAuthz, /def scoped_messages[\s\S]*?if user\.role == "admin":[\s\S]*?Message\.direction == "inbound"/)
  assert.match(backendAuthz, /def get_scoped_message[\s\S]*?query = scoped_messages\(user\)[\s\S]*?raise deny\(\)/)
  assert.match(backendRoutes, /def get_message\([\s\S]*?user\.role in \{"admin", "engineering", "procurement", "production"\}/)
  assert.match(backendRoutes, /def get_message_content\([\s\S]*?if user\.role == "admin":[\s\S]*?raise deny\(\)/)
  assert.match(backendRoutes, /def _message_view[\s\S]*?if user is not None and user\.role == "admin":[\s\S]*?redact_contact_text\([\s\S]*?attachments": \[\]/)
  assert.match(backendRoutes, /def _inquiry_view[\s\S]*?redact_contact_text\([\s\S]*?overview_text[\s\S]*?is_revoked_content\(message\.raw_content\)/)
  assert.match(backendRoutes, /"unlinked_messages": \[[\s\S]*?if user\.role == "admin" else \{[\s\S]*?"external_message_id"/)
  assert.match(backendRoutes, /"messages_needing_manual_review": \[[\s\S]*?if user\.role == "admin" else \{[\s\S]*?"external_message_id"/)
})

test('admin can regrant revoked channel history from the employee page', () => {
  assert.match(app, /listAdminChannelAccounts/)
  assert.match(app, /regrantChannelHistory/)
  assert.match(app, /渠道账号与历史访问/)
  assert.match(inboxApi, /\/auth\/admin\/channel-accounts\/\$\{accountId\}\/history-access/)
  assert.match(backendAuthRoutes, /def regrant_channel_history[\s\S]*?account\.status = "not_ready"/)
})

test('admin can hand admin-owned channel accounts to an operating employee', () => {
  assert.match(app, /transferChannelAccountsOwner\(selectedAdminChannelAccountIds\)/)
  assert.match(app, /transferTargetUserId/)
  assert.match(app, /adminChannelOwnerIsAdmin/)
  assert.match(app, /归属转移完成/)
  assert.match(app, /管理员名下/)
  assert.match(app, /v-for="employee in transferableEmployees"/)
  assert.match(inboxApi, /\/auth\/admin\/channel-accounts\/transfer-owner/)
  assert.match(inboxApi, /account_ids: accountIds, owner_user_id: ownerUserId/)
  assert.match(backendAuthRoutes, /def transfer_channel_accounts_owner/)
  assert.match(backendAuthRoutes, /def _rebind_channel_owner[\s\S]*?insert\(ChannelGrant\)/)
  assert.match(backendAuthRoutes, /if target\.role not in _OPERATING_ROLES:/)
})

test('administrators can connect channels but never see the message column', () => {
  assert.match(app, /v-if="canOperateChannels \|\| isAdmin" class="secondary" type="button" @click="profileOpen/)
  assert.match(app, /v-if="profileOpen && \(canOperateChannels \|\| isAdmin\)"/)
  assert.match(app, /渠道接入（管理员代连接）/)
  assert.match(app, /去转交账号/)
  assert.match(app, /needAccounts && \(canOperateChannels\.value \|\| isAdmin\.value\) \? channelsApi\.accounts\(\)/)
  assert.match(backendAuthzSource, /def channel_onboarding_account_ids[\s\S]*?if user\.role == "admin":/)
  assert.match(backendChannelRoutes, /def require_channel_preauthorization[\s\S]*?if user\.role == "admin":\s*return/)
  assert.match(backendChannelRoutes, /def require_channel_operator[\s\S]*?can_connect_channels\(user\)/)
  assert.match(backendAuthz, /def scoped_messages[\s\S]*?if user\.role == "admin":[\s\S]*?Message\.direction == "inbound"/)
  assert.match(backendRoutes, /def get_message_content\([\s\S]*?if user\.role == "admin":[\s\S]*?raise deny\(\)/)
})

test('revoking a connection cleans up empty shells instead of leaving zombies', () => {
  assert.match(backendCleanup, /def purge_channel_shell[\s\S]*?delete\(ChannelAccount\)/)
  assert.match(backendChannelRoutes, /def revoke_channel[\s\S]*?purge_channel_shell\(db, account\)/)
  assert.match(backendWhatsappRoutes, /def disconnect[\s\S]*?purge_channel_shell\(db, account\)/)
  assert.match(backendAuthRoutes, /retired_shells/)
  assert.match(inboxApi, /retired_shells/)
  assert.match(app, /已彻底清除/)
})

test('administrator transfer is exposed without inquiry-state mutation', () => {
  assert.match(app, /isAdmin && selectedInquiry\.status === 'assigned'/)
  assert.match(app, /isAdmin\.value \? '客户链路已改派。'/)
  assert.match(backendRoutes, /def list_channel_accounts[\s\S]*?if user\.role != "admin" and not can_operate_channels\(user\):\s*return \[\]/)
  assert.match(backendRoutes, /def list_inquiry_transfer_targets[\s\S]*?if \([\s\S]*?user\.role != "admin"[\s\S]*?not can_operate_channels\(user\) or user\.manager_overlay_enabled[\s\S]*?\):\s*raise deny\(\)/)
})

test('restricted roles cannot use operational views or channel account scope', () => {
  assert.match(app, /\['sales', 'engineering', 'procurement', 'production'\]/)
  assert.match(router, /const view = \['messages', 'review', 'customers', 'customerMessages'\]\.includes\(page\) \? page as WorkspaceView : parsedView/)
})

test('department roles require a department when creating employees', () => {
  assert.match(app, /const department = employeeForm\.value\.department\.trim\(\)[\s\S]*?if \(!department\)[\s\S]*?所有账号都必须填写所属部门/)
  assert.match(app, /const department = user\.department \|\| ''[\s\S]*?if \(!department\)[\s\S]*?所有账号都必须填写所属部门/)
})

test('backend scopes channel access to operating roles and limits admin content to snapshot', () => {
  assert.match(backendAuthz, /if user\.role not in \{"staff", "operations", "ops"\}:\s*return select\(ChannelAccount\.id\)\.where\(False\)/)
  assert.match(backendRoutes, /allow_provider_refetch=user\.role in \{"staff", "operations", "ops"\}/)
  assert.match(backendRoutes, /if user\.role == "admin":\s*query = query\.where\(Message\.direction == "inbound"\)/)
})

test('empty 204 responses are not parsed as JSON and logout forces a document reload', () => {
  assert.match(inboxApi, /const text = await response\.text\(\)/)
  assert.match(inboxApi, /text \? JSON\.parse\(text\) : undefined/)
  assert.match(channelsApiSource, /text \? JSON\.parse\(text\) : undefined/)
  assert.match(loginGate, /const text = await response\.text\(\)/)
  assert.match(app, /window\.location\.reload\(\)/)
  assert.doesNotMatch(app, /location\.assign\(window\.location\.pathname \+ window\.location\.search\)/)
})

test('channel authorization uses the created account instead of gating on a workspace refetch', () => {
  assert.match(app, /const created = await channelsApi\.createGmailAccount/)
  assert.match(app, /const created = await channelsApi\.createOutlookAccount/)
  assert.doesNotMatch(app, /Gmail 账号已初始化，但工作台刷新失败/)
  assert.match(app, /accounts\.value = \[\s*\.\.\.accounts\.value\.filter\(\(item\) => item\.id !== created\.id/)
})

test('channel preauthorization uses explicit grant and revoke actions with feedback', () => {
  assert.match(app, /employeeChannelFeedback/)
  assert.match(app, /已\$\{grant \? '授予' : '撤销'\}/)
  assert.match(app, /class="ea-channel-action ea-channel-revoke"[\s\S]*changeEmployeeChannel\(employee, channel.key, false\)/)
  assert.match(app, /class="ea-channel-action" type="button"[\s\S]*changeEmployeeChannel\(employee, channel.key, true\)/)
  assert.doesNotMatch(app, /class="ea-toggle"[^\n]*@click="changeEmployeeChannel/)
})

test('employee creation reports success and avoids native validation bubbles', () => {
  assert.match(app, /class="ea-form" novalidate/)
  assert.match(app, /employeeCreateFeedback/)
  assert.match(app, /'创建成功'/)
  assert.match(app, /:disabled="employeeCreating"/)
})

test('first-login password form asks for a new password and its confirmation only', () => {
  assert.doesNotMatch(loginGate, /currentPassword|当前临时密码|current_password/)
  assert.match(loginGate, /确认新密码/)
  assert.match(loginGate, /new_password: newPassword\.value/)
  assert.match(loginGate, /两次输入的新密码不一致/)
})

test('refetch diagnostics separate "not linked yet" from a real failure', () => {
  // The amber "实时回源不可用" box used to appear for an unpaired WhatsApp
  // device and for a blocked egress network alike, which read as a bug.
  assert.match(app, /function refetchTone\(check: RefetchCheck \| undefined\)/)
  assert.match(app, /return check\.severity === 'not_ready' \? 'info' : 'warn'/)
  assert.match(app, /session_offline: 'WhatsApp 设备尚未关联'/)
  assert.match(app, /失败域名 \$\{check\.network\.host\}/)
  assert.match(app, /已入库的历史消息仍可正常查看与处理/)
  assert.match(inboxApi, /severity: 'ok' \| 'action_required' \| 'not_ready'/)
  assert.match(backendRoutes, /NOT_READY_FAILURES = \{"session_offline", "unsupported_channel"\}/)
  assert.match(backendRoutes, /"history_available": history_available/)
})

test('provider egress failures are classified and can be proxied', async () => {
  assert.match(backendRoutes, /from app\.provider_transport import classify_network_failure, provider_proxy_summary/)
  assert.match(backendRoutes, /record\("出站网络配置", True, provider_proxy_summary\(\)\)/)
  const transport = await readFile(path.join(here, '../../backend/app/provider_transport.py'), 'utf8')
  assert.match(transport, /PROVIDER_HTTPS_PROXY/)
  assert.match(transport, /def classify_network_failure/)
  assert.match(transport, /def provider_http_client/)
  const outlookRoutes = await readFile(path.join(here, '../../backend/app/outlook_routes.py'), 'utf8')
  assert.match(outlookRoutes, /except \(httpx\.HTTPError, OSError\) as exc:[\s\S]*?network_failure_message/)
})

test('message content blocks stack instead of overlapping', async () => {
  // `.message-content-view` is itself a grid; an unscoped `.message-row p`
  // rule forced every paragraph into row 1 so the preview and the two source
  // notes painted on top of each other.
  assert.match(app, /\.message-row > p \{ grid-column: 2; grid-row: 1;/)
  assert.doesNotMatch(app, /\.message-row p \{ grid-column: 2; grid-row: 1;/)
  const refreshCss = await readFile(path.join(here, 'operations-refresh.css'), 'utf8')
  assert.match(refreshCss, /\.message-content-view > \* \{ grid-column: 1; grid-row: auto;/)
  assert.match(refreshCss, /\.message-row > \.message-preview \{ display: -webkit-box; grid-column: 2;/)
  // The label must live outside the line-clamped paragraph, otherwise it eats
  // one of the 8 clamped lines and clips the last line in half.
  assert.match(app, /<span class="content-label">\{\{ isMessageExpanded\(message\.id\) \? '完整原文' : '安全原文预览' \}\}<\/span>/)
})

test('expanding a message replaces the clamped preview instead of duplicating it', () => {
  // Regression: the clamped preview rendered unconditionally and the full text
  // was appended as an extra paragraph, so 展开全文 showed the body twice.
  assert.match(app, /<p v-if="isMessageExpanded\(message\.id\)" class="message-full-content">/)
  assert.match(app, /<p v-else class="message-original-preview">/)
  assert.doesNotMatch(app, /fullMessageContentIds\.has\(message\.id\)" class="message-full-content">\s*\{\{ messageContentFor\(message\.id\)\?\.full_text \}\}/)
  // The "8 行" hint only applies to the collapsed state.
  assert.match(app, /v-if="messageContentFor\(message\.id\)\?\.can_expand && !isMessageExpanded\(message\.id\)" class="content-clamp-hint"/)
})

test('a logged-out WhatsApp device can be re-linked instead of staying revoked', async () => {
  const bridge = await readFile(path.join(here, '../../whatsapp-bridge/src/index.ts'), 'utf8')
  assert.match(bridge, /async function clearStoredAuth/)
  assert.match(bridge, /options: \{ wipeAuth\?: boolean \} = \{\}/)
  assert.match(bridge, /runtime = await resetRuntime\(id, \{ wipeAuth: true \}\)/)
  assert.match(backendWhatsappRoutes, /account\.status = "awaiting_authorization"/)
})

test('deactivated employees are archived and cannot be reconfigured', () => {
  // 停用账号混在有效员工表里、还能继续改部门/授权，读起来像配置没生效。
  assert.match(app, /if \(!item\.is_active\) return false/)
  assert.match(app, /const inactiveEmployees = computed\(\(\) => employeeRecords\.value\.filter\(\(item\) => !item\.is_active\)\)/)
  // 归档与筛选完全分开：状态筛选里不再出现「已停用」，否则选了只剩空表。
  assert.doesNotMatch(app, /<option value="inactive">已停用<\/option>/)
  assert.match(app, /v-for="employee in activeEmployees"/)
  assert.match(app, /v-if="inactiveEmployees\.length" class="ea-card ea-archive-card"/)
  assert.match(app, /已停用的员工（\{\{ inactiveEmployees\.length \}\}）/)
  assert.match(app, /v-if="expandedEmployeeId === employee\.id && employee\.is_active"/)
  assert.match(app, /employeeStatusFilter\.value === 'pending'/)
  assert.match(app, /async function reactivateEmployee\(user: EmployeeRecord\)/)
  assert.match(inboxApi, /reactivateEmployee: \(userId: number, csrfToken: string\) =>[\s\S]*?\/reactivate/)
  // 后端同口径：停用账号的岗位/部门/授权一律冻结，并支持启用后恢复配置。
  assert.match(backendAuthRoutes, /def _require_active_employee[\s\S]*?员工已停用，请先启用账号再修改授权/)
  assert.match(backendAuthRoutes, /def reactivate_employee[\s\S]*?user\.is_active = True/)
})

test('employee name is a first-class field and the inquiry owner shows the employee name', () => {
  assert.match(app, /员工姓名 <em>必填<\/em>/)
  assert.match(app, /employeeForm\.full_name/)
  assert.match(app, /function employeeDisplayName\(employee: EmployeeRecord\)/)
  assert.match(app, /employee\.full_name \|\| employee\.username/)
  assert.match(app, /placeholder="姓名、用户名或部门关键字"/)
  // 负责人展示员工姓名，账号只作副标识；之前显示 sales1 让人以为是账号名。
  assert.match(app, /selectedInquiry\.assigned_sales_name \|\| selectedInquiry\.assigned_sales_username/)
  assert.match(app, /class="fact-account">账号 \{\{ selectedInquiry\.assigned_sales_username \}\}/)
  // 展开授权设置后仍要能看到登录账号：姓名是显示名，账户名才是唯一登录凭据。
  assert.match(app, /登录账号 <code>\{\{ employee\.username \}\}<\/code>/)
  assert.match(app, /确认停用 \{\{ employeeDisplayName\(employee\) \}\}（\{\{ employee\.username \}\}）/)
  // 已有账号可以随时在管理员处改名（纠正错别字），且改名不应连带清授权、踢下线。
  assert.match(app, /function changeEmployeeFullName\(user: EmployeeRecord, event: Event\)/)
  assert.match(backendAuthRoutes, /identity_changed = user\.role != mapped_role or user\.department != department[\s\S]*?authorization_changed = identity_changed or manager_overlay_enabled != user\.manager_overlay_enabled/)
  assert.match(backendAuthRoutes, /keep_session_id=admin_session\.id if user\.id == admin\.id else None/)
  assert.match(backendRoutes, /"assigned_sales_name": assignee\.get\("name"\)/)
  assert.match(backendRoutes, /"assigned_sales_username": assignee\.get\("username"\)/)
  // 改派下拉同样按姓名找人，同名时再用账号区分。
  assert.match(app, /function transferTargetLabel\(target: TransferTarget\)/)
  assert.match(backendRoutes, /"full_name": target\.full_name/)
})

test('password reset reports its result inline, and stale errors auto-dismiss', () => {
  // 点「重置密码」只在顶部红字里报错，视线在按钮上根本看不到；成功更是完全无声。
  assert.match(app, /function flashEmployeeReset\(userId: number, kind: 'success' \| 'error', text: string\)/)
  assert.match(app, /employeeResetFeedback && employeeResetFeedback\.userId === employee\.id/)
  assert.match(app, /已重置 \$\{employeeDisplayName\(user\)\}/)
  assert.match(app, /employeeResetPendingId === employee\.id \? '重置中…' : '重置密码'/)
  // 员工页错误是一次性反馈：操作成功或切到别的员工就应消失，不能一直贴在面板上。
  assert.match(app, /watch\(employeeError, \(message\) => \{/)
  assert.match(app, /if \(expandedEmployeeId\.value !== userId\) employeeError\.value = ''/)
  assert.match(app, /employeeError\.value = ''\s+try \{\s+const csrf = await inboxApi\.getCsrf\(\)\s+await inboxApi\.mapEmployee/)
})

test('customer message opens the sanitized text in place', () => {
  // 「查看客户消息」原本跳整页消息详情，还要再点一次「查看原文」；业务员在链路里只想看这条消息本身。
  assert.match(app, /async function openCustomerMessage\(messageId: number\)/)
  assert.match(app, /await inboxApi\.getMessageContent\(messageId\)/)
  assert.match(app, /安全文本（清洗后的原文）/)
  assert.match(app, /class="customer-message-text"/)
  assert.match(app, /渠道实时回读不可用/)
  assert.match(app, /async function copyCustomerMessage\(\)/)
  // 不得再退回到"跳到消息详情页"的旧实现。
  assert.doesNotMatch(app, /function openCustomerMessage\(messageId: number\) \{\s+navigate\(/)
})

test('inquiry detail names the transferring operator separately from the owner', () => {
  // 负责人是业务员，转交人是点「分配」的运营；两者不能混成一个字段。
  assert.match(app, /<span>转交人<\/span>/)
  assert.match(app, /selectedInquiry\.transferred_by_name \|\| selectedInquiry\.transferred_by_username \|\| '未转交'/)
  assert.match(app, /selectedInquiry\.transferred_at/)
  assert.match(backendRoutes, /def _transfer_labels\(db: Session, inquiries: list\[Inquiry\]\)/)
  assert.match(backendRoutes, /InquiryEvent\.event_type == "inquiry_transferred"/)
  assert.match(backendRoutes, /"transferred_by_name": transfer\.get\("name"\)/)
  assert.match(backendRoutes, /"transferred_at": transfer\.get\("at"\)/)
})

test('customer chain shows sanitized original first and the Chinese summary as a footnote', () => {
  // 用户反馈：链路里第一行就是中文概述，看不到客户原本说了什么。
  assert.match(app, /class="linked-message-safe-text"/)
  assert.match(app, /linkedMessage\.safe_text/)
  assert.match(app, /中文概述：\{\{ linkedOverviewText\(linkedMessage\)/)
  assert.match(app, /以运营同事入站时清洗后的安全原文为主/)
  const safeTextAt = app.indexOf('class="linked-message-safe-text"')
  const overviewAt = app.indexOf('class="linked-message-overview"')
  assert.ok(safeTextAt > 0 && overviewAt > safeTextAt, '安全原文必须排在中文概述之前')
  // 旧的大绿框（10px 内边距 + 左边框）不再作为主展示。
  assert.doesNotMatch(app, /\.linked-message-overview \{ margin: 8px 0; padding: 10px 12px/)
  // 消息列表与消息详情同样以原文为主，概述降为小字，且两段不能压进同一个网格格。
  assert.match(app, /class="message-brief"/)
  assert.match(app, /\.message-row > \.message-brief \{ grid-column: 2; grid-row: 1;/)
  assert.match(app, /<h3>安全原文（清洗后）<\/h3>/)
  assert.match(app, /<h3>中文概述（辅助）<\/h3>/)
  assert.match(inboxApi, /safe_text: string \| null/)
  // 后端只给非管理员下发清洗后的正文。
  assert.match(backendRoutes, /\*\*_linked_message_content_view\(message, user\)/)
  assert.match(backendRoutes, /"content_state": CONTENT_STATE_HIDDEN/)
})

test('a revoked WhatsApp message is labelled 已撤回, never 待处理 / 消息为空', () => {
  assert.match(app, /return message\.content_state === 'revoked' \|\| message\.safe_content_status === 'revoked'[\s\S]*?\? '已撤回'/)
  assert.match(app, /messageStatusLabel\(linkedMessage\)/)
  assert.match(app, /linkedMessage\.content_state !== 'revoked'/)
  assert.match(app, /用户已撤回，无需生成中文概要。/)
  assert.match(app, /overview_status === 'not_applicable_revoked'/)
  assert.match(app, /customerMessageRevoked/)
  assert.match(app, /customer-message-revoked-tag/)
  // 撤回消息不提供「标记已处理 / 重新生成概要」，但必须保留「忽略」。
  assert.match(app, /message\.content_state !== 'revoked' && \(message\.overview/)
  assert.match(app, /message\.content_state !== 'revoked' && \(workspaceView === 'messages'/)
  assert.match(app, /<!-- 撤回消息也必须能「忽略」：[\s\S]*?<button v-if="!isAdmin && \(workspaceView === 'messages' \|\| workspaceView === 'customerMessages'\)"/)
  assert.match(backendRoutes, /客户已撤回的消息不能标记已处理，可选择忽略/)
  assert.match(inboxApi, /content_state: 'ready' \| 'revoked'/)
  assert.match(backendRoutes, /"content_state": content\["content_state"\]/)
})

test('a message with a recoverable original is no longer labelled 已撤回', () => {
  // 截图回归：弹窗显示完整西语原文，列表却写「已撤回 / 原文不再可用」。
  assert.match(backendRoutes, /def _repair_message_body/)
  assert.match(backendRoutes, /def _heal_recoverable_messages/)
  assert.match(backendRoutes, /needs_body_repair\(getattr\(message, "raw_content", ""\), raw_content\)/)
  assert.match(backendRoutes, /_heal_recoverable_messages\(db, user, messages\)/)
  assert.match(app, /applyRecoveredMessageBody\(messageId, content\)/)
  assert.match(app, /客户已撤回，原文不可恢复；不能标记已处理，但仍可在消息列表点「忽略」清理。/)
})

test('a whole conversation can be handled in one action instead of row by row', () => {
  // 用户反馈：同一群聊会话 5 条消息，却只能在每条上分别点「系统外已处理」。
  assert.match(app, /runBulkMessageAction\('processed', groupSelectableIds\(group\)\)/)
  assert.match(app, /runBulkMessageAction\('ignored', groupSelectableIds\(group\)\)/)
  assert.match(app, /全选本页 \{\{ selectableMessageIds\.length \}\} 条/)
  assert.match(app, /全选本组 \{\{ groupSelectableIds\(group\)\.length \}\} 条/)
  assert.match(app, /批量标记已处理/)
  assert.match(app, /批量忽略/)
  assert.doesNotMatch(app, /<p class="eyebrow">逐条处理<\/p>/)
  // 已终态消息不进入批量选择；撤回消息仍需能被批量忽略。
  assert.match(app, /message\.handling_status === 'pending'\s*&& message\.direction === 'inbound'/)
  assert.match(app, /撤回消息没有可处理的正文，不能批量「标记已处理」；但可以批量「忽略」/)
  assert.match(app, /messages\.value\.find\(\(item\) => item\.id === id\)\?\.content_state !== 'revoked'/)
  // 归链消息由询盘整组处理，成功后同链路兄弟消息一起移出待办。
  assert.match(app, /updatedInquiryIds\.has\(message\.inquiry_id\)/)
  assert.match(inboxApi, /bulkUpdateMessageHandling: \(messageIds: number\[\]/)
  assert.match(inboxApi, /export type MessageBulkActionResult/)
  assert.match(backendRoutes, /@router\.post\("\/messages\/bulk-action"\)/)
  assert.match(backendRoutes, /is_revoked_content\(message\.raw_content\)/)
})
