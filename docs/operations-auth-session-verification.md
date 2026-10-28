# 生产认证与会话验收规范

> 本文是生产运维和验收流程，不是业务需求或真实渠道接入证明。命令示例不得把密码、CSRF token、session cookie、数据库连接串、provider token 或客户内容写入终端记录、日志或 handoff。

## 1. 适用范围

本文用于排查和验收以下生产链路：

```text
HTTPS 外部 Nginx
  → /auth/csrf
  → CSRF cookie + response token
  → /auth/login
  → HttpOnly ea_session
  → /auth/me
  → 受保护业务 API
```

`/auth/csrf` 成功只表示 CSRF 初始化成功，不表示用户已经登录。只有登录成功并且 `/auth/me` 返回成功，才能把会话标为已建立。

## 2. 生产入口与代理边界

生产环境不使用 Vite 开发服务器作为入口。生产请求应由外部 HTTPS Nginx 转发到前端生产静态服务，再由前端 Nginx 将以下路径转发给 backend：

```text
/        → 前端静态资源和 SPA fallback
/api/    → backend
/auth/   → backend
```

`5173` 是本地 Vite dev server 端口，不是生产验收地址。生产验收应使用正式 HTTPS origin，并确认 backend 容器中的 `AUTH_ORIGIN` 与该 origin 完全一致（去除末尾 `/` 后比较）。

## 3. 一次登录必须使用一组状态

一次登录需要同时保持三项状态：

1. `/auth/csrf` 响应体中的 `csrf_token`；
2. 同一次响应写入的 `ea_csrf` cookie；
3. 登录成功后写入的 `ea_session` cookie。

命令行验收时，每一轮必须使用同一个 cookie jar。例如：

```text
/tmp/ea-login.cookies
/tmp/ea-csrf.json
/tmp/ea-login.headers
```

要求：

- `/auth/csrf` 的 `curl -c` 与 `/auth/login` 的 `curl -b/-c` 指向同一个 cookie jar；
- `EA_CSRF` 必须从同一次 `/auth/csrf` 响应提取；
- 不在同一轮混用旧的 `enterprise-agent-cookies.txt`、诊断 cookie 文件和新的登录 cookie 文件；
- 清理旧文件后必须重新获取 CSRF，不能继续使用旧 shell 变量；
- 所有请求使用同一个正式 Origin；
- 密码不能写入命令行参数、脚本文件、日志或 handoff。

同一个终端并不会自动同步不同的 cookie 文件，也不会让 shell 变量自动关联到某个 cookie jar。`-c` 只保存/更新指定文件，`-b` 只读取指定文件。

## 4. 标准只读/认证验收顺序

### 4.1 检查 backend 配置（不输出秘密）

```bash
docker compose --env-file .env exec -T backend \
  sh -lc 'printf "AUTH_ORIGIN=<%s>\\n" "$AUTH_ORIGIN"'
```

预期是正式 HTTPS origin，例如：

```text
AUTH_ORIGIN=<https://qianshuibingyu.xyz>
```

不要执行 `cat .env` 或复制 `.env` 内容到记录。

### 4.2 获取 CSRF

清理本轮临时文件后，使用同一 cookie jar：

```bash
rm -f /tmp/ea-login.cookies \
      /tmp/ea-csrf.json \
      /tmp/ea-csrf.headers \
      /tmp/ea-login.headers \
      /tmp/ea-login.body

curl -sS \
  -D /tmp/ea-csrf.headers \
  -o /tmp/ea-csrf.json \
  -c /tmp/ea-login.cookies \
  -H 'Origin: https://正式生产域名' \
  'https://正式生产域名/auth/csrf'
```

检查状态和 token 是否存在时只输出布尔结果，不输出 token：

```bash
awk 'NR == 1 { print }' /tmp/ea-csrf.headers

python - <<'PY'
import json
from pathlib import Path

data = json.loads(Path('/tmp/ea-csrf.json').read_text())
print('csrf response has token:', bool(data.get('csrf_token')))
PY
```

预期：`HTTP 200` 且 `csrf response has token: True`。

### 4.3 登录

从同一个 `/tmp/ea-csrf.json` 提取 token，在当前 shell 中输入账号和密码，并用同一个 `/tmp/ea-login.cookies` 发送登录请求。不要打印请求体或密码：

```bash
EA_CSRF=$(python -c '
import json
from pathlib import Path

token = json.loads(Path("/tmp/ea-csrf.json").read_text()).get("csrf_token")
if not token:
    raise SystemExit("csrf_token missing")
print(token)
')
export EA_CSRF
```

登录请求必须同时使用：

```text
-b /tmp/ea-login.cookies
-c /tmp/ea-login.cookies
-H "X-CSRF-Token: $EA_CSRF"
-H "Origin: https://正式生产域名"
```

建议只保存响应状态和响应头：

```bash
curl -sS \
  -D /tmp/ea-login.headers \
  -o /tmp/ea-login.body \
  -w 'HTTP %{http_code}\\n' \
  -b /tmp/ea-login.cookies \
  -c /tmp/ea-login.cookies \
  -H 'Origin: https://正式生产域名' \
  -H 'Content-Type: application/json' \
  -H "X-CSRF-Token: $EA_CSRF" \
  --data "$LOGIN_BODY" \
  'https://正式生产域名/auth/login'
```

`LOGIN_BODY` 的生成方式必须避免把密码写入命令历史；不要使用 `echo "$LOGIN_BODY"`。

### 4.4 验证会话

登录返回 `200` 后，必须继续验证：

```bash
curl -sS \
  -o /tmp/ea-me.body \
  -w 'auth/me HTTP %{http_code}\\n' \
  -b /tmp/ea-login.cookies \
  'https://正式生产域名/auth/me'
```

只有 `auth/me HTTP 200` 才能确认 session 可用。之后再请求受保护 API，例如：

```bash
curl -sS \
  -o /tmp/ea-analysis.body \
  -w 'internal-analysis HTTP %{http_code}\\n' \
  -b /tmp/ea-login.cookies \
  -H 'Content-Type: application/json' \
  --data '{"operation":"read"}' \
  'https://正式生产域名/api/internal-analysis'
```

完成后删除临时会话文件：

```bash
rm -f /tmp/ea-login.cookies \
      /tmp/ea-csrf.json \
      /tmp/ea-csrf.headers \
      /tmp/ea-login.headers \
      /tmp/ea-login.body \
      /tmp/ea-me.body \
      /tmp/ea-analysis.body
```

## 5. HTTP 状态码诊断

| 状态 | 位置 | 含义与处理 |
|---|---|---|
| `200` `/auth/csrf` | CSRF 初始化 | 只证明 CSRF 响应成功，不证明已登录 |
| `403` `/auth/csrf` 或 `/auth/login` | Origin/CSRF 层 | 检查 `AUTH_ORIGIN`、Origin、CSRF cookie、header token 是否来自同一轮；此时通常尚未进入密码校验 |
| `401` `/auth/login` | 密码阶段 | CSRF 已通过，用户名或密码错误；不要继续大量尝试 |
| `422` `/auth/login` | 请求体校验 | 用户名/密码变量为空或 JSON 字段格式不正确 |
| `200` `/auth/login`、`401` `/auth/me` | session 传递/生命周期 | 检查是否使用同一个 cookie jar、session 是否被撤销，以及 backend 是否被重建 |
| `200` `/auth/me`、`401` `/api/...` | 业务授权或会话使用 | 检查业务对象授权、`must_change_password` 和请求是否使用同一个 cookie jar |
| `404` `/api/...` | 代理路径 | 检查生产 Nginx 是否把 `/api/` 转发到 backend；不要把 Vite dev server 的响应当作 backend 响应 |

## 6. HttpOnly cookie 检查

`ea_session` 设置为 `HttpOnly`，浏览器脚本不能读取。curl 的 Netscape cookie 文件可能把它写成：

```text
#HttpOnly_...
```

因此不能使用以下规则判断 session 是否存在：

```awk
$0 !~ /^#/
```

它会把 HttpOnly cookie 错误过滤掉。不要输出 cookie 值；若确需检查名称，只处理字段 6：

```bash
awk '
  NF >= 6 {
    if ($6 == "ea_csrf" || $6 == "ea_session") print $6, "present"
  }
' /tmp/ea-login.cookies
```

最可靠的 session 验证仍然是：

```text
/auth/me → HTTP 200
```

登录响应头出现 `ea_session` 也只能证明服务端设置了 cookie；还应使用同一 cookie jar 调用 `/auth/me`。

## 7. 密码重置后的验收

密码重置/改密后应验证：

- 新密码可以登录；
- 旧密码不能登录；
- 旧 session 已撤销；
- `must_change_password` 符合重置策略；
- 重置失败时事务 rollback；
- 不修改用户角色、渠道账号或业务数据。

`create_admin.py` 只用于没有管理员时的首次 bootstrap。已有管理员时，它拒绝执行，不是密码重置工具。不要通过删除用户、清空数据库或 `docker compose down -v` 恢复密码。

## 8. 安全禁止事项

不得在终端输出、日志、截图、issue、handoff 或版本库中记录：

- 密码或密码哈希；
- `ea_session` cookie 值；
- CSRF token；
- 数据库密码、连接串或 `.env` 内容；
- Gmail/Outlook/WhatsApp token、QR 或 auth state；
- 客户原始消息或附件内容。

生产验证只记录命令目的、HTTP 状态码、退出状态和非敏感阻塞原因。

## 9. 本次排错经验摘要

本次生产认证排错中，曾因多个临时 cookie 文件和不同轮次的 CSRF token 混用而产生 `403`；统一使用同一 cookie jar 和同一次 `/auth/csrf` 响应后，`/auth/login` 返回 `200`。随后发现简单的 awk 检查排除了 curl Netscape 文件中的 `#HttpOnly_` 行，造成“没有 session”的误判。后续以 `/auth/me` 的实际结果作为 session 验证依据。

该摘要不包含任何密码、token、cookie、连接串或客户内容。
