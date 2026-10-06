import atexit
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml

from . import db

logger = logging.getLogger("audit_to_db")

_CONFIG_PATH = Path(__file__).parent / "audit_to_db.yaml"
_DEFAULT_MAX_ARG_LENGTH = 200
MAX_ERROR_LENGTH = 80
_tool_args: dict = {}
_max_arg_length: int = _DEFAULT_MAX_ARG_LENGTH


def _load_config() -> None:
    global _tool_args, _max_arg_length
    try:
        with open(_CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
        _tool_args = config.get("tool_args", {})
        _max_arg_length = int(config.get("max_arg_length", _DEFAULT_MAX_ARG_LENGTH))
    except FileNotFoundError:
        logger.error("audit_to_db.yaml not found — arg mapping disabled")
    except Exception:
        logger.exception("Failed to load audit_to_db.yaml — arg mapping disabled")


_load_config()
db.init_db()
_executor = ThreadPoolExecutor(max_workers=1)
atexit.register(_executor.shutdown, wait=True)


BAD_STATUSES = {
    "error",
    "timeout",
    "not_found",
    "blocked",
    "disabled",
    "approval_required",
}


def is_ok(result: Any) -> tuple[bool, str]:
    try:
        data = json.loads(result) if isinstance(result, str | bytes | bytearray) else result
    except Exception:
        return False, "Tool result is not JSON"

    if not isinstance(data, dict):
        return True, ""

    error = data.get("error")
    success = data.get("success")
    status = data.get("status")
    exit_code = data.get("exit_code")

    if error:
        return False, str(error)

    if success is False:
        return False, str(data.get("error") or "success=false")

    if status in BAD_STATUSES:
        return False, str(data.get("error") or status)

    if exit_code is not None and exit_code != 0:
        return False, f"exit code={exit_code}"

    return True, ""

def register(ctx) -> None:
    ctx.register_hook("post_tool_call", on_post_tool_call)
    ctx.register_hook("post_api_request", on_post_api_call)
    

def on_post_tool_call(
    *,
    tool_name: str = "",
    args: Any = None,
    result: Any = "",
    task_id: str = "",
    session_id: str = "",
    duration_ms: int = 0,
    **kwargs: Any,
) -> None:
    try:
        success, error = False, ""
        try:
            success, error = is_ok(result)
        except Exception:
            success = False
            error = f"Failed to parse result for tool {tool_name}"
            logger.exception(error)

        arg_name = _tool_args.get(tool_name)
        arg_value = None
        if arg_name and isinstance(args, dict) and arg_name in args:
            arg_value = str(args[arg_name])[:_max_arg_length]

        error_val = error[:MAX_ERROR_LENGTH] if not success and error else None
        task_id_val = task_id or None

        def _insert():
            try:
                db.insert_call(
                    tool_name=tool_name,
                    result=1 if not success else 0,
                    session_id=session_id,
                    task_id=task_id_val,
                    duration_ms=duration_ms,
                    arg_name=arg_name,
                    arg_value=arg_value,
                    error=error_val,
                )
            except Exception:
                logger.exception("Failed to record tool call for %s", tool_name)

        _executor.submit(_insert)
    except Exception:
        logger.exception("Failed to record tool call for %s", tool_name)


def on_post_api_call(*, task_id: str = "", session_id: str = "", provider: str = "", base_url: str = "",
                     api_mode: str = "", model: str = "", api_call_count: int = 0,
                     assistant_message: Any = None, response: Any = None,
                     api_duration: float = 0.0, finish_reason: str = "",
                     usage: Any = None, assistant_content_chars: int = 0,
                     assistant_tool_call_count: int = 0, assistant_response: Any = None, platform: str="",
                     **kwargs: Any) -> None:
    try:
        provider_val = provider or None
        model_val = model or None
        platform_val = platform or None
        finish_reason_val = finish_reason or None
        task_id_val = task_id or None
        tokens = usage if isinstance(usage, dict) else {}

        def _insert():
            try:
                db.insert_api_call(
                    session_id=session_id,
                    task_id=task_id_val,
                    provider=provider_val,
                    model=model_val,
                    platform=platform_val,
                    finish_reason=finish_reason_val,
                    api_call_count=api_call_count,
                    api_duration=api_duration,
                    assistant_tool_call_count=assistant_tool_call_count,
                    input_tokens=tokens.get("input_tokens", 0),
                    output_tokens=tokens.get("output_tokens", 0),
                    cache_read_tokens=tokens.get("cache_read_tokens", 0),
                    cache_write_tokens=tokens.get("cache_write_tokens", 0),
                    reasoning_tokens=tokens.get("reasoning_tokens", 0),
                    prompt_tokens=tokens.get("prompt_tokens", 0),
                    total_tokens=tokens.get("total_tokens", 0),
                    request_count=tokens.get("request_count", 0),
                )
            except Exception:
                logger.exception("Failed to record API call for %s/%s", provider_val, model_val)

        _executor.submit(_insert)
    except Exception:
        logger.exception("Failed to record API call for %s/%s", provider, model)