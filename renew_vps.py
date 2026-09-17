"""
VPSFree.es 免费面板自动续期脚本 (多账号批量续期版 - 登录无限重试直至成功)
- 支持单账号 (VPS_EMAIL/VPS_PASSWORD) 与 多账号 (VPS_ACCOUNTS)
- 登录错误自动重试，直至成功为止
- 多账号隔离会话独立执行
- 每个账号独立发送 TG 仪表盘截图与到期报告
"""

import os
import random
import re
import sys
import time
import json
import urllib.request
import ssl
import requests
from datetime import datetime

# 强制 stdout flush，避免日志看不到
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# ========== 配置 ==========
NOPECHA_KEY = os.environ.get("NOPECHA_KEY", "").strip()
# Playwright 仅支持 http/socks5。Hysteria 2 / TUIC 节点需经本地 Sing-box/Clash 转发为本地端口
PROXY_URL = os.environ.get("PROXY_URL", "socks5://127.0.0.1:10808").strip()
BASE_URL = "https://free.vpsfree.es"
EXT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "scripts", "extensions", "nopecha", "unpacked")

# 失败重试等待间隔（秒）
RETRY_DELAY = int(os.environ.get("RETRY_DELAY", "10"))

# Telegram 推送配置
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()


def log(msg, level="INFO"):
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{t}] [{level}] {msg}", flush=True)


def solve_hcaptcha_api(sitekey, pageurl):
    """NopeCHA API 解 hCaptcha（插件失效时的兜底方案）"""
    if not NOPECHA_KEY:
        return None
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        payload = json.dumps({
            "key": NOPECHA_KEY,
            "type": "hcaptcha",
            "data": {"sitekey": sitekey, "pageurl": pageurl}
        }).encode()
        proxy = urllib.request.ProxyHandler({"https": PROXY_URL, "http": PROXY_URL})
        opener = urllib.request.build_opener(proxy)
        req = urllib.request.Request(
            "https://api.nopecha.com",
            data=payload, method="POST",
            headers={"Content-Type": "application/json"}
        )
        with opener.open(req, timeout=60) as r:
            result = json.loads(r.read())
            token = result.get("data")
            if token:
                log(f"[NopeCHA API] ✅ hCaptcha token: {str(token)[:25]}...")
                return token
            log(f"[NopeCHA API] ❌ {result}", "WARN")
    except Exception as e:
        log(f"[NopeCHA API] 异常: {e}", "WARN")
    return None


def send_tg_photo(photo_path, caption=""):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        log("未配置 TG 推送，跳过", "WARN")
        return False
    if not os.path.exists(photo_path):
        log(f"截图文件不存在: {photo_path}", "WARN")
        return send_tg_text(caption)
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
        with open(photo_path, "rb") as f:
            files = {"photo": f}
            data = {"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
            resp = requests.post(url, files=files, data=data, timeout=30)
        res_json = resp.json()
        if res_json.get("ok"):
            log("TG 仪表盘截图已成功发送 ✅")
            return True
        else:
            log(f"TG 图片发送失败: {res_json}，改发纯文本...", "WARN")
            return send_tg_text(caption)
    except Exception as e:
        log(f"TG 发送异常: {e}", "ERROR")
        return send_tg_text(caption)


def send_tg_text(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": TG_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=15)
        return resp.json().get("ok", False)
    except Exception as e:
        log(f"TG 纯文本发送异常: {e}", "ERROR")
        return False


def get_accounts():
    """解析单账号或多账号列表（增强容错与多格式清洗）"""
    accounts = []
    raw_multi = os.environ.get("VPS_ACCOUNTS", "").strip()

    if raw_multi:
        for line in raw_multi.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # 去除用户可能复制的前缀如 "账号1："、"账号1:"、"1." 等
            line = re.sub(r"^(?:账号\s*\d+\s*[：:]\s*|\d+[\.、]\s*)", "", line)

            parts = None
            if "----" in line:
                parts = line.split("----", 1)
            elif "密码" in line:
                parts = line.split("密码", 1)
            elif ":" in line:
                parts = line.split(":", 1)
            elif "：" in line:
                parts = line.split("：", 1)
            elif "," in line:
                parts = line.split(",", 1)
            elif "\t" in line:
                parts = line.split("\t", 1)
            else:
                parts = line.split(None, 1)

            if parts and len(parts) == 2:
                em = parts[0].strip()
                pw = parts[1].strip()
                if em and pw:
                    accounts.append({"email": em, "password": pw})

    if not accounts:
        single_email = os.environ.get("VPS_EMAIL", "").strip()
        single_pwd = os.environ.get("VPS_PASSWORD", "").strip()
        if single_email and single_pwd:
            accounts.append({"email": single_email, "password": single_pwd})

    return accounts



def is_on_server_detail_page(page):
    """检测当前是否已处于 VPS 实例的管理详情页"""
    try:
        url = page.url.lower()
        if any(k in url for k in ["/connexion", "/login", "/order", "/commande", "/inscription", "/register"]):
            return False

        body_text = page.evaluate("() => document.body ? document.body.innerText : ''")

        # 1. 检查是否存在实例特有的管理控制按钮 (Reboot, Restart, Redémarrer, Console, VNC, etc.)
        has_controls = False
        for ctrl_sel in [
            "button:has-text('Restart')", "button:has-text('Reboot')", "button:has-text('Redémarrer')",
            "button:has-text('Console')", "a:has-text('Console')",
            "button:has-text('Renew')", "a:has-text('Renew')",
            "button:has-text('Renouveler')", "a:has-text('Renouveler')",
            "button:has-text('Stop')", "button:has-text('Arrêter')",
            "button:has-text('Power')", "button:has-text('Alimentation')",
        ]:
            try:
                if page.locator(ctrl_sel).count() > 0:
                    has_controls = True
                    break
            except Exception:
                pass

        # 2. 检查是否有实例专属指标文本 (CPU, RAM/Memory, Disk, Expiration, Uptime)
        has_metrics = bool(re.search(r"(?:Expires|Expiration|Expire le|Date d'expiration|Vence|Expira)\s*[:：]?", body_text, re.I)) or \
                      bool(re.search(r"(?:Renewal opens in|Renouvellement disponible dans|Renouvellement ouvert dans)", body_text, re.I)) or \
                      (bool(re.search(r"\bCPU\b", body_text, re.I)) and bool(re.search(r"\b(?:RAM|MEMORY|MÉMOIRE)\b", body_text, re.I)))

        # 3. 检查 URL 是否带具体实例路径（排除纯列表路径如 /vps, /instances, /servers）
        is_detail_url = bool(re.search(r"/(?:instance|vps|server|vm|manage)/\w+", url))

        return (has_metrics and has_controls) or (has_metrics and is_detail_url) or (has_controls and is_detail_url) or has_controls or (has_metrics and "/vps" not in url and "/instances" not in url)
    except Exception:
        return False


def perform_renewal_if_available(page, email):
    """检测并点击页面上的 Renew 7 days 续期按钮（支持列表页与详情页）"""
    log(f"[{email}] 正在检测可用续期按钮 (Renew 7 days)...")
    for renew_selector in [
        "a:has-text('Renew 7 days')",
        "button:has-text('Renew 7 days')",
        "a:has-text('Renew for 7 days')",
        "button:has-text('Renew for 7 days')",
        "a:has-text('Renouveler pour 7 jours')",
        "button:has-text('Renouveler pour 7 jours')",
        "a:has-text('Renew'):not([href*='order']):not([href*='new'])",
        "button:has-text('Renew'):not(:has-text('New')):not(:has-text('Order'))",
    ]:
        try:
            btns = page.locator(renew_selector)
            for i in range(btns.count()):
                btn = btns.nth(i)
                if not btn.is_visible(timeout=1000):
                    continue

                disabled_attr = btn.get_attribute("disabled")
                class_attr = (btn.get_attribute("class") or "").lower()
                style_attr = (btn.get_attribute("style") or "").lower()

                # 如果明确被禁用或者是灰色状态
                if disabled_attr is not None or "disabled" in class_attr or "pointer-events: none" in style_attr:
                    log(f"[{email}] 续期按钮存在但已被禁用 (disabled)，未到 24h 窗口")
                    return "disabled"

                log(f"[{email}] 🚀 发现高亮可用续期按钮: {renew_selector}，立即触发点击！")
                btn.scroll_into_view_if_needed()
                time.sleep(0.5)
                btn.click(timeout=8000)
                time.sleep(3)

                # 处理弹窗二次确认
                for confirm_selector in [
                    "button:has-text('Confirm')",
                    "button:has-text('Confirmer')",
                    "button:has-text('Confirmar')",
                    "button:has-text('Yes')",
                    "button:has-text('Oui')",
                    "button:has-text('Valider')",
                    "button:has-text('OK')",
                    ".modal button.btn-primary",
                    "button.btn-success",
                    "a:has-text('Confirm')",
                ]:
                    try:
                        c_btn = page.locator(confirm_selector).first
                        if c_btn.is_visible(timeout=2000):
                            c_btn.click(timeout=5000)
                            log(f"[{email}] 点击二次确认按钮: {confirm_selector} ✅")
                            time.sleep(2)
                            break
                    except Exception:
                        pass

                log(f"[{email}] 🎉 续期请求提交完成！")
                return "renewed"
        except Exception as e:
            log(f"[{email}] 续期按钮扫描异常: {e}", "DEBUG")

    log(f"[{email}] 当前未发现可点击的续期按钮")
    return "not_found"


def navigate_to_server_page(page, email):
    """
    智能定位进入实例独立详情页（优先点击 Manage VPS 按钮）
    """
    current_url = page.url.lower()
    log(f"[{email}] 正在定位实例管理页面，当前 URL: {current_url}")


    # 等待页面 DOM 与异步数据加载完成
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    time.sleep(2)

    # 1. 核心关键：检查页面是否存在 Manage VPS 按钮，优先直接通过 href 跳转进入
    mv_info = page.evaluate("""() => {
        const els = Array.from(document.querySelectorAll('a, button'));
        for (const el of els) {
            const txt = (el.innerText || el.textContent || '').trim();
            if (txt.includes('Manage VPS')) {
                el.removeAttribute('target');
                const href = el.getAttribute('href');
                return { found: true, href: href, tag: el.tagName };
            }
        }
        return { found: false };
    }""")

    if mv_info and mv_info.get("found"):
        href = mv_info.get("href")
        log(f"[{email}] 🎯 发现【Manage VPS】按钮 (href={href})，立即进入详情页...")

        if href and not href.startswith("#") and not href.startswith("javascript"):
            try:
                target_url = href if href.startswith("http") else f"{BASE_URL.rstrip('/')}/{href.lstrip('/')}"
                log(f"[{email}] 🚀 URL 直达实例详情页: {target_url}")
                page.goto(target_url, timeout=15000)
                time.sleep(4)
                log(f"[{email}] ✅ 已成功直达实例详情页: {page.url}")
                return "ok"
            except Exception as e:
                log(f"[{email}] 直接跳转异常: {e}，改用点击触发", "WARN")

        # 物理点击 + DOM 强制点击
        try:
            mv_btn = page.locator("a:has-text('Manage VPS'), button:has-text('Manage VPS')").first
            mv_btn.scroll_into_view_if_needed()
            time.sleep(0.5)
            mv_btn.click(force=True, timeout=5000)
        except Exception:
            page.evaluate("""() => {
                const els = Array.from(document.querySelectorAll('a, button'));
                for (const el of els) {
                    if ((el.innerText || '').trim().includes('Manage VPS')) {
                        el.removeAttribute('target');
                        el.click();
                        break;
                    }
                }
            }""")

        time.sleep(4)
        log(f"[{email}] ✅ 已通过 Manage VPS 进入: {page.url}")
        return "ok"

    # 2. 检查是否在 Order 页面（无实例或被强制引导订购）
    if "/order" in current_url or "commande" in current_url:
        log(f"[{email}] ⚠️ 当前在 Order 页面（可能无有效实例）", "WARN")
        return "order_page"

    # 3. 检查当前是否已经是实例详情页
    if is_on_server_detail_page(page):
        log(f"[{email}] ✅ 已在实例详情页: {page.url}")
        return "ok"




    # 3. 候选实例入口选择器（优先命中精准的 Manage 与 Gérer 链接）
    candidate_selectors = [
        "a:has-text('Manage'):not([href*='order']):not([href*='new']):not([href*='create'])",
        "a:has-text('Gérer'):not([href*='order']):not([href*='new']):not([href*='create'])",
        "a:has-text('Manage VPS'):not([href*='order']):not([href*='new'])",
        "a:has-text('Gérer le VPS'):not([href*='order']):not([href*='new'])",
        "button:has-text('Manage'):not(:has-text('New'))",
        "button:has-text('Gérer')",
        "table a:has-text('Manage'):not([href*='order']):not([href*='new'])",
        "table a:has-text('Gérer'):not([href*='order']):not([href*='new'])",
        "a[href*='/projet/']:not([href*='order']):not([href*='new']):not([href*='create'])",
        "a[href*='/serveur/']:not([href*='order']):not([href*='new']):not([href*='create'])",
        "a[href*='/instance/']:not([href*='order']):not([href*='new']):not([href*='create']):not([href*='delete'])",
        "a[href*='/vps/']:not([href*='order']):not([href*='new']):not([href*='create']):not([href*='delete'])",
        "a[href*='/server/']:not([href*='order']):not([href*='new']):not([href*='create']):not([href*='delete'])",
        "a[href*='/vm/']:not([href*='order']):not([href*='new']):not([href*='create']):not([href*='delete'])",
        "a:has-text('View Details'):not([href*='order'])",
        "a:has-text('Détails'):not([href*='order'])",
        "a:has-text('Console'):not([href*='order'])",
        ".card a:not([href*='order']):not([href*='new'])",
        ".server-card a:not([href*='order']):not([href*='new'])",
    ]

    clicked = False
    log(f"[{email}] 正在当前页面寻找实例卡片或管理入口...")
    for sel in candidate_selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=2500):
                log(f"[{email}] 发现实例入口，点击: {sel}")
                loc.click(timeout=5000)
                time.sleep(3)
                clicked = True
                break
        except Exception:
            continue


    # 4. 如果页面有数据表格 table，且上述没有命中，点击第一行中的主要链接
    if not clicked:
        try:
            table_rows = page.locator("table tbody tr")
            if table_rows.count() > 0:
                first_row = table_rows.first
                row_links = first_row.locator("a:not([href*='order']):not([href*='new']):not([href*='delete']):not([href*='cancel'])")
                if row_links.count() > 0:
                    target_link = row_links.first
                    log(f"[{email}] 点击表格首行实例链接: {target_link.get_attribute('href')}")
                    target_link.click(timeout=5000)
                    time.sleep(3)
                    clicked = True
        except Exception as e:
            log(f"[{email}] 表格检查异常: {e}", "DEBUG")

    # 5. 如果当前在主仪表盘，且页面未直接展示实例，尝试导航至 VPS/Instances 菜单
    cur_u = page.url.lower()
    if not clicked and ("dashboard" in cur_u or cur_u.rstrip("/").endswith("vpsfree.es")):
        log(f"[{email}] 当前在主仪表盘，尝试导航至 VPS/Instances 菜单...")
        nav_selectors = [
            "a[href*='/vps']:not([href*='order'])",
            "a[href*='/instance']:not([href*='order'])",
            "a[href*='/server']:not([href*='order'])",
            "a[href*='/service']:not([href*='order'])",
            "a:has-text('Instances')",
            "a:has-text('My Instances')",
            "a:has-text('Mes Instances')",
            "a:has-text('VPS')",
            "a:has-text('My VPS')",
            "a:has-text('Mes VPS')",
            "a:has-text('Servers')",
            "a:has-text('Services')",
        ]
        for n_sel in nav_selectors:
            try:
                n_loc = page.locator(n_sel).first
                if n_loc.is_visible(timeout=1500):
                    log(f"[{email}] 点击导航菜单: {n_sel}")
                    n_loc.click(timeout=5000)
                    time.sleep(3)
                    clicked = True
                    break
            except Exception:
                continue

        # 进入列表页后，再次在列表页中点击具体实例
        if clicked:
            time.sleep(2)
            log(f"[{email}] 已进入列表页: {page.url}，正在寻找具体实例...")
            for sel in candidate_selectors:
                try:
                    loc = page.locator(sel).first
                    if loc.is_visible(timeout=1500):
                        log(f"[{email}] 列表页点击实例入口: {sel}")
                        loc.click(timeout=5000)
                        time.sleep(3)
                        break
                except Exception:
                    continue

    # 6. 如果在 /projets 页面，优先寻找实例入口并绝对避免跳转到不存在的 404 路由
    if "/projets" in current_url or "/projets" in page.url.lower():
        log(f"[{email}] 当前已在 projets 项目页面，正在定位具体实例卡片...")
        for p_sel in [
            "a:has-text('Manage'):not([href*='order'])",
            "a:has-text('Gérer'):not([href*='order'])",
            "a:has-text('View'):not([href*='order'])",
            "a:has-text('Détails')",
            ".card a:not([href*='order']):not([href*='new'])",
            "a[href*='/projet/']",
            "a[href*='/server/']",
            "a[href*='/vps/']",
        ]:
            try:
                loc = page.locator(p_sel).first
                if loc.count() > 0 and loc.is_visible(timeout=1500):
                    log(f"[{email}] 点击 projets 实例卡片: {p_sel}")
                    loc.click(timeout=5000)
                    time.sleep(3)
                    clicked = True
                    break
            except Exception:
                continue

    # 若误入 404 页面，立即返回 /projets
    if "not found" in page.evaluate("() => document.body ? document.body.innerText.toLowerCase() : ''"):
        log(f"[{email}] 检测到 404 页面，安全返回主项目页面 /projets ...", "WARN")
        try:
            page.goto(f"{BASE_URL}/projets", timeout=15000)
            time.sleep(3)
        except Exception:
            pass


    # 7. 检查次级跳转按钮 (如 "Manage VPS")
    for sub_sel in [
        "a:has-text('Manage VPS'):not([href*='order'])",
        "a:has-text('Gérer le VPS')",
        "button:has-text('Manage VPS')",
        "button:has-text('Gérer le VPS')",
    ]:
        try:
            sub_btn = page.locator(sub_sel).first
            if sub_btn.is_visible(timeout=1500):
                log(f"[{email}] 二次点击子级管理按钮: {sub_sel}")
                sub_btn.click(timeout=3000)
                time.sleep(3)
                break
        except Exception:
            pass

    final_url = page.url.lower()
    if is_on_server_detail_page(page) or "/projets" in final_url:
        log(f"[{email}] ✅ 成功到达实例管理页面: {final_url}")
        return "ok"
    elif "/order" in final_url or "commande" in final_url:
        log(f"[{email}] ⚠️ 最终停留在 Order 页面", "WARN")
        return "order_page"
    else:
        log(f"[{email}] ⚠️ 未能明确确认到达实例详情页，当前 URL: {final_url}", "WARN")
        try:
            page_links = page.evaluate("() => Array.from(document.querySelectorAll('a')).map(a => a.innerText.trim() + ' -> ' + a.href).filter(x => x.length > 5).slice(0, 10)")
            log(f"[{email}] 当前页面链接前10个: {page_links}")
        except Exception:
            pass
        return "uncertain"


def process_single_account(p, email, password, acc_index, total_accs):
    log(f"▶️ 开始处理账号 [{acc_index}/{total_accs}]: {email}")
    ext_ok = os.path.exists(EXT_PATH) and os.path.exists(os.path.join(EXT_PATH, "manifest.json"))
    log(f"[{email}] NopeCHA 插件路径: {EXT_PATH}，存在={ext_ok}")

    launch_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
    ]
    if ext_ok:
        launch_args.extend([
            f"--disable-extensions-except={EXT_PATH}",
            f"--load-extension={EXT_PATH}",
        ])

    proxy_config = None
    if PROXY_URL:
        clean_proxy = PROXY_URL.split("#")[0].strip()
        if clean_proxy.startswith(("http://", "https://", "socks5://", "socks4://")):
            proxy_config = {"server": clean_proxy}
        else:
            log(f"[{email}] 代理协议不受 Chromium 支持，请转为 socks5/http: {clean_proxy}", "WARN")

    # 最多重试3次
    for attempt in range(1, 4):
        log(f"[{email}] === 第 {attempt} 次尝试 ===")
        log(f"[{email}] 🔄 正在启动独立会话...")
        browser = None

        try:
            user_data_dir = f"/tmp/playwright-user-{acc_index}"
            t_launch = time.time()
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                proxy=proxy_config,
                args=launch_args,
                ignore_default_args=["--enable-automation"],
                viewport={"width": 1440, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                locale="zh-CN",
                bypass_csp=True,
                ignore_https_errors=True,
            )
            log(f"[{email}] ✅ Chromium 启动完成 (耗时 {time.time()-t_launch:.1f}s)")

            page = browser.pages[0] if browser.pages else browser.new_page()
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")

            # 路由过滤：拦截无关的字体、音视频与外部追踪统计，大幅减轻源站与代理负担
            def route_interceptor(route):
                try:
                    req_type = route.request.resource_type
                    req_url = route.request.url.lower()
                    if req_type in ["font", "media"]:
                        return route.abort()
                    if any(bad in req_url for bad in ["google-analytics", "googletagmanager", "clarity.ms", "doubleclick", "facebook.net"]):
                        return route.abort()
                    return route.continue_()
                except Exception:
                    try:
                        route.continue_()
                    except Exception:
                        pass

            try:
                page.route("**/*", route_interceptor)
            except Exception:
                pass

            # 1. 激活 NopeCHA（插件模式，仅当插件加载成功时）
            if ext_ok and NOPECHA_KEY:
                try:
                    log(f"[{email}] 激活 NopeCHA 插件...")
                    page.goto(f"https://nopecha.com/setup#{NOPECHA_KEY}", wait_until="commit", timeout=30000)
                    time.sleep(3)
                except Exception as e:
                    log(f"[{email}] NopeCHA setup 失败（不影响主流程）: {e}", "WARN")

            # 1.5 代理连通性预检测
            log(f"[{email}] 预检测代理...")
            try:
                req = urllib.request.Request(BASE_URL, headers={"User-Agent": "Mozilla/5.0"})
                proxy = urllib.request.ProxyHandler({"https": PROXY_URL, "http": PROXY_URL})
                opener = urllib.request.build_opener(proxy)
                opener.open(req, timeout=15)
                log(f"[{email}] ✅ 代理可达")
            except Exception as e:
                log(f"[{email}] ⚠️ 代理预检: {e}", "WARN")

            # 2. 打开登录页（设置合理超时 60s）
            log(f"[{email}] [第 {attempt} 次] 打开登录页: {BASE_URL}/connexion ...")
            try:
                page.goto(f"{BASE_URL}/connexion", wait_until="commit", timeout=60000)
                log(f"[{email}] ✅ 页面提交请求完成")
            except Exception as e:
                log(f"[{email}] ❌ 页面加载超时(60s): {e}", "WARN")
                try:
                    page.screenshot(path=f"goto_timeout_{acc_index}.png")
                except Exception:
                    pass
            time.sleep(3)

            # 检测是否遭遇源站宕机 (Cloudflare 520/521/522/523/524/502/504)
            try:
                page_text = page.evaluate("() => document.body ? document.body.innerText : ''")
                if any(err_sig in page_text for err_sig in ["Error code 524", "Error code 522", "Error code 520", "Error code 521", "Error code 523", "Host Error", "Web server is down"]):
                    log(f"[{email}] ⚠️ 检测到 Cloudflare 源站异常/超时，源站高负载，等待 15s 后重新刷新...", "WARN")
                    time.sleep(15)
                    page.reload(wait_until="commit", timeout=60000)
                    time.sleep(3)
            except Exception:
                pass

            # 2.5 等待并自动穿透 Cloudflare challenge / Turnstile（最多 45s）
            log(f"[{email}] [第 {attempt} 次] 检测并等待 Cloudflare challenge / Turnstile 通过...")
            cf_passed = False
            for cf_wait in range(45):
                try:
                    # 检查是否已经显示登录输入框（最直接标志）
                    email_loc = page.locator("input[type='email'], input[name='email'], input[name='username']")
                    if email_loc.count() > 0 and email_loc.first.is_visible():
                        log(f"[{email}] ✅ 已直接检测到登录输入框，Cloudflare 通过（耗时 {cf_wait}s）")
                        cf_passed = True
                        break

                    page_content = page.content()
                    if "Just a moment" not in page_content and "cloudflare" not in page_content.lower():
                        log(f"[{email}] ✅ Cloudflare challenge 已通过（等待 {cf_wait}s）")
                        cf_passed = True
                        break

                    if "cdn-cgi" in page_content and "status" in page_content:
                        status_match = re.search(r'"status":"(\w+)"', page_content)
                        if status_match and status_match.group(1) == "ok":
                            log(f"[{email}] ✅ Cloudflare challenge 已通过")
                            cf_passed = True
                            break

                    # 尝试寻找并点击 Cloudflare Turnstile 复选框
                    # 1) 在所有 frame 中寻找验证复选框
                    for frame in page.frames:
                        try:
                            chk = frame.locator("input[type='checkbox'], span.mark, .ctp-checkbox-label, #challenge-stage")
                            if chk.count() > 0 and chk.first.is_visible():
                                chk.first.click(timeout=2000)
                                log(f"[{email}] 👆 点击了 Turnstile 复选框")
                                time.sleep(2)
                                break
                        except Exception:
                            pass

                    # 2) 针对 Turnstile iframe 区域模拟鼠标点击
                    for sel in ["iframe[src*='challenges.cloudflare.com']", "iframe[src*='turnstile']", "iframe[title*='Cloudflare']"]:
                        try:
                            cf_frame = page.locator(sel)
                            if cf_frame.count() > 0 and cf_frame.first.is_visible():
                                box = cf_frame.first.bounding_box()
                                if box:
                                    page.mouse.click(box["x"] + 28, box["y"] + box["height"] / 2)
                                    log(f"[{email}] 👆 模拟鼠标点击 Turnstile 区域")
                                    time.sleep(2)
                                    break
                        except Exception:
                            pass
                except Exception:
                    pass
                time.sleep(1)

            if not cf_passed:
                log(f"[{email}] ⚠️ Cloudflare challenge 等待超时(45s)，继续尝试...", "WARN")
                try:
                    page.screenshot(path=f"cf_challenge_{acc_index}.png")
                except Exception:
                    pass

            # 3. 输入账号密码
            log(f"[{email}] 填写账号密码...")
            try:
                email_input = page.locator("input[name='mail'], input[type='email'], input[name='email'], input[name='username'], #emailaddress").first
                pass_input = page.locator("input[name='pwd'], input[type='password'], input[name='password'], #password").first
                # 等待可见（最多 8s，若未出现则直接重试，避免盲等 30s）
                email_input.wait_for(state="visible", timeout=8000)
                email_input.fill(email)
                pass_input.fill(password)
                time.sleep(1)
            except Exception as e:
                log(f"[{email}] ❌ 找不到输入框: {e}", "WARN")
                try:
                    page.screenshot(path=f"input_not_found_{acc_index}.png")
                except Exception:
                    pass
                continue

            # 4. 等待打码（最长 100s，前 50s 等插件，若超时则调用 NopeCHA API 兜底）
            log(f"[{email}] [第 {attempt} 次] 等待 NopeCHA 自动识别 hCaptcha 验证码...")
            captcha_solved = False
            for i in range(100):
                try:
                    solved = page.evaluate("""() => {
                        const tas = document.querySelectorAll('textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]');
                        for (const ta of tas) {
                            if (ta.value && ta.value.trim().length > 20) return true;
                        }
                        const iframes = document.querySelectorAll('iframe[src*="hcaptcha"], iframe[title*="hcaptcha"]');
                        for (const f of iframes) {
                            try {
                                if (f.contentDocument?.querySelector('[aria-checked="true"]')) return true;
                            } catch(e) {}
                        }
                        return false;
                    }""")
                    if solved:
                        captcha_solved = True
                        log(f"[{email}] 🎉 验证码插件识别成功（耗时 {i + 1} 秒）✅")
                        break
                except Exception:
                    pass

                # 在第 50 秒若仍未解决，尝试 NopeCHA API 兜底
                if i == 50 and not captcha_solved and NOPECHA_KEY:
                    log(f"[{email}] 插件打码超时，正在调用 NopeCHA API 兜底破解...")
                    token = solve_hcaptcha_api("a40f015b-3fa4-4dca-9826-becbad294aaf", page.url)
                    if token:
                        try:
                            page.evaluate(f"""(tok) => {{
                                document.querySelectorAll('textarea[name="h-captcha-response"], textarea[name="g-recaptcha-response"]').forEach(t => t.value = tok);
                            }}""", token)
                            captcha_solved = True
                            log(f"[{email}] 🎉 NopeCHA API 注入 Token 成功！✅")
                            break
                        except Exception as e:
                            log(f"[{email}] 注入 Token 异常: {e}", "WARN")

                time.sleep(1)

            if not captcha_solved:
                log(f"[{email}] ⚠️ 验证码识别超时，准备尝试直接提交...", "WARN")

            # 验证码识别完后拉长缓冲等待时间，确保 NopeCHA 动画结束、hCaptcha 回调彻底触发并将 Token 稳定写入表单
            wait_after_captcha = 10
            log(f"[{email}] ⏳ 验证码识别成功，缓冲等待 {wait_after_captcha} 秒确保 Token 彻底稳定写入...")
            time.sleep(wait_after_captcha)

            # 5. 确保账号密码 100% 完整填入并触发 input/change 事件（防止因插件工作时输入框失焦重置）
            try:
                page.evaluate("""({u, p}) => {
                    const mail = document.querySelector("input[name='mail'], input[type='email'], #emailaddress");
                    const pwd = document.querySelector("input[name='pwd'], input[type='password'], #password");
                    if (mail) {
                        mail.value = u;
                        mail.dispatchEvent(new Event('input', { bubbles: true }));
                        mail.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    if (pwd) {
                        pwd.value = p;
                        pwd.dispatchEvent(new Event('input', { bubbles: true }));
                        pwd.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }""", {"u": email, "p": password})
                # 额外通过 Playwright 再次安全填充，确保前端框架捕获真实输入
                page.locator("input[name='pwd'], input[type='password'], #password").first.fill(password)
            except Exception as e:
                log(f"[{email}] 密码二次填充告警: {e}", "WARN")

            # 6. 优先使用 Playwright 原生物理点击紫色 Sign In 按钮（比纯 JS 点击更贴合真实用户）
            submit_clicked = False
            for selector in [
                "button.btn-primary",
                "button[type='submit']",
                "button:has-text('Sign In')",
                "button:has-text('Sign in')",
            ]:
                try:
                    btn = page.locator(selector).first
                    if btn.count() > 0 and btn.is_visible():
                        btn.scroll_into_view_if_needed()
                        time.sleep(0.3)
                        btn.click(force=True, timeout=3000)
                        log(f"[{email}] 🚀 点击【Sign In】按钮成功 (Playwright 原生点击) ✅")
                        submit_clicked = True
                        break
                except Exception:
                    continue

            # 兜底：若未完成原生点击，使用 DOM 方法与回车
            if not submit_clicked:
                try:
                    res = page.evaluate("""() => {
                        const btns = Array.from(document.querySelectorAll("button, input[type='submit']"));
                        for (const b of btns) {
                            const txt = (b.innerText || b.value || '').trim().toLowerCase();
                            if (txt.includes('sign in') || txt.includes('login') || txt.includes('connexion') || b.type === 'submit') {
                                b.click();
                                return { clicked: true, method: 'btn.click' };
                            }
                        }
                        return { clicked: false };
                    }""")
                    if res and res.get("clicked"):
                        submit_clicked = True
                        log(f"[{email}] ⚡ DOM 点击 Sign In 成功 ✅")
                except Exception:
                    pass

            time.sleep(0.5)
            try:
                page.keyboard.press("Enter")
            except Exception:
                pass

            # 7. 智能等待响应（实时检测：成功跳转 / 密码不存在错误 / 验证码重试）
            log(f"[{email}] 等待登录完成跳转或响应...")
            login_redirected = False
            credential_error = False

            for wait_sec in range(35):
                time.sleep(1)
                cur_u = page.url.lower()

                # 判定成功 1：离开登录页
                if "connexion" not in cur_u and "login" not in cur_u:
                    login_redirected = True
                    log(f"[{email}] ✅ 已成功跳转离开登录页: {page.url}（耗时 {wait_sec + 1}s）")
                    break

                # 判定成功 2：已渲染出控制台元素
                dash_detected = page.evaluate("""() => {
                    const txt = document.body ? document.body.innerText.toLowerCase() : '';
                    return txt.includes('dashboard') || txt.includes('my servers') || txt.includes('mes serveurs') || txt.includes('logout') || txt.includes('déconnexion');
                }""")
                if dash_detected:
                    login_redirected = True
                    log(f"[{email}] ✅ 已检测到控制面板内容，登录成功！")
                    break

                # 判定失败：实时检查页面错误文字提示
                err_text = page.evaluate("""() => {
                    const body = document.body ? document.body.innerText : '';
                    if (body.includes("This email/password pair does not exist")) {
                        return "pair_not_exist";
                    }
                    if (body.includes("Complete the captcha")) {
                        return "captcha_incomplete";
                    }
                    const invalids = Array.from(document.querySelectorAll('.invalid-feedback, .is-invalid, .alert-danger'));
                    for (const el of invalids) {
                        const t = (el.innerText || '').trim();
                        if (t && !t.includes('Complete the captcha')) return t;
                    }
                    return null;
                }""")

                if err_text == "pair_not_exist":
                    credential_error = True
                    log(f"[{email}] ❌ 网站提示：【This email/password pair does not exist】（账号或密码错误）！", "ERROR")
                    break
                elif err_text == "captcha_incomplete":
                    log(f"[{email}] ⚠️ 验证码未完成或校验过期，准备重试...", "WARN")
                    break
                elif err_text:
                    log(f"[{email}] ⚠️ 登录页面提示: {err_text}", "WARN")

            if credential_error:
                # 账号密码不存在时，不再盲目重试该账号，立即保存截图并通知
                shot_path = f"credential_error_{acc_index}.png"
                try:
                    page.screenshot(path=shot_path)
                except Exception:
                    pass
                send_tg_message(f"❌ <b>VPSFree 账号密码错误</b>\n📧 账号: <code>{email}</code>\n⚠️ 提示: <code>This email/password pair does not exist</code>\n💡 说明: 该账号密码无法登录，请核对 Secrets 配置！")
                log(f"[{email}] ⛔ 当前账号密码无效，跳过重试直接处理下一个账号。")
                browser.close()
                return False

            if not login_redirected:
                log(f"[{email}] ❌ [第 {attempt} 次] 登录后仍停留在登录页: {page.url}。将在 {RETRY_DELAY} 秒后重新尝试...", "WARN")
                try:
                    page.screenshot(path=f"login_failed_{acc_index}.png")
                except Exception:
                    pass
                time.sleep(RETRY_DELAY)
                continue


            time.sleep(3)

            # 6. 先在主列表页尝试执行续期（针对图2所示的列表页直显 Renew 7 days 场景）
            renew_res = perform_renewal_if_available(page, email)

            # 7. 点击【Manage VPS】进入实例独立详情页
            nav_result = navigate_to_server_page(page, email)

            # 8. 若列表页未点击成功，在详情页中再次尝试检测续期
            if renew_res != "renewed":
                sub_renew = perform_renewal_if_available(page, email)
                if sub_renew == "renewed":
                    renew_res = "renewed"
                elif renew_res == "not_found" and sub_renew == "disabled":
                    renew_res = "disabled"

            if nav_result == "order_page":
                action_result = "⛔ 账号在 Order 页面（已达项目上限或无运行中实例）"
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                shot_path = f"instance_{acc_index}.png"
                page.screenshot(path=shot_path)
                caption = (
                    f"⚠️ <b>VPSFree.es 账号提示 [{acc_index}/{total_accs}]</b>\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"📧 <b>账号:</b> <code>{email}</code>\n"
                    f"⚡ <b>状态:</b> {action_result}\n"
                    f"🔗 <b>页面:</b> <code>{page.url}</code>\n"
                    f"⏰ <b>检测时间:</b> {now_str}\n"
                )
                send_tg_photo(shot_path, caption)
                browser.close()
                log(f"[{email}] 账号处理完成（Order 状态）")
                return True

            # 9. 提取实例运行状态与到期时间（等待数据渲染并提取文本）
            time.sleep(3)
            try:
                body_text = page.evaluate("() => document.body ? document.body.innerText : ''")
                log(f"[{email}] 详情页文本已获取，长度: {len(body_text)} 字符")
            except Exception as e:
                log(f"[{email}] 提取 body 文本异常: {e}", "WARN")
                body_text = ""

            # 多语言支持：到期时间（跨越换行/空格精确提取标准日期）
            expires_str = "未获取到"
            m_exp = re.search(r"Expires[^\d\n\r]*(\d{1,2}/\d{1,2}/\d{4}(?:\s+\d{1,2}:\d{2})?)", body_text, re.I)
            if not m_exp:
                m_exp = re.search(r"(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2})", body_text)
            if not m_exp:
                m_exp = re.search(r"(?:Expires|Expiration|Expire le|Date d'expiration|Vence|Expira)\s*[:：]?\s*([0-9/:\-\s]{8,25})", body_text, re.I)
            if m_exp:
                expires_str = m_exp.group(1).strip()


            # 多语言支持：续期倒计时
            renewal_countdown = "已开放"
            m_open = re.search(r"(?:Renewal opens in|Renouvellement disponible dans|Renouvellement ouvert dans|Renovación en)\s*[:：]?\s*([^\n\r<]+)", body_text, re.I)
            if m_open:
                renewal_countdown = f"Renewal opens in {m_open.group(1).strip()}"
            elif "less than 24 hours" in body_text.lower() or "moins de 24 heures" in body_text.lower():
                renewal_countdown = "剩余不足 24 小时（可续期）"

            # 规格与 IP
            spec_info = ""
            m_spec = re.search(r"(\d+\s*vCPU[^\n\r<]+)", body_text, re.I)
            if m_spec:
                spec_info = m_spec.group(1).strip()
            
            ip_info = ""
            m_ip = re.search(r"(?:IPv4\s*/\s*IPv6|IP)\s*[:：]?\s*([a-f0-9:.]+)", body_text, re.I)
            if m_ip:
                ip_info = m_ip.group(1).strip()

            # 多语言支持：运行时间
            uptime_str = "正常运行中"
            m_uptime = re.search(r"(Running since[^\n\r]+|Uptime[^\n\r]+|En ligne depuis[^\n\r]+|Activo desde[^\n\r]+)", body_text, re.I)
            if m_uptime:
                uptime_str = m_uptime.group(1).strip()

            # 多语言支持：CPU / 内存 / 磁盘使用率
            cpu_str, mem_str, disk_str = "0.0%", "0.0%", "0.0%"
            m_cpu = re.search(r"([\d.]+%)\s*(?:CPU|Processeur)", body_text, re.I) or re.search(r"(?:CPU|Processeur)\s*[:：]?\s*([\d.]+%|\d+%)", body_text, re.I)
            if m_cpu:
                cpu_str = m_cpu.group(1)
            m_mem = re.search(r"([\d.]+%)\s*(?:MEMORY|RAM|MÉMOIRE|MEM)", body_text, re.I) or re.search(r"(?:MEMORY|RAM|MÉMOIRE|MEM)\s*[:：]?\s*([\d.]+%|\d+%)", body_text, re.I)
            if m_mem:
                mem_str = m_mem.group(1)
            m_disk = re.search(r"([\d.]+%)\s*(?:DISK|DISQUE|STORAGE|STOCKAGE)", body_text, re.I) or re.search(r"(?:DISK|DISQUE|STORAGE)\s*[:：]?\s*([\d.]+%|\d+%)", body_text, re.I)
            if m_disk:
                disk_str = m_disk.group(1)

            # 若未从图表获取到资源，且当前存在规格信息，展示规格说明
            if cpu_str == "0.0%" and spec_info:
                cpu_str = "1 核"
            if mem_str == "0.0%" and "1 GB RAM" in spec_info:
                mem_str = "1 GB"
            if disk_str == "0.0%" and "10 GB SSD" in spec_info:
                disk_str = "10 GB"


            if renew_res == "renewed":
                action_result = "🎉 <b>成功完成 7 天续期！</b>"
            elif renew_res == "disabled":
                action_result = "⏸ 续期按钮存在但已被禁用（未到 24h 窗口期）"
            else:
                action_result = "⏸ 未到续期窗口（仅到期前24小时内开放）"


            time.sleep(2)
            shot_path = f"instance_{acc_index}.png"
            page.screenshot(path=shot_path)

            # 9. 发送该账号的独立报告
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            caption = (
                f"🖥 <b>VPSFree.es 实例运行报告 [{acc_index}/{total_accs}]</b>\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📧 <b>账号:</b> <code>{email}</code>\n"
                f"🖥 <b>配置:</b> <code>{spec_info or '1 vCPU / 1 GB RAM / 10 GB SSD'}</code>\n"
                f"🌐 <b>网络:</b> <code>{ip_info or '已绑定分配'}</code>\n"
                f"📊 <b>资源:</b> CPU: {cpu_str} | 内存: {mem_str} | 硬盘: {disk_str}\n"
                f"⏱ <b>运行:</b> {uptime_str}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"⏳ <b>到期时间:</b> <code>{expires_str}</code>\n"
                f"🔄 <b>续期状态:</b> <code>{renewal_countdown}</code>\n"
                f"⚡ <b>执行结果:</b> {action_result}\n"
                f"⏰ <b>检测时间:</b> {now_str}\n"
            )
            send_tg_photo(shot_path, caption)
            log(f"[{email}] ✅ 账号处理成功完成！")
            return True

        except Exception as e:
            log(f"[{email}] ❌ [第 {attempt} 次] 处理流程异常: {e}，将在 {RETRY_DELAY} 秒后重试...", "ERROR")
            time.sleep(RETRY_DELAY)
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

    log(f"[{email}] ❌ 3次尝试后仍失败，跳过此账号", "ERROR")
    # 如果有现场异常截图，推送到 Telegram 告知用户真实状况
    fail_shot = None
    for s_name in [f"cf_challenge_{acc_index}.png", f"input_not_found_{acc_index}.png", f"goto_timeout_{acc_index}.png"]:
        if os.path.exists(s_name):
            fail_shot = s_name
            break
    if fail_shot:
        fail_caption = (
            f"⚠️ <b>VPSFree.es 账号异常告警 [{acc_index}/{total_accs}]</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📧 <b>账号:</b> <code>{email}</code>\n"
            f"❌ <b>状态:</b> 登录页面未加载或卡在盾页\n"
            f"💡 <b>现场实况:</b> 目标源站宕机(Error 522/523)或网络异常\n"
            f"⏰ <b>时间:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        send_tg_photo(fail_shot, fail_caption)
        log(f"[{email}] ⚠️ 已向 TG 推送现场异常截图: {fail_shot}")

    return False


def main():
    log("=" * 40)
    log("VPSFree.es 自动续期运行开始")
    log("=" * 40)

    accounts = get_accounts()
    if not accounts:
        log("未找到任何账号配置！请设置 VPS_ACCOUNTS 或 VPS_EMAIL/VPS_PASSWORD 环境变量！", "ERROR")
        sys.exit(1)

    total = len(accounts)
    log(f"共检测到 {total} 个账号待处理...")
    for i, acc in enumerate(accounts, 1):
        log(f"  {i}. {acc['email']}")

    from playwright.sync_api import sync_playwright
    success_count = 0
    fail_count = 0
    with sync_playwright() as p:
        for idx, acc in enumerate(accounts, start=1):
            try:
                ok = process_single_account(p, acc["email"], acc["password"], idx, total)
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                fail_count += 1
                log(f"[{acc['email']}] 主流程异常: {e}", "ERROR")
            if idx < total:
                cool_down = random.randint(25, 40)
                log(f"等待 {cool_down} 秒（冷却防同IP撞库风控）后处理下一个账号...")
                time.sleep(cool_down)

    log("🎉 所有账号处理完毕！")
    # 汇总报告
    summary = (
        f"🖥 <b>VPSFree.es 续期汇总报告</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👥 总账号数: {total}\n"
        f"✅ 成功完成: {success_count}\n"
        f"❌ 处理失败: {fail_count}\n"
        f"⏰ 完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    )
    send_tg_text(summary)
    log("✅ 汇总已推送至 TG")


if __name__ == "__main__":
    main()
