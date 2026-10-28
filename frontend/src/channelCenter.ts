export type ConnectionStatus =
  | 'not_connected'
  | 'external_authorization_required'
  | 'authorizing'
  | 'connected'
  | 'blocked'
  | 'error'
  | 'revoked'

export type ChannelRuntime = 'baileys_adapter' | 'google_oauth_pubsub' | 'outlook_mcp'

export type FakeChannel = {
  channel_type: 'whatsapp' | 'gmail' | 'outlook'
  provider: string
  display_name: string
  runtime: ChannelRuntime
  authorization_owner: string
  ingress_kind: string
  status: ConnectionStatus
  test_only: true
  message: string
}

export const fakeChannels: FakeChannel[] = [
  {
    channel_type: 'whatsapp',
    provider: 'whatsapp_web_baileys',
    display_name: 'WhatsApp',
    runtime: 'baileys_adapter',
    authorization_owner: 'account_owner_qr',
    ingress_kind: 'baileys_adapter',
    status: 'not_connected',
    test_only: true,
    message: 'TEST_ONLY：由 fake Baileys adapter 模拟短时 QR 绑定，不代表真实 WhatsApp 已连接。',
  },
  {
    channel_type: 'gmail',
    provider: 'gmail_api_pubsub',
    display_name: 'Gmail',
    runtime: 'google_oauth_pubsub',
    authorization_owner: 'google_oauth',
    ingress_kind: 'pubsub_webhook',
    status: 'external_authorization_required',
    test_only: true,
    message: 'TEST_ONLY：由 fake Google OAuth/Pub/Sub seam 模拟授权，不代表真实 Gmail 已连接。',
  },
  {
    channel_type: 'outlook',
    provider: 'outlook_mcp_graph',
    display_name: 'Outlook',
    runtime: 'outlook_mcp',
    authorization_owner: 'outlook_mcp_entra',
    ingress_kind: 'mcp',
    status: 'external_authorization_required',
    test_only: true,
    message: 'TEST_ONLY：由 fake Outlook MCP 模拟个人委派授权，不代表真实 Outlook 已连接。',
  },
]

export function statusLabel(status: ConnectionStatus): string {
  return {
    not_connected: '未连接',
    external_authorization_required: '等待外部授权',
    authorizing: '授权中',
    connected: '已连接（需区分真实/fake）',
    blocked: '平台阻塞',
    error: '连接错误',
    revoked: '已撤销',
  }[status]
}

export function canStartFakeAuthorization(channel: FakeChannel): boolean {
  return channel.status === 'not_connected'
    || channel.status === 'external_authorization_required'
    || channel.status === 'revoked'
    || channel.status === 'error'
}

export function fakeAuthorize(channel: FakeChannel): FakeChannel {
  if (!canStartFakeAuthorization(channel)) return channel
  return {
    ...channel,
    status: 'connected',
    message: `${channel.display_name} TEST_ONLY fake 连接成功；不代表真实 provider 已验收。`,
  }
}

export function fakeRevoke(channel: FakeChannel): FakeChannel {
  return {
    ...channel,
    status: 'revoked',
    message: `${channel.display_name} TEST_ONLY fake 连接已撤销；历史消息不因撤销而删除。`,
  }
}
