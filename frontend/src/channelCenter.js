export const fakeChannels = [
  {
    channel_type: 'whatsapp',
    provider: 'whatsapp_web_baileys',
    display_name: 'WhatsApp',
    runtime: 'baileys_adapter',
    authorization_owner: 'account_owner_qr',
    ingress_kind: 'baileys_adapter',
    status: 'not_ready',
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
    status: 'awaiting_authorization',
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
    status: 'awaiting_authorization',
    test_only: true,
    message: 'TEST_ONLY：由 fake Outlook MCP 模拟个人委派授权，不代表真实 Outlook 已连接。',
  },
]

export function statusLabel(status) {
  return {
    not_ready: '尚未准备好',
    awaiting_authorization: '等待官方授权',
    connected_pending_inbound: '已授权，等待真实入站',
    verified_inbound: '真实入站已验收',
    blocked: '平台阻塞',
    system_error: '系统错误',
    revoked: '已撤销',
  }[status]
}

export function canStartFakeAuthorization(channel) {
  return channel.status === 'not_ready'
    || channel.status === 'awaiting_authorization'
    || channel.status === 'revoked'
    || channel.status === 'system_error'
}

export function fakeAuthorize(channel) {
  if (!canStartFakeAuthorization(channel)) return channel
  return {
    ...channel,
    status: 'connected_pending_inbound',
    message: `${channel.display_name} TEST_ONLY fake 已授权；不代表真实 provider 已验收。`,
  }
}

export function fakeRevoke(channel) {
  return {
    ...channel,
    status: 'revoked',
    message: `${channel.display_name} TEST_ONLY fake 连接已撤销；历史消息不因撤销而删除。`,
  }
}
