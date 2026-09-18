# 🚀 VPSFree.es 自动续期脚本 (GitHub Actions 增强版)

> ⚠️ 本仓库为公开工作流仓库，核心运行脚本托管于私人仓库 **[my-private-scripts (vpsfree 目录)](https://github.com/yuxiaojie0322-maker/my-private-scripts)**，在 GitHub Actions 运行阶段自动带鉴权拉取执行。

基于 **GitHub Actions + Playwright + NopeCHA + Sing-box (Hysteria 2)** 的全自动 [VPSFree.es](https://free.vpsfree.es) 免费 VPS 续期与巡检工具。

无需自己准备服务器或电脑开机，每日定时云端巡检、自动打码、精准捕捉 24 小时续期窗口，并将实例运行仪表盘与到期倒计时推送至 Telegram！

---

## ✨ 核心特性

- 🌐 **内置 Hysteria 2 代理网络**：自动启动 `sing-box` 客户端，完美绕过微软 GitHub 云端机房 IP 拦截风控。
- 🤖 **NopeCHA 验证码自动破解**：无缝通过 `free.vpsfree.es` 的 **hCaptcha** 人机验证。
- ⚡ **精准捕捉 24 小时续期窗口**：根据官方规则（*仅在到期前最后 24 小时开放续期按钮*），设置每 12 小时（早晚各一次）自动巡检，确保绝不漏续、绝不删机。
- 👥 **支持单账号 / 多账号批量轮询**：一个 Secret 即可配置多个账号，每个账号独立隔离会话运行。
- 📸 **Telegram 仪表盘高清图文推送**：自动进入 `Instance Management` 详情页截取高分辨率完整界面，并格式化推送 CPU/内存占用、运行时间与到期倒计时。

---

## 🛠️ 配置教程

### 第一步：创建 GitHub Secrets 环境变量

进入你的 GitHub 仓库 ➔ **Settings** ➔ **Secrets and variables** ➔ **Actions** ➔ 点击 **New repository secret**，添加以下变量：

| Secret 变量名 | 是否必填 | 说明 | 示例值 |
| :--- | :--- | :--- | :--- |
| `CORE_SCRIPT_TOKEN` | **必填** | 具备读取私有仓库 `my-private-scripts` 权限的 GitHub PAT | `ghp_xxxx` |
| `VPS_ACCOUNTS` | **推荐** | **多账号配置**（一行一个，使用 `----` 分隔邮箱与密码） | 见下方多账号示例 |
| `VPS_EMAIL` | 可选 | 单账号模式邮箱（若未填 `VPS_ACCOUNTS` 则使用此项） | `example@gmail.com` |
| `VPS_PASSWORD` | 可选 | 单账号模式密码 | `YourPassword123` |
| `NOPECHA_KEY` | **必填** | [NopeCHA](https://nopecha.com) 官方 API Key（用于自动打码） | `k_1234567890abcdef` |
| `TG_BOT_TOKEN` | 可选 | Telegram Bot Token（用于消息推送） | `123456789:ABCdef...` |
| `TG_CHAT_ID` | 可选 | Telegram 接收通知的用户/群组 Chat ID | `987654321` |

> 💡 **`VPS_ACCOUNTS` 多账号填写示例（支持任意添加多个，回车换行即可）：**
> ```text
> myemail1@gmail.com----Password123@
> myemail2@outlook.com----Password456@
> ```

---

### 第二步：手动触发测试

1. 点击仓库顶部的 **Actions** 标签页。
2. 在左侧选择 **VPSFree 自动续期** 工作流。
3. 点击右侧的 **Run workflow** ➔ 再次点击绿色的 **Run workflow** 按钮。
4. 查看运行日志，并在 Telegram 中查收完整的实例仪表盘截图与运行报告！

---

## ⏰ 定时任务说明

工作流默认配置为 **每天 UTC 00:00 和 12:00（北京时间 08:00 和 20:00）各自动运行一次**：

```yaml
schedule:
  - cron: '0 0,12 * * *'

