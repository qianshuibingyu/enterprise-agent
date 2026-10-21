# 目标服务器检查记录

> 本文仅记录用户在目标服务器实际执行并贴出的检查结果；未执行项目不推断为通过。
>
> 记录日期：2026-10-19（依据本次记录日期）
> 执行位置：Alibaba Cloud Linux 服务器，提示符主机名 `iZj6cj2jk6fiwhspq216jqZ`；当时 shell 所在目录为 `frontend/`。

## 1. 检查结果

| 检查项 | 实际结果 | 状态与说明 |
|---|---|---|
| `cat /etc/os-release` | `NAME="Alibaba Cloud Linux"`；`VERSION="3 (OpenAnolis Edition)"`；`ID="alinux"`；`ID_LIKE="rhel fedora centos anolis"`；`VERSION_ID="3"`；`VARIANT="OpenAnolis Edition"`；`VARIANT_ID="openanolis"`；`ALINUX_MINOR_ID="2104"`；`ALINUX_UPDATE_ID="13.4"`；`PLATFORM_ID="platform:al8"`；`PRETTY_NAME="Alibaba Cloud Linux 3.2104 U13.4 (OpenAnolis Edition)"`；`HOME_URL="https://www.aliyun.com/"`。 | **已检查**。与项目目标 Alibaba Cloud Linux 3.2104 LTS 的发行版及 3.2104 系列相符；实际系统标识为 U13.4。 |
| `nproc` | `2` | **已检查**。当前可用处理器数为 2，与项目目标 2 vCPU 数量相符。 |
| `free -h` | `Mem: total 1.8Gi, used 1.5Gi, free 115Mi, shared 2.0Mi, buff/cache 359Mi, available 329Mi`；`Swap: 0B, 0B, 0B`。 | **已检查**。内存总量显示为 1.8 GiB，可用内存为 329 MiB；检查时已用 1.5 GiB。记录为命令当时的运行状态，不把它解释为固定余量或容器配额。Swap 显示为 0B。 |
| `df -h` | `/dev/vda3`：40G，总用 15G，可用 23G，39%，挂载 `/`；`/dev/vda2`：200M，总用 5.8M，可用 194M，3%，挂载 `/boot/efi`。另有 `overlay` 挂载在 `/var/lib/docker/overlay2/443307c407981026efbba6c5dd91978e90e2fbf524fd4259d889f79eb0abab13/merged`，显示 40G、已用 15G、可用 23G、39%。其余 devtmpfs/tmpfs 行见下方原始摘要。 | **已检查**。根文件系统 `/` 可用 23G（39% 已用）。Docker overlay 显示与根文件系统相同的容量数据；此输出未单独证明 Docker 数据目录所在底层磁盘或其配额。 |
| `docker --version` | `Docker version 26.1.3, build b72abbb` | **已检查**。记录客户端报告的 Docker 版本；此命令本身不证明 Docker 守护进程状态或当前用户访问权限。 |
| `docker compose version` | `Docker Compose version v2.27.0` | **已检查**。Compose 命令可报告版本；此命令本身不证明项目 Compose 配置可解析或服务可启动。 |
| `swapon --show` | 无输出。 | **已检查**。本次输出未列出已启用的 Swap 设备/文件；`free -h` 也显示 Swap 为 0B。项目说明书未将 Swap 设为硬性验收条件。 |

## 2. 磁盘检查原始摘要

```text
Filesystem      Size  Used Avail Use% Mounted on
devtmpfs        916M     0  916M   0% /dev
tmpfs           936M     0  936M   0% /dev/shm
tmpfs           936M  564K  935M   1% /run
tmpfs           936M     0  936M   0% /sys/fs/cgroup
/dev/vda3        40G   15G   23G  39% /
/dev/vda2       200M  5.8M  194M   3% /boot/efi
tmpfs           188M   40K  188M   1% /run/user/0
overlay          40G   15G   23G  39% /var/lib/docker/overlay2/443307c407981026efbba6c5dd91978e90e2fbf524fd4259d889f79eb0abab13/merged
```

## 3. 同次会话提供的前端构建结果

用户同时提供了在 `frontend/` 目录执行 `npm run build` 的输出：Vite `6.4.4`，`8 modules transformed`，生成 `dist/index.html`（0.33 kB，gzip 0.24 kB）和 `dist/assets/index-WnPuYi0Y.js`（65.91 kB，gzip 26.25 kB），最终显示 `✓ built in 1.93s`。此结果已同步记录到 [day1-verification.md](day1-verification.md)；它只证明这次前端生产构建成功，不证明浏览器页面视觉验收、前后端联调或服务器生产部署完成。

## 4. 未由本次输出证明的事项

- Docker daemon 是否正常运行、当前用户是否具有所需访问权限（版本命令不能证明）。
- `compose.yaml` 是否通过 `docker compose config`，项目镜像是否成功构建，Compose 容器是否启动，以及容器内 `/health` 是否返回 HTTP 200。
- 目标服务器上的 FastAPI/Uvicorn 是否已启动并通过 HTTP 请求验证。
- Nginx、HTTPS、数据库、备份恢复、渠道授权及完整生产部署。
- Swap 是否需要配置；当前项目基线没有将其设为硬性要求。
