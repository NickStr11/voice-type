from __future__ import annotations

import sys
import time

from voice_type.telegram_web import TelegramWebAuthRequired, TelegramWebExecutor


def main() -> int:
    message = sys.argv[1] if len(sys.argv) > 1 else f"VoiceType smoke {time.strftime('%Y-%m-%d %H:%M:%S')}"
    executor = TelegramWebExecutor()

    try:
        print("step: opening telegram web")
        executor.open_telegram()

        if executor.is_logged_out():
            print("step: telegram web requires manual login")
            input("Залогинься в Telegram Web в открытом окне и нажми Enter...")

        print("step: opening Saved Messages")
        executor.open_saved_messages()

        print("step: sending message")
        executor.send_message_to_saved(message)

        print("step: verifying message")
        executor.verify_message(message)

        print(f"ok: message verified -> {message}")
        return 0
    except TelegramWebAuthRequired as exc:
        artifact = executor.save_failure_artifacts()
        print(f"fail: {exc}")
        print(f"artifact: {artifact}")
        return 1
    except Exception as exc:
        artifact = executor.save_failure_artifacts()
        print(f"fail: {exc}")
        print(f"artifact: {artifact}")
        return 1
    finally:
        executor.close()


if __name__ == "__main__":
    raise SystemExit(main())
