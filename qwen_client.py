import os
import asyncio
import logging

import html2text
from playwright.async_api import async_playwright

from config import (
    QWEN_URL,
    QWEN_TIMEOUT,
    QWEN_PROFILE_DIR,
    QWEN_MAX_PROMPT_CHARS,
    QWEN_PROXY,
    QWEN_USER_AGENT,
    QWEN_CHROME_ARGS,
)
from proxy_utils import socks5_health
from messages import get

_html_converter = html2text.HTML2Text()
_html_converter.body_width = 0
_html_converter.ignore_links = False
_html_converter.ignore_images = False
_html_converter.ignore_emphasis = False
_html_converter.protect_links = True
_html_converter.unicode_snob = True
_html_converter.skip_internal_links = True
_html_converter.wrap_links = False

logger = logging.getLogger(__name__)

QWEN_INPUT_SELECTOR = (
    ".message-input-textarea, "
    ".ant-input, "
    "textarea[placeholder*='Qwen'], "
    "#chat-input, "
    "textarea"
)

QWEN_RESPONSE_SELECTORS = (
    ".response-message-content.phase-answer",
    ".qwen-markdown",
    ".markdown-body",
    ".ant-typography",
    "#chat-message-container .markdown-body",
)

QWEN_STOP_BTN = (
    "button:has(use[*|href='#icon-fill-stop-011']), "
    "button.stop-button, "
    ".anticon-stop, "
    "button:has-text('Stop'), "
    ".chat-input-stop"
)

QWEN_SEND_BTN = (
    ".send-button:has(use[*|href='#icon-line-arrow-up']), "
    ".chat-prompt-send-button button, "
    "button[aria-label='Send Message'], "
    "button:has(.anticon-send), "
    "button:has(.send-icon), "
    ".chat-input-send"
)

STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    if (!navigator.plugins.length) {
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }
            ]
        });
    }
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en', 'ru-RU', 'ru'] });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Google Inc. (Intel)';
        if (parameter === 37446) return 'ANGLE (Intel, Intel(R) HD Graphics 620 (0x00005916) Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return getParameter.apply(this, arguments);
    };
    if (window.WebGL2RenderingContext) {
        WebGL2RenderingContext.prototype.getParameter = WebGLRenderingContext.prototype.getParameter;
    }
    if (!window.chrome) {
        window.chrome = {
            runtime: {},
            app: { isInstalled: false, installState: () => {}, getDetails: () => {}, getIsInstalled: () => {} },
            csi: () => {},
            loadTimes: () => {}
        };
    }
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );
"""

SUMMARY_PROMPT_RU = (
    "Составь подробную заметку-конспект на русском языке. Используй Markdown, совместимый с Obsidian.\n\n"
    "Заголовок: придумай сам, исходя из смысла транскрибации.\n\n"
    "Требования к форматированию:\n"
    "- Заголовки с эмодзи: ## 🎯 ..., ## 📋 ..., ## ✅ ..., ## 🔧 ..., ## 📝 ..., ## 💡 ..., ## 🔗 ...\n"
    "- Используй Obsidian-коллауты: > [!note], > [!tip], > [!important], > [!warning], > [!example], > [!summary]\n"
    "- Таблицы для сравнений, списков характеристик, сводок\n"
    "- Чек-листы: - [ ] / - [x]\n"
    "- Кодовые блоки ```...``` где уместно\n"
    "- Разделители --- между крупными секциями\n"
    "- Пустые строки после заголовков и между блоками\n"
    "- Выделяй ключевые термины **жирным**\n\n"
    "Чего НЕ делать:\n"
    "- Не добавляй YAML-метаданные (tags, date, source, status)\n"
    "- Не добавляй нумерацию вроде \"1 2 3\" в начале строк\n"
    "- Не добавляй лишний служебный текст и пояснения вне структуры\n\n"
    "Структура:\n"
    "1. **Краткое введение/контекст** — о чём видео, 2-3 предложения\n"
    "2. **Основные разделы** — логически разбивай на подтемы с заголовками\n"
    "3. **Ключевые инсайты** — важные выводы, правила, принципы\n"
    "4. **Практические советы** — конкретные рекомендации, шаги, инструменты\n"
    "5. **Итог** — краткое резюме, главная мысль\n\n"
    "Транскрибация:\n{text}"
)

SUMMARY_PROMPT_EN = (
    "Write a detailed summary/notes in English. Use Markdown compatible with Obsidian.\n\n"
    "Title: come up with your own based on the transcription.\n\n"
    "Formatting requirements:\n"
    "- Headers with emoji: ## 🎯 ..., ## 📋 ..., ## ✅ ..., ## 🔧 ..., ## 📝 ..., ## 💡 ..., ## 🔗 ...\n"
    "- Use Obsidian callouts: > [!note], > [!tip], > [!important], > [!warning], > [!example], > [!summary]\n"
    "- Tables for comparisons, feature lists, summaries\n"
    "- Checklists: - [ ] / - [x]\n"
    "- Code blocks ```...``` where appropriate\n"
    "- Separators --- between major sections\n"
    "- Blank lines after headers and between blocks\n"
    "- Highlight key terms in **bold**\n\n"
    "What NOT to do:\n"
    "- Do not add YAML metadata (tags, date, source, status)\n"
    "- Do not add numbering like \"1 2 3\" at the start of lines\n"
    "- Do not add extra service text or explanations outside the structure\n\n"
    "Structure:\n"
    "1. **Brief introduction/context** — what the video is about, 2-3 sentences\n"
    "2. **Main sections** — logically split into subtopics with headers\n"
    "3. **Key insights** — important takeaways, rules, principles\n"
    "4. **Practical tips** — concrete recommendations, steps, tools\n"
    "5. **Conclusion** — a brief summary, the main idea\n\n"
    "Transcription:\n{text}"
)

SUMMARY_PROMPTS = {"ru": SUMMARY_PROMPT_RU, "en": SUMMARY_PROMPT_EN}


async def generate_summary(transcription: str, video_title: str | None = None, lang: str = "ru") -> str:
    prompt = SUMMARY_PROMPTS.get(lang, SUMMARY_PROMPT_RU).format(text=transcription)
    if len(prompt) > QWEN_MAX_PROMPT_CHARS:
        logger.error(f"Prompt too large for Qwen: {len(prompt)} chars")
        return "ERROR: Prompt exceeds Qwen character limit."
    try:
        text = await asyncio.wait_for(_query_qwen(prompt), timeout=QWEN_TIMEOUT + 30)
    except asyncio.TimeoutError:
        logger.error("Qwen query timed out")
        return get("qwen.timeout")
    return text


async def _query_qwen(prompt: str) -> str:
    os.makedirs(QWEN_PROFILE_DIR, exist_ok=True)
    _clean_lock_files()

    launch_kwargs = dict(
        user_data_dir=QWEN_PROFILE_DIR,
        headless=False,
        user_agent=QWEN_USER_AGENT,
        viewport={"width": 1920, "height": 1600},
        args=QWEN_CHROME_ARGS,
        ignore_default_args=["--enable-automation"],
        color_scheme="light",
    )
    if QWEN_PROXY:
        exit_ip = socks5_health(QWEN_PROXY)
        if exit_ip:
            logger.info(f"Using proxy for Qwen browser: {QWEN_PROXY} (exit IP: {exit_ip})")
            launch_kwargs["proxy"] = {"server": QWEN_PROXY}
        else:
            logger.warning(f"Proxy {QWEN_PROXY} unreachable, launching Qwen browser without it")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(**launch_kwargs)

        page = await context.new_page()
        await page.add_init_script(STEALTH_SCRIPT)

        try:
            logger.info("Navigating to Qwen AI...")
            await page.goto(QWEN_URL, wait_until="load", timeout=60000)
            await asyncio.sleep(2)

            input_sel = QWEN_INPUT_SELECTOR
            try:
                await page.wait_for_selector(input_sel, timeout=15000)
                input_ok = True
            except Exception:
                input_sel = "textarea, div[contenteditable='true']"
                try:
                    await page.wait_for_selector(input_sel, timeout=10000)
                    input_ok = True
                except Exception:
                    input_ok = False

            if not input_ok:
                login_btn = page.locator(
                    "button:has-text('Log in'), "
                    "button:has-text('Sign in'), "
                    ".auth-button-ui.login"
                ).first
                if await login_btn.is_visible(timeout=3000):
                    logger.warning("Qwen login page detected, waiting for session restore...")
                    for _ in range(10):
                        await asyncio.sleep(3)
                        try:
                            await page.wait_for_selector(input_sel, timeout=1000)
                            input_ok = True
                            break
                        except Exception:
                            pass
                    if not input_ok:
                        logger.critical("Qwen requires login; aborting instead of sending prompt into login page")
                        return get("qwen.need_login")
                if not input_ok:
                    raise RuntimeError("Qwen chat input not found and no login page detected")

            input_field = page.locator(input_sel).first
            await input_field.click()
            await input_field.fill(prompt)
            await asyncio.sleep(1)

            send_button = page.locator(QWEN_SEND_BTN).first
            send_visible = await send_button.is_visible()
            send_enabled = await send_button.is_enabled()
            logger.info(f"Send button visible={send_visible}, enabled={send_enabled}")
            if send_visible and send_enabled:
                logger.info("Clicking send button...")
                await send_button.click()
            else:
                logger.info("Send button not visible/enabled, pressing Enter...")
                await page.keyboard.press("Enter")

            await asyncio.sleep(2)

            logger.info("Waiting for Qwen response...")
            last_text = ""
            stable_count = 0
            rechecked_send = False
            regenerate_clicked = False

            for attempt in range(QWEN_TIMEOUT * 2):
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=3000)
                except Exception:
                    pass
                try:
                    page_content = await page.content()
                except Exception:
                    await asyncio.sleep(0.5)
                    continue
                if "Requests rate limit exceeded" in page_content:
                    logger.critical("Qwen rate limit detected!")
                    return get("qwen.rate_limit")

                interrupted = page.locator(
                    ".qwen-chat-thinking-status-card-title-text:has-text('Мысль прервана')"
                ).first
                if await interrupted.is_visible(timeout=500):
                    if not regenerate_clicked:
                        logger.warning("Detected 'Мысль прервана', clicking regenerate...")
                        regenerate_button = page.locator(
                            ".qwen-chat-package-comp-new-action-control-container-regenerate"
                        ).first
                        if await regenerate_button.is_visible(timeout=5000):
                            await regenerate_button.click()
                            regenerate_clicked = True
                            await asyncio.sleep(1)

                if attempt == 40 and not rechecked_send:
                    rechecked_send = True
                    is_generating_now = await page.locator(QWEN_STOP_BTN).first.is_visible(
                        timeout=500
                    )
                    if is_generating_now:
                        logger.info("Generation already running, waiting...")
                    else:
                        if (
                            await send_button.is_visible(timeout=2000)
                            and await send_button.is_enabled(timeout=2000)
                        ):
                            logger.warning("Send button still available, clicking again...")
                            await send_button.click()
                        else:
                            has_content = False
                            for sel in QWEN_RESPONSE_SELECTORS:
                                loc = page.locator(sel).last
                                if await loc.is_visible(timeout=100):
                                    current_text = await loc.inner_text()
                                    if current_text and len(current_text.strip()) > 20:
                                        has_content = True
                                        break
                            if not has_content:
                                logger.warning("Generation did not start, pressing Enter again...")
                                await page.keyboard.press("Enter")

                is_generating = await page.locator(QWEN_STOP_BTN).first.is_visible(timeout=500)

                content = ""
                for sel in QWEN_RESPONSE_SELECTORS:
                    loc = page.locator(sel).last
                    try:
                        if await loc.is_visible(timeout=100):
                            t = await _extract_html_md(loc)
                            if t and len(t.strip()) > 20:
                                content = t
                                break
                    except Exception:
                        continue

                if content:
                    if content == last_text and not is_generating:
                        stable_count += 1
                        if stable_count >= 8:
                            logger.info("Qwen response complete, returning")
                            return content
                    elif content != last_text:
                        stable_count = 0
                        last_text = content

                if attempt % 20 == 0:
                    logger.info(f"Waiting for Qwen... ({attempt // 2}s)")

                await asyncio.sleep(0.5)

            if last_text:
                return last_text
            return get("qwen.no_response")

        except Exception as e:
            logger.error(f"Qwen error: {e}")
            return f"ERROR: {e}"

        finally:
            await context.close()


async def _extract_html_md(locator) -> str:
    """Return the locator's inner HTML converted to markdown text."""
    html = await locator.evaluate("el => el.innerHTML")
    return _html_converter.handle(html).strip()


def _clean_lock_files():
    for fname in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        fpath = os.path.join(QWEN_PROFILE_DIR, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass
