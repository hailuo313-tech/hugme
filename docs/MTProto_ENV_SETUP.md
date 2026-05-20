# MTProto / Telethon 环境配置（C-03）

任务 **C-03** 交付物：让新人仅凭本页 + `.env.template` 即可配齐 **真人 Userbot（MTProto）** 所需环境变量。  
W2 接入 Telethon 代码尚未落地时，这些变量由 `app/core/config.py` 读取并供校验脚本检查。

## 快速开始

```powershell
cd E:\eris
copy .env.template .env
# 编辑 .env，至少填完下方「必填」四列
.\scripts\check-mtproto-env.ps1
```

Linux / 服务器：

```bash
cp .env.template .env
# 编辑 .env
bash scripts/check-mtproto-env.sh
```

Docker Compose 使用仓库根目录 `.env`（与 `docker-compose.yml` 同级）；`api` 服务会通过 compose 注入下列 `TELEGRAM_*` 变量。

## 必填项（MTProto 开发 / 联调）

| 变量 | 说明 | 获取方式 |
|------|------|----------|
| `TELEGRAM_API_ID` | 整数，应用 ID | [my.telegram.org/apps](https://my.telegram.org/apps) |
| `TELEGRAM_API_HASH` | 应用 hash 字符串 | 同上 |
| `TELEGRAM_SESSION_FERNET_KEY` | Fernet 密钥，用于加密落库的 StringSession | 见下方生成命令 |
| `TELEGRAM_SESSION_STRINGS` **或** `TELEGRAM_SESSION_DIR` | 至少配置一种 Session 来源 | 见下方 |

### 生成 `TELEGRAM_SESSION_FERNET_KEY`

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

未安装 `cryptography` 时：

```bash
pip install cryptography
```

**勿将 Fernet 密钥或 StringSession 提交到 Git。**

### Session 来源（二选一或并存）

1. **`TELEGRAM_SESSION_STRINGS`**（开发常用）  
   逗号分隔的 Telethon `StringSession`，例如单账号：  
   `TELEGRAM_SESSION_STRINGS=1BVtsOHwBu5X...`  
   多账号池：`TELEGRAM_SESSION_STRINGS=sess1,sess2`（勿含未转义逗号）。

2. **`TELEGRAM_SESSION_DIR`**（可选）  
   目录下放每账号一个 `.session` 文件，默认 `./data/telegram_sessions`。  
   目录已在 `.gitignore` 的 `data/` 下，不会进库。

首次登录生成 StringSession 属于 W2（P1-13+）实现范围；本阶段只要求 **变量位留好**。

## 可选项

| 变量 | 默认 | 说明 |
|------|------|------|
| `MTProto_ENABLED` | `0` | W2 前保持 `0`；Telethon 接入后改为 `1` |
| `TELEGRAM_BOT_TOKEN` | 空 | Bot Webhook 降级路径，与 MTProto 并存 |
| `TELEGRAM_DEVICE_MODEL` | `ERIS` | Telethon 客户端标识 |
| `TELEGRAM_SYSTEM_VERSION` | `1.0` | 同上 |

完整应用变量见 **`.env.template`**（新人模板）与 **`.env.example`**（与当前 compose 字段对齐的超集）。

## 验收自检

```powershell
.\scripts\check-mtproto-env.ps1
# 退出码 0 = MTProto 区块已填齐
```

## 相关文件

| 文件 | 用途 |
|------|------|
| `.env.template` | C-03 标准模板（复制为 `.env`） |
| `.env.example` | 历史 compose 变量参考 |
| `app/core/config.py` | `Settings` 字段定义 |
| `docker-compose.yml` | `api.environment` 注入 |

## 故障排查

| 现象 | 处理 |
|------|------|
| `TELEGRAM_API_ID` 非数字 | 只填 my.telegram.org 上的数字 ID |
| check 脚本报缺 Fernet | 必须生成新密钥，不能用占位符 `change_me` |
| compose 内读不到变量 | 确认 `.env` 在仓库根目录且已 `docker compose up` 重建 api |
| 与 Bot Token 混淆 | MTProto 用 API_ID/HASH + Session；Bot 用 `TELEGRAM_BOT_TOKEN` |
