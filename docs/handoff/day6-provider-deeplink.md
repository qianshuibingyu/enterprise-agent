# 渠道深链路由排查与修复（Outlook / WhatsApp）

> 记录 2026-11-05 对“点击消息里的『去渠道处理』总是跳到授权登录页、且进不到具体邮件/聊天”的链路排查。
> 只记录非敏感证据：不包含 token、client secret、refresh token、邮件正文。

## 1. 现象

- Outlook 已真实接入，账号状态 `verified_inbound`。
- 点击任一 Outlook 消息的「去渠道处理」→ 浏览器打开 Microsoft 登录/选账号页面，每条消息都要重新登录一次。
- Outlook 与 WhatsApp 都无法定位到“收到的那封邮件 / 那个聊天”。

## 2. 排查结论：不是服务器问题，是业务逻辑 + 数据问题

### 2.1 服务端链路本身是通的

| 检查项 | 结果 |
| --- | --- |
| `channel_accounts#3` Outlook refresh token 密文 | 存在 |
| 账号状态 | `verified_inbound` |
| `GET /api/messages/{id}/provider-action` | 全部 200，无 401/403 |
| 会话 Cookie / CSRF | 正常，点击不触发本项目登录页 |

本项目自己的 OAuth 回调也确实把授权写进了数据库（`credential_reference=db-encrypted:outlook-refresh-token`），
所以“每次都要重新授权”**不是**本项目没保存登录信息。

### 2.2 真正的根因链

```text
Graph 消息里的 webLink 没有被持久化（provider_web_link 全为 NULL）
        ↓
/api/messages/{id}/provider-action 走 open_inbox 兜底分支
        ↓
兜底地址写死为 https://outlook.office.com/mail/inbox
        ↓
该账号是个人 Microsoft 账号（wafuture…@outlook.com，Graph id 为 16 位 hex）
outlook.office.com 只服务工作/学校邮箱
        ↓
每次都落到 Microsoft 登录 / 选择账号页 → 表现为"每条消息都要重新授权"
```

数据库证据（修复前）：

```text
channel_accounts#3: external_account_id=1ee714b1593489d8（个人 MSA id，非 GUID）
messages where channel_account_id=3: 10 条，provider_web_link 全部为 NULL
```

Graph 侧证据（用已存的 refresh token 直接查询）：

```text
me.id      = 1ee714b1593489d8
me.mail    = wafutechnology@outlook.com
webLink    = https://outlook.live.com/owa/?ItemID=…   ← 主机是 outlook.live.com
```

**webLink 一直是有的**，只是没被存下来，所以业务代码永远只能走兜底。

### 2.3 为什么 webLink 一直存不下来

1. 这些行是在 `0011_message_provider_web_link` 迁移之前入库的。
2. 回填逻辑只挂在“重复入库”分支，但读取策略是 `isRead eq false`（只读未读）。
3. 用户点开邮件后，这些邮件全部变成已读，`list_emails` 再也返回不到它们。
   → 一次都回填不上，形成自锁。

### 2.4 WhatsApp 的根因

- 现有消息的联系方式是 `32771439386851@lid`、`198479750152321@lid`（WhatsApp 新的隐私 LID）。
- `_whatsapp_phone()` 只接受 `@s.whatsapp.net` 的传统 JID，LID 一律返回 None。
- 兜底分支返回 `whatsapp://`（只打开 App 根页面），所以永远进不到聊天框。
- bridge 端 `customerContact` 也只在 `@s.whatsapp.net` 时赋值，LID 消息进来就是空。

## 3. 修复内容

### 后端

- `app/provider_links.py`（新增）：Outlook 链接白名单 + 个人/工作邮箱判定 + 正确兜底主机。
- `business_routes.get_message_provider_action()`
  - 有可信 `provider_web_link` → 直接 `open_message`（真实邮件详情页）。
  - 没有 → 用账号已存 refresh token 调 Graph `/me/messages/{id}?$select=webLink`
    现场补链并落库（每条只补一次，之后走本地）。
  - 仍失败 → 兜底到**账号对应**的邮箱主机（个人 `outlook.live.com` / 工作 `outlook.office.com`），
    不再把个人账号送到工作邮箱域名。
  - 响应新增 `web_url`：App 协议（`whatsapp://`）打不开时的网页版兜底入口。
- `outlook_graph.message_web_link()`：Graph 是链接唯一权威来源，不臆造 URL 形态。
- `outlook_routes.list_outlook_messages()`：每次主动读取后，对有链接缺口的行做
  **限量 20 条**的补链（`links_repaired` 返回给前端）。
  保留 `isRead eq false` 的入队语义，避免把整箱历史邮件灌进处理队列。
- `whatsapp_adapter.resolve_lid_phone()` + `scripts/backfill_whatsapp_contacts.py`：
  历史 LID 行通过 bridge 的 LID 映射回填真实手机号。

### WhatsApp bridge

- `whatsapp-message.ts`：新增 `phoneFromWhatsAppJid()` / `customerPhoneForKey()`，
  优先 `remoteJid` → `remoteJidAlt` → `participantAlt`；群聊（`@g.us`）始终不产出手机号。
- `event-handler.ts` + `index.ts`：LID 直聊时用 `signalRepository.lidMapping.getPNForLID()` 解析，
  解析失败不影响消息入库。
- 新增 `POST /internal/whatsapp/accounts/:id/lid-phone`（Bearer 鉴权）。

### 前端

- `App.vue openMessageProvider()`：
  - `http(s)` 链接仍走预开窗口；
  - `whatsapp://` 这类 App 协议改为锚点触发，不再留下空白标签页；
  - 服务端给了 `web_url` 时，反馈区展示「改用 WhatsApp 网页版打开」兜底链接。

## 4. 线上验证（2026-11-05）

```text
GET /api/messages/129/provider-action
→ open_message  https://outlook.live.com/owa/?ItemID=…&exvsurl=1&viewmodel=ReadMessageItem

GET /api/messages/156/provider-action
→ open_chat     whatsapp://send?phone=8615817317518   web=https://wa.me/8615817317518

GET /api/messages/159/provider-action
→ open_chat     whatsapp://send?phone=15557038852     web=https://wa.me/15557038852

GET /api/messages/160/provider-action（群聊）
→ open_inbox    whatsapp://                           web=https://web.whatsapp.com/

GET /api/integrations/outlook/accounts/3/messages
→ {"total":1,"created":0,"duplicates":1,"links_repaired":6}

messages where channel_account_id=3: null_links=0 / total=10
```

## 5. 已知边界

- WhatsApp **群聊**没有可用的手机号，WhatsApp 也不支持用 JID 直接打开群聊；
  只能打开 WhatsApp 根页面（或网页版）。要精确打开群聊需要群邀请链接，当前数据里没有。
- LID 映射来自已关联设备，bridge 掉线或未同步的联系人解析不出来，此时回落根页面。
- Outlook 网页是否需要再次登录取决于浏览器里 outlook.live.com 的会话；
  本项目只保证送到**正确的邮件详情地址**，不能代替 Microsoft 的登录态。
- `isRead eq false` 仍是入队口径：已读邮件不会被重新入库，只做链接补链。
