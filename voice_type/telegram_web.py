from __future__ import annotations

import re
import time
from pathlib import Path

from loguru import logger
from playwright.sync_api import BrowserContext, Locator, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = PROJECT_ROOT / "runtime" / "playwright"
PROFILE_DIR = RUNTIME_DIR / "telegram-profile"
FAILURES_DIR = RUNTIME_DIR / "failures"
TELEGRAM_URL = "https://web.telegram.org/a/"
SAVED_MESSAGES_RE = re.compile(
    r"Saved Messages|Избранное|Сохраненные сообщения|Сохранённые сообщения",
    re.IGNORECASE,
)
LOGIN_HINT_RE = re.compile(
    r"QR|Ваш номер телефона|Your phone number|Log in|Войти|Continue in English",
    re.IGNORECASE,
)


class TelegramWebError(RuntimeError):
    pass


class TelegramWebAuthRequired(TelegramWebError):
    pass


class TelegramWebExecutor:
    def __init__(self, profile_dir: Path | None = None, headless: bool = False) -> None:
        self._profile_dir = profile_dir or PROFILE_DIR
        self._headless = headless
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def open_saved_messages(self) -> None:
        self.open_chat("Saved Messages")

    def open_chat(self, chat_name: str) -> None:
        page = self._page_or_raise()
        self._open_telegram(page)
        self._ensure_authenticated(page)
        self._open_chat_impl(page, chat_name)

    def send_message(self, chat_name: str, message: str) -> None:
        page = self._page_or_raise()
        self._open_telegram(page)
        self._ensure_authenticated(page)
        self._open_chat_impl(page, chat_name)
        self._send_message(page, message)
        self._verify_message(page, message)

    def send_message_to_saved(self, message: str) -> None:
        page = self._page_or_raise()
        self._open_telegram(page)
        self._ensure_authenticated(page)
        self._open_chat_impl(page, "Saved Messages")
        self._send_message(page, message)
        self._verify_message(page, message)

    def send_image(self, chat_name: str, image_path: Path) -> None:
        page = self._page_or_raise()
        self._open_telegram(page)
        self._ensure_authenticated(page)
        self._open_chat_impl(page, chat_name)
        self._upload_image(page, image_path)

    def send_image_to_saved(self, image_path: Path) -> None:
        self.send_image("Saved Messages", image_path)

    def read_last_messages(self, chat_name: str, count: int = 5) -> list[str]:
        page = self._page_or_raise()
        self._open_telegram(page)
        self._ensure_authenticated(page)
        self._open_chat_impl(page, chat_name)
        messages = self._collect_visible_message_texts(page)
        return messages[-max(1, count):]

    def search_messages(self, chat_name: str, query: str, limit: int = 5) -> list[str]:
        page = self._page_or_raise()
        self._open_telegram(page)
        self._ensure_authenticated(page)
        self._open_chat_impl(page, chat_name)
        self._open_chat_search(page, query)
        matches = [
            message
            for message in self._collect_visible_message_texts(page)
            if query.casefold() in message.casefold()
        ]
        return matches[-max(1, limit):]

    def open_telegram(self) -> None:
        page = self._page_or_raise()
        self._open_telegram(page)

    def is_logged_out(self) -> bool:
        return self._looks_logged_out(self._page_or_raise())

    def verify_message(self, message: str) -> None:
        self._verify_message(self._page_or_raise(), message)

    def save_failure_artifacts(self) -> Path:
        return self._save_failure_artifacts(self._page_or_raise())

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
            self._page = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def _page_or_raise(self) -> Page:
        if self._page is None:
            self._ensure_started()
        if self._page is None:
            raise TelegramWebError("Telegram Web browser page is not available")
        return self._page

    def _ensure_started(self) -> None:
        if self._page is not None:
            return

        self._profile_dir.mkdir(parents=True, exist_ok=True)
        FAILURES_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            str(self._profile_dir),
            headless=self._headless,
            viewport={"width": 1440, "height": 960},
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def _open_telegram(self, page: Page) -> None:
        page.goto(TELEGRAM_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

    def _ensure_authenticated(self, page: Page) -> None:
        if self._looks_logged_out(page):
            raise TelegramWebAuthRequired(
                "Telegram Web is not authenticated. Run telegram_web_smoke.py once and log in manually."
            )

    def _looks_logged_out(self, page: Page) -> bool:
        if self._find_sidebar_search_box(page) is not None:
            return False
        return page.get_by_text(LOGIN_HINT_RE).first.is_visible()

    def _open_saved_messages_impl(self, page: Page) -> None:
        direct_result = page.locator("a.ListItem-button").filter(has=page.get_by_text(SAVED_MESSAGES_RE)).first
        if direct_result.is_visible():
            direct_result.click()
            page.wait_for_timeout(800)
        else:
            search_box = self._find_sidebar_search_box(page)
            if search_box is None:
                raise TelegramWebError("Telegram sidebar search box not found")

            search_box.click()
            search_box.fill("")
            search_box.fill("Saved")

            result = page.locator("a.ListItem-button").filter(has=page.get_by_text(SAVED_MESSAGES_RE)).first
            try:
                result.wait_for(state="visible", timeout=8000)
            except PlaywrightTimeoutError as exc:
                raise TelegramWebError("Saved Messages was not found in Telegram search") from exc

            result.click()
            page.wait_for_timeout(800)

        composer = self._find_composer_box(page)
        if composer is None:
            raise TelegramWebError("Saved Messages chat did not open")

    def _open_chat_impl(self, page: Page, chat_name: str) -> None:
        visible_chat = self._find_chat_result(page, chat_name, timeout_ms=500)
        if visible_chat is not None:
            self._click_chat_result(page, visible_chat)
            composer = self._find_composer_box(page)
            if composer is not None:
                return

        search_box = self._find_sidebar_search_box(page)
        if search_box is None:
            raise TelegramWebError("Telegram sidebar search box not found")

        search_query = self._normalize_chat_query(chat_name)
        search_box.click()
        search_box.fill("")
        search_box.fill(search_query)

        result = self._find_chat_result(page, search_query)
        if result is None:
            raise TelegramWebError(f"Telegram chat not found: {chat_name}")

        self._click_chat_result(page, result)

        composer = self._find_composer_box(page)
        if composer is None:
            raise TelegramWebError(f"Telegram chat did not open: {chat_name}")

    def _find_chat_result(self, page: Page, chat_name: str, timeout_ms: int = 8000) -> Locator | None:
        patterns = self._chat_patterns(chat_name)
        deadline = time.time() + (timeout_ms / 1000)
        while time.time() < deadline:
            for pattern in patterns:
                candidate = page.locator("a.ListItem-button").filter(has=page.get_by_text(pattern)).first
                if candidate.is_visible():
                    return candidate
            page.wait_for_timeout(250)
        return None

    def _click_chat_result(self, page: Page, result: Locator) -> None:
        try:
            result.click(timeout=3000)
        except PlaywrightTimeoutError:
            page.wait_for_timeout(700)
            result.click(force=True, timeout=3000)
        page.wait_for_timeout(800)

    def _send_message(self, page: Page, message: str) -> None:
        composer = self._find_composer_box(page)
        if composer is None:
            raise TelegramWebError("Telegram composer was not found")

        composer.click()
        page.keyboard.type(message)
        page.keyboard.press("Enter")
        page.wait_for_timeout(700)

    def _upload_image(self, page: Page, image_path: Path) -> None:
        attach_button = page.get_by_role("button", name="Add an attachment")
        attach_button.click()
        with page.expect_file_chooser() as file_chooser_info:
            page.get_by_role("menuitem", name="Photo or Video").click()
        file_chooser_info.value.set_files(str(image_path))
        page.wait_for_timeout(1200)
        page.get_by_role("button", name="Send").click()
        page.wait_for_timeout(1800)

        cancel_button = page.get_by_role("button", name="Cancel attachments")
        if cancel_button.count():
            raise TelegramWebError("Telegram image upload preview did not close after send")

    def _verify_message(self, page: Page, message: str) -> None:
        try:
            page.get_by_text(message, exact=True).last.wait_for(state="visible", timeout=8000)
        except PlaywrightTimeoutError as exc:
            raise TelegramWebError("Sent message was not found in message list") from exc

    def _open_chat_search(self, page: Page, query: str) -> None:
        page.get_by_role("button", name="Search this chat").click()
        page.wait_for_timeout(400)
        search_box = self._find_chat_search_box(page)
        if search_box is None:
            raise TelegramWebError("Telegram chat search box not found")
        search_box.click()
        search_box.fill("")
        search_box.fill(query)
        page.wait_for_timeout(1200)

    def _find_chat_search_box(self, page: Page) -> Locator | None:
        candidates = page.locator('input[placeholder="Search"]')
        count = candidates.count()
        ranked: list[tuple[float, int]] = []

        for index in range(count):
            candidate = candidates.nth(index)
            if not candidate.is_visible():
                continue
            box = candidate.bounding_box()
            if box is None:
                continue
            if box["x"] >= 520:
                ranked.append((box["x"], index))

        if not ranked:
            return None

        ranked.sort(reverse=True)
        return candidates.nth(ranked[0][1])

    def _collect_visible_message_texts(self, page: Page) -> list[str]:
        items = page.locator('[class*="text-content"]')
        count = items.count()
        if count == 0:
            return []

        texts: list[str] = []
        last_normalized = ""
        for index in range(max(0, count - 40), count):
            item = items.nth(index)
            if not item.is_visible():
                continue
            text = item.inner_text(timeout=1000).strip()
            if not text:
                continue
            normalized = re.sub(r"\s+", " ", text).strip()
            if not normalized or normalized == last_normalized:
                continue
            texts.append(normalized)
            last_normalized = normalized
        return texts

    def _find_sidebar_search_box(self, page: Page) -> Locator | None:
        candidates = [
            page.locator("#telegram-search-input").first,
            page.locator('input[placeholder="Search"]').first,
            page.locator('input.form-control').first,
        ]
        for candidate in candidates:
            if candidate.is_visible():
                return candidate
        return None

    def _find_composer_box(self, page: Page) -> Locator | None:
        return self._pick_contenteditable(page, side="right")

    def _pick_contenteditable(self, page: Page, side: str) -> Locator | None:
        candidates = page.locator('[contenteditable="true"]')
        count = candidates.count()
        ranked: list[tuple[float, int]] = []

        for index in range(count):
            candidate = candidates.nth(index)
            if not candidate.is_visible():
                continue
            box = candidate.bounding_box()
            if box is None:
                continue

            if side == "left" and box["x"] < 520:
                ranked.append((box["y"], index))
            if side == "right" and box["x"] >= 520:
                ranked.append((-box["y"], index))

        if not ranked:
            return None

        ranked.sort()
        return candidates.nth(ranked[0][1])

    def _normalize_chat_query(self, chat_name: str) -> str:
        normalized = re.sub(r"^\s*(?:чат(?:\s+с)?|диалог(?:\s+с)?)\s+", "", chat_name, flags=re.IGNORECASE)
        normalized = re.sub(r"\s+", " ", normalized).strip(" '\"")
        return normalized

    def _chat_patterns(self, chat_name: str) -> list[re.Pattern[str]]:
        variants = {chat_name, self._normalize_chat_query(chat_name)}
        patterns: list[re.Pattern[str]] = []
        for variant in variants:
            if not variant:
                continue
            patterns.append(re.compile(re.escape(variant), re.IGNORECASE))
        return patterns

    def _save_failure_artifacts(self, page: Page) -> Path:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        screenshot_path = FAILURES_DIR / f"telegram-smoke-{timestamp}.png"
        html_path = FAILURES_DIR / f"telegram-smoke-{timestamp}.html"
        page.screenshot(path=str(screenshot_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")
        logger.warning(f"Telegram Web failure artifact saved: {screenshot_path}")
        return screenshot_path
