import os
import asyncio
import logging

import html2text
from playwright.async_api import async_playwright

from config import QWEN_URL, QWEN_TIMEOUT, QWEN_PROFILE_DIR
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
    "#chat-message-container .markdown-body",
    ".response-message-content.phase-answer",
    ".qwen-markdown",
    ".markdown-body",
    ".ant-typography",
)

QWEN_STOP_BTN = "button:has(use[*|href='#icon-fill-stop-011']), .icon-fill-stop-011"

QWEN_THINKING_SELECTORS = (
    "[class*='thinking-status']",
    "[class*='ThinkingStatus']",
    ".qwen-chat-thinking-status-card-title-text",
)

SUMMARY_PROMPT = (
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


async def _extract_html_md(locator) -> str:
    html = await locator.inner_html()
    md = _html_converter.handle(html).strip()
    return md


async def generate_summary(transcription: str, video_title: str | None = None) -> str:
    prompt = SUMMARY_PROMPT.format(text=transcription)
    try:
        text = await asyncio.wait_for(_query_qwen(prompt), timeout=QWEN_TIMEOUT + 30)
    except asyncio.TimeoutError:
        logger.error("Qwen query timed out")
        return get("qwen.timeout")
    return text


async def _query_qwen(prompt: str) -> str:
    os.makedirs(QWEN_PROFILE_DIR, exist_ok=True)
    _clean_lock_files()

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=QWEN_PROFILE_DIR,
            headless=False,
            viewport={"width": 1920, "height": 1600},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
            ignore_default_args=["--enable-automation"],
            color_scheme="light",
        )

        page = await context.new_page()

        try:
            logger.info("Navigating to Qwen AI...")
            await page.goto(QWEN_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)

            login_btn = page.locator(
                "button:has-text('Log in'), "
                "button:has-text('Sign in'), "
                ".auth-button-ui.login"
            ).first
            if await login_btn.is_visible(timeout=3000):
                logger.warning("Qwen login page detected, but continuing anyway...")

            input_sel = QWEN_INPUT_SELECTOR
            try:
                await page.wait_for_selector(input_sel, timeout=15000)
            except Exception:
                input_sel = "textarea, div[contenteditable='true']"
                await page.wait_for_selector(input_sel, timeout=10000)

            input_field = page.locator(input_sel).first
            await input_field.click()
            await input_field.fill(prompt)
            await asyncio.sleep(1)

            send_button = page.locator(
                "button[aria-label='Send Message'], "
                "button:has(.anticon-send), "
                ".chat-prompt-send-button button, "
                "button:has(.send-icon)"
            ).first
            send_visible = await send_button.is_visible()
            send_enabled = await send_button.is_enabled()
            logger.info(f"Send button visible={send_visible}, enabled={send_enabled}")
            if send_visible and send_enabled:
                logger.info("Clicking send button...")
                await send_button.click()
            else:
                logger.info("Send button not visible/enabled, pressing Enter...")
                await page.keyboard.press("Enter")
                await asyncio.sleep(1)
                await page.keyboard.press("Enter")

            await asyncio.sleep(2)

            logger.info("Waiting for Qwen response...")
            last_text = ""
            stable_count = 0
            rechecked_send = False
            regenerate_clicked = False

            for attempt in range(QWEN_TIMEOUT * 2):
                try:
                    body_text = await page.evaluate("() => document.body.innerText")
                    if "Requests rate limit exceeded" in body_text:
                        logger.critical("Qwen rate limit detected!")
                        return get("qwen.rate_limit")
                except Exception:
                    await asyncio.sleep(0.5)
                    continue

                if not regenerate_clicked:
                    for sel in QWEN_THINKING_SELECTORS:
                        interrupted = page.locator(sel).filter(has_text="прерван").first
                        if await interrupted.is_visible(timeout=100):
                            logger.warning("Detected 'Мысль прервана', clicking regenerate...")
                            regen_btn = page.locator(
                                ".qwen-chat-package-comp-new-action-control-container-regenerate"
                            ).first
                            if await regen_btn.is_visible(timeout=2000):
                                await regen_btn.click()
                                regenerate_clicked = True
                                await asyncio.sleep(1)
                                break
                        if regenerate_clicked:
                            break

                if attempt == 20 and not rechecked_send:
                    rechecked_send = True
                    is_generating = await page.locator(QWEN_STOP_BTN).first.is_visible(timeout=200)
                    if not is_generating:
                        if await send_button.is_visible(timeout=1000) and await send_button.is_enabled(timeout=1000):
                            logger.warning("Send button still visible, clicking again...")
                            await send_button.click()
                            await asyncio.sleep(2)

                is_generating = await page.locator(QWEN_STOP_BTN).first.is_visible(timeout=100)

                text = ""
                for sel in QWEN_RESPONSE_SELECTORS:
                    try:
                        loc = page.locator(sel).last
                        if await loc.is_visible(timeout=50):
                            t = await _extract_html_md(loc)
                            if len(t) > 20:
                                text = t
                                break
                    except Exception:
                        continue

                if not text:
                    try:
                        last_msg = page.locator(
                            "[class*='message'], [class*='Message'], [class*='chat-item']"
                        ).last
                        if await last_msg.is_visible(timeout=100):
                            t = await _extract_html_md(last_msg)
                            if len(t) > 20:
                                text = t
                    except Exception:
                        pass

                if text:
                    if text == last_text and not is_generating:
                        stable_count += 1
                        if stable_count >= 10:
                            logger.info("Qwen response stable, returning")
                            return text
                    elif text != last_text:
                        stable_count = 0
                        last_text = text

                if attempt % 40 == 0:
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


def _clean_lock_files():
    for fname in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        fpath = os.path.join(QWEN_PROFILE_DIR, fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
            except OSError:
                pass
