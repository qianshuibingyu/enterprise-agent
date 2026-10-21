# Day 3 渠道官方资料核验（连接中心设计依据）

> 状态：文档资料初步核对；不是账号资格、授权、实际接通或运行验收。核对日期：2026-10-21。
>
> 范围：当前阶段只设计后续由客户在实际使用时完成的渠道连接入口、分渠道操作指南和连接状态；不在开发时预先接入客户账号，不预置/模拟“已连接”，也不要求客户向网页粘贴长期 Token。此记录不代表本项目 OAuth 回调、密钥加密、渠道适配器或真实消息收发已实现。

## 官方资料与可据此采用的设计边界

### Gmail

- [Gmail API OAuth scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)：Google 按 scope 列明授权范围和敏感级别；`gmail.send` 用于发送，`gmail.readonly`、`gmail.modify` 属 restricted scopes。产品应申请功能必需的最窄 scope；受限 scope 可能要求 Google 验证，在存储/传输受限 scope 数据时可能要求安全评估。
- [OAuth 2.0 for Web Server Applications](https://developers.google.com/identity/protocols/oauth2/web-server)：服务端 web app OAuth 适用于能保护机密信息并维护状态的应用。若要离线访问，可请求 offline access 并安全保存 refresh token；授权回调应验证请求 `state` 与发起值相符。
- 设计影响：授权码交换、refresh token 保管和 Gmail API 调用留在服务端；浏览器只发起授权并展示非敏感状态。产品方必须预先注册/配置自己的 Google OAuth 应用及 redirect URI，客户授权自己的 mailbox 不替代产品 OAuth 应用配置或可能的 Google 验证。

### Outlook / Microsoft Graph

- [Microsoft Graph permissions reference](https://learn.microsoft.com/en-us/graph/permissions-reference)：Graph 权限分 delegated 与 application；delegated `Mail.Read`/`Mail.Send` 在登录用户上下文中授权，application 权限可以在无登录用户时访问 mailbox，权限范围与管理员同意要求不同。
- [Microsoft Graph: Get access on behalf of a user](https://learn.microsoft.com/graph/auth-v2-user)：用户委托访问通过 OAuth 2.0 authorization code flow 获取同意和令牌，再以该用户身份调用 Graph；文档建议大多数应用使用 MSAL。
- [Microsoft identity platform auth concepts](https://learn.microsoft.com/en-us/graph/auth/auth-concepts)：delegated access 受到授予应用权限和已登录用户自身权限两者限制。
- 设计影响：本项目面向客户授权其自己的邮箱，应优先评估 delegated access，并按已确认功能请求最小 Graph scopes；不要默认采用可访问任意邮箱的 application permissions。产品方需预先注册/配置自己的 Microsoft Entra 应用、redirect URI 和必要权限/同意策略；客户用户授权不替代这些配置或租户管理员审批。

### WhatsApp Business Platform / Cloud API

- [Meta WhatsApp Business Platform 官方 Postman workspace](https://www.postman.com/meta/whatsapp-business-platform/overview)：Meta 官方工作区索引 Cloud API 文档和入门资料。
- [Cloud API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api?entity=request-13382743-9dbec0ce-30d4-4df2-b188-674b7d8da2d9)：官方工作区可用于后续核查具体 API 示例。当前检索工具只返回集合入口，未能验证请求说明正文，因此本记录不据此断言客户准入、生产授权、测试凭据限制或 WABA webhook 订阅的具体步骤。
- Meta 开发者文档 [Get Started](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started) 与 [Webhooks](https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks) 在当前检索环境无法安全获取正文；不得把未读取页面内容当作本次已核实规范。
- 因此本次 WhatsApp 仅能确认需以 WhatsApp Business Platform/Cloud API 官方规范为后续实施依据；账号资格、地区可用性、业务验证、计费、号码迁移/共存、OAuth/Embedded Signup、凭据生命周期、webhook 校验和订阅流程均保持“待官方核实”，不作推断。测试资产或模拟调用不等于客户生产资格、生产授权或真实连接。
- 设计影响：可先展示分步指南和“暂不可连接/需完成平台准入”等状态；不能用测试号码、测试 token、固定状态或模拟 webhook 冒充客户真实 WhatsApp 接通。任何正在使用的业务号码切换/迁移前必须另行取得账号所有者确认。

## 共同产品侧约束

1. 账号所有者在客户实际使用阶段自行完成平台侧资格、应用/资产准备、必要验证/计费和授权；产品方负责自己的 OAuth 应用配置、回调/API 集成、凭据保护、账号隔离、连接测试和状态呈现。
2. 授权状态、系统连接状态和真实入站验证是不同事实。建议 UI 分开显示：未开始/待平台准入、等待授权、授权完成待验证、已连接（仅在服务端连接检查成功后）、已验证（仅在真实读取/接收测试事件后）、失败/阻塞、已断开。不得只靠创建记录或 OAuth 成功就标记“已验证”。最终状态/枚举须结合 API 与数据模型设计确认。
3. 不在普通表单收集长期 Token，不将 access/refresh token 暴露给前端、URL、日志或分析追踪。OAuth state 必须抗 CSRF 且绑定当前用户/待授权连接与短期有效期；回调后服务端交换授权码并保存加密凭据。密钥管理、加密算法、刷新与撤销语义在编码前单独设计审阅。
4. Gmail/Outlook 的产品 OAuth 应用及 redirect URI 由产品开发方预先配置；客户授权不能替代应用注册、发布验证或可能的租户管理员审批。
5. 当前功能阶段不做真实客户账号接入、不发送出站测试消息、不将本地模拟或指南入口作为渠道验收。客户真实使用时再由账号所有者执行授权，并以真实入站/连接检查证据逐账号验收；运营主动出站按项目后续最终验收另行执行。

## 已确认的产品/权限决策与剩余验证

- **已确认：**系统仍仅供公司内部员工使用；账号由管理员创建并分发，不开放注册。渠道入口在“我的 > 接入渠道”。渠道账号按公司派发给员工的个人工作账号/渠道账号归属；管理员配置每个人可以接入的渠道范围，运营员工在其个人授权范围内连接、查看、重新授权和断开本人账号；客户/员工账号所有者本人完成平台授权。WhatsApp 号码也由员工本人按分配账号授权。该决定已同步至 `PROJECT_SPEC.md` 与 `docs/architecture.md`。
- **待实现前验证：**现有数据库用户模型没有岗位/部门授权表，目前只有 `admin`/`staff` 字符串角色；需在渠道 API 实现前定义运营岗位识别、管理员为个人配置渠道类型范围的持久化表示，并在后端做对象级检查。
- **待实现前验证：**员工离职、账号转交、多个账号、个人 WhatsApp WABA/号码资格及历史消息保留/解绑语义。WhatsApp 官方页面当前不能在检索环境读取，具体 Embedded Signup/授权、业务资产、地区/资格及 webhook 规范仍需在实现前回查官方材料；不得据邮箱 OAuth 模型推导。
- **产品侧前置：**Google/Microsoft OAuth 应用、Client ID、redirect URI、发布/同意配置由产品开发方配置，不由客户授权替代；具体环境配置由项目方在不暴露秘密的前提下另行完成。
- 最小 OAuth scopes、管理员同意、Gmail restricted-scope verification/security assessment 及未来出站需求，应在确定“首期只读入站”与完整运营收发范围后逐渠道复核。
- 精确连接状态转换、断开后历史数据保留、连接测试语义与错误展示需在模型/API 设计前确定。

## 当前结论

现有研究支持设计按需由员工发起的连接流程和服务端 OAuth 安全约束；租户边界已明确为公司内部员工个人账号，不是外部客户租户。但当前仓库尚无岗位/渠道授权持久化、渠道连接数据模型、密钥管理配置或产品侧 OAuth 应用，WhatsApp 官方流程也仍待核实。因此本次只更新设计记录，未新增可实际使用的渠道 API/迁移，也未执行真实授权；实现这些能力前需补齐上述基础并审阅迁移/安全方案。
