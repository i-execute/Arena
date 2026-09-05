import asyncio
import builtins as _builtins
import json
import os
import re
import shutil
import sys
import uuid
import time
import secrets
import base64
import mimetypes
import hashlib
from collections import defaultdict
from contextlib import asynccontextmanager, AsyncExitStack
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, urlparse, parse_qs

import uvicorn
from camoufox.async_api import AsyncCamoufox
from fastapi import FastAPI, HTTPException, Depends, status, Form, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.security import APIKeyHeader

import httpx
import requests

# Import from modularized modules
from . import constants
from . import configurator as _config_module
from . import state as _state_module
from . import secrets_env as _secrets
from .configurator import get_models, save_models
from .browser_utils import (
    _is_windows,
    _normalize_camoufox_window_mode,
    _windows_apply_window_mode_by_title_substring,
    _maybe_apply_camoufox_window_mode,
    click_turnstile,
    is_execution_context_destroyed_error,
    safe_page_evaluate,
    _consume_background_task_exception,
    _cancel_background_task,
)
from .recaptcha import (
    extract_recaptcha_params_from_text,
    get_recaptcha_settings,
    _mint_recaptcha_v3_token_in_page,
    _camoufox_proxy_signup_anonymous_user,
    _set_provisional_user_id_in_browser,
    _maybe_inject_arena_auth_cookie_from_localstorage,
    find_chrome_executable,
    get_recaptcha_v3_token_with_chrome,
    get_recaptcha_v3_token,
    refresh_recaptcha_token,
    get_cached_recaptcha_token,
)
from .auth import (
    _combine_split_arena_auth_cookies,
    _capture_ephemeral_arena_auth_token_from_cookies,
    _upsert_browser_session_into_config,
    normalize_user_agent_value,
    get_request_headers_with_token,
    _decode_arena_auth_session_token,
    maybe_build_arena_auth_cookie_from_signup_response_body,
    _decode_jwt_payload,
    extract_supabase_anon_key_from_text,
    _derive_supabase_auth_base_url_from_arena_auth_token,
    get_arena_auth_token_expiry_epoch,
    is_arena_auth_token_expired,
    is_probably_valid_arena_auth_token,
    refresh_arena_auth_token_via_lmarena_http,
    refresh_arena_auth_token_via_supabase,
    maybe_refresh_expired_auth_tokens_via_lmarena_http,
    maybe_refresh_expired_auth_tokens,
    get_next_auth_token,
    remove_auth_token,
    ARENA_AUTH_REFRESH_LOCK,
)

from .transport import (
    BrowserFetchStreamResponse,
    UserscriptProxyStreamResponse,
    _touch_userscript_poll,
    _get_userscript_proxy_queue,
    _userscript_proxy_is_active,
    _userscript_proxy_check_secret,
    _cleanup_userscript_proxy_jobs,
    _mark_userscript_proxy_inactive,
    _finalize_userscript_proxy_job,
    _detect_arena_origin,
    _arena_origin_candidates,
    _arena_auth_cookie_specs,
    _provisional_user_id_cookie_specs,
    _get_arena_context_cookies,
    _normalize_userscript_proxy_url,
    fetch_lmarena_stream_via_userscript_proxy,
    fetch_lmarena_stream_via_chrome,
    fetch_lmarena_stream_via_camoufox,
    fetch_via_proxy_queue,
    push_proxy_chunk,
    camoufox_proxy_worker,
)

from .vision_solver import (
    solve_recaptcha_v2_challenge,
    VisionSolverConfig,
    VISION_SOLVER_AVAILABLE,
)

# Aliases for backward compatibility
DEBUG = constants.DEBUG
PORT = None  # resolved at startup via configurator.resolve_port()
HTTPStatus = constants.HTTPStatus
STATUS_MESSAGES = constants.STATUS_MESSAGES
RECAPTCHA_SITEKEY = constants.RECAPTCHA_SITEKEY
RECAPTCHA_ACTION = constants.RECAPTCHA_ACTION
RECAPTCHA_V2_SITEKEY = constants.RECAPTCHA_V2_SITEKEY
TURNSTILE_SITEKEY = constants.TURNSTILE_SITEKEY
STRICT_BROWSER_FETCH_MODELS = constants.STRICT_BROWSER_FETCH_MODELS
STRICT_CHROME_FETCH_MODELS = STRICT_BROWSER_FETCH_MODELS  # backward compat alias
LMARENA_ORIGIN = constants.LMARENA_ORIGIN
ARENA_ORIGIN = constants.ARENA_ORIGIN
ARENA_HOST_TO_ORIGIN = constants.ARENA_HOST_TO_ORIGIN
DEFAULT_REQUEST_TIMEOUT = constants.DEFAULT_REQUEST_TIMEOUT
GRECAPTCHA_TIMEOUT_MS = constants.GRECAPTCHA_TIMEOUT_MS
GRECAPTCHA_POLL_MS = constants.GRECAPTCHA_POLL_MS
TOKEN_EXPIRY_SKEW_SECONDS = constants.TOKEN_EXPIRY_SKEW_SECONDS
RECAPTCHA_TOKEN_EXPIRY_SECONDS = constants.RECAPTCHA_TOKEN_EXPIRY_SECONDS
RECAPTCHA_V3_TOKEN_LIFETIME_SECONDS = constants.RECAPTCHA_V3_TOKEN_LIFETIME_SECONDS
PERIODIC_REFRESH_INTERVAL_SECONDS = constants.PERIODIC_REFRESH_INTERVAL_SECONDS
DEFAULT_RATE_LIMIT_RPM = constants.DEFAULT_RATE_LIMIT_RPM
RATE_LIMIT_WINDOW_SECONDS = constants.RATE_LIMIT_WINDOW_SECONDS
DEFAULT_USERSCRIPT_PROXY_POLL_TIMEOUT_SECONDS = constants.DEFAULT_USERSCRIPT_PROXY_POLL_TIMEOUT_SECONDS
DEFAULT_USERSCRIPT_PROXY_JOB_TTL_SECONDS = constants.DEFAULT_USERSCRIPT_PROXY_JOB_TTL_SECONDS
USERSCRIPT_PROXY_ACTIVE_WINDOW_BUFFER_SECONDS = constants.USERSCRIPT_PROXY_ACTIVE_WINDOW_BUFFER_SECONDS
USERSCRIPT_PROXY_JOB_TTL_MAX_SECONDS = constants.USERSCRIPT_PROXY_JOB_TTL_MAX_SECONDS
DEFAULT_CAMOUFOX_PROXY_WINDOW_MODE = constants.DEFAULT_CAMOUFOX_PROXY_WINDOW_MODE
DEFAULT_CAMOUFOX_FETCH_WINDOW_MODE = constants.DEFAULT_CAMOUFOX_FETCH_WINDOW_MODE
DEFAULT_CHROME_FETCH_WINDOW_MODE = constants.DEFAULT_CHROME_FETCH_WINDOW_MODE
VALID_WINDOW_MODES = constants.VALID_WINDOW_MODES
CHROME_PATH_CANDIDATES = constants.CHROME_PATH_CANDIDATES
EDGE_PATH_CANDIDATES = constants.EDGE_PATH_CANDIDATES
DEFAULT_USER_AGENT = constants.DEFAULT_USER_AGENT
MAX_IMAGE_SIZE_BYTES = constants.MAX_IMAGE_SIZE_BYTES
SUPPORTED_IMAGE_MIME_TYPES = constants.SUPPORTED_IMAGE_MIME_TYPES
CF_CLEARANCE_COOKIE = constants.CF_CLEARANCE_COOKIE
CF_BM_COOKIE = constants.CF_BM_COOKIE
CF_UVID_COOKIE = constants.CF_UVID_COOKIE
PROVISIONAL_USER_ID_COOKIE = constants.PROVISIONAL_USER_ID_COOKIE
ARENA_AUTH_COOKIE = constants.ARENA_AUTH_COOKIE
GRECAPTCHA_COOKIE = constants.GRECAPTCHA_COOKIE
ARENA_COOKIE_DOMAINS = constants.ARENA_COOKIE_DOMAINS
ARENA_DIRECT_MODE_URL = constants.ARENA_DIRECT_MODE_URL
NEXTJS_API_SIGNUP = constants.NEXTJS_API_SIGNUP
CONTENT_TYPE_TEXT_PLAIN_UTF8 = constants.CONTENT_TYPE_TEXT_PLAIN_UTF8
CONTENT_TYPE_APPLICATION_JSON = constants.CONTENT_TYPE_APPLICATION_JSON
TURNSTILE_SELECTORS = constants.TURNSTILE_SELECTORS
TURNSTILE_INNER_SELECTORS = constants.TURNSTILE_INNER_SELECTORS
ARENA_ORIGIN_HEADER = constants.ARENA_ORIGIN_HEADER
ARENA_REFERER_HEADER = constants.ARENA_REFERER_HEADER
SUPABASE_JWT_PATTERN = constants.SUPABASE_JWT_PATTERN
CLOUDFLARE_CHALLENGE_TITLE = constants.CLOUDFLARE_CHALLENGE_TITLE

# Backoff functions
def get_rate_limit_sleep_seconds(retry_after: Optional[str], attempt: int) -> int:
    return constants.get_rate_limit_backoff_seconds(retry_after, attempt)

def get_general_backoff_seconds(attempt: int) -> int:
    return constants.get_general_backoff_seconds(attempt)


def safe_print(*args, **kwargs) -> None:
    """
    Print without crashing on Windows console encoding issues (e.g., GBK can't encode emoji).
    This must never raise, because it's used inside request handlers/streaming generators.
    """
    try:
        _builtins.print(*args, **kwargs)
    except UnicodeEncodeError:
        file = kwargs.get("file") or sys.stdout
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        flush = bool(kwargs.get("flush", False))

        try:
            text = sep.join(str(a) for a in args) + end
            encoding = getattr(file, "encoding", None) or getattr(sys.stdout, "encoding", None) or "utf-8"
            safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="ignore")
            file.write(safe_text)
            if flush:
                try:
                    file.flush()
                except Exception:
                    pass
        except Exception:
            return


# Ensure all module-level `print(...)` calls are resilient to Windows console encoding issues.
# (Some environments default to GBK, which cannot encode emoji.)
print = safe_print  # type: ignore[assignment]


def debug_print(*args, **kwargs):
    """Print debug messages only if DEBUG is True; always append to bridge.log (criterion 5)."""
    if DEBUG:
        print(*args, **kwargs)
    try:
        _line = " ".join(str(a) for a in args) + (" " + str(kwargs) if kwargs else "")
        _log_dir = os.path.join(os.getcwd(), "Storage", "logs")
        os.makedirs(_log_dir, exist_ok=True)
        _log_path = os.path.join(_log_dir, "bridge.log")
        with open(_log_path, "a", encoding="utf-8") as _lf:
            _lf.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {_line}\n")
    except Exception:
        pass


def get_status_emoji(status_code: int) -> str:
    if 200 <= status_code < 300:
        return "✅"
    elif 300 <= status_code < 400:
        return "↪️"
    elif 400 <= status_code < 500:
        if status_code == 401:
            return "🔒"
        elif status_code == 403:
            return "🚫"
        elif status_code == 404:
            return "❓"
        elif status_code == 429:
            return "⏱️"
        return "⚠️"
    elif 500 <= status_code < 600:
        return "❌"
    return "ℹ️"


def log_http_status(status_code: int, context: str = "") -> None:
    emoji = get_status_emoji(status_code)
    message = STATUS_MESSAGES.get(status_code, f"Unknown Status {status_code}")
    if context:
        debug_print(f"{emoji} HTTP {status_code}: {message} ({context})")
    else:
        debug_print(f"{emoji} HTTP {status_code}: {message}")


def _parse_arena_sse_text_to_dict(sse_text: str) -> dict | None:
    """Parse a raw SSE body (ag:/a0:/ad: lines) into a dict with 'content' and 'reasoning_content'."""
    import json as _json
    text_parts = []
    reasoning_parts = []
    for _line in sse_text.splitlines():
        _line = _line.strip()
        if _line.startswith("data: "):
            _line = _line[6:].strip()
        if _line.startswith("ag:"):
            try:
                reasoning_parts.append(_json.loads(_line[3:]))
            except Exception:
                pass
        elif _line.startswith("a0:"):
            try:
                text_parts.append(_json.loads(_line[3:]))
            except Exception:
                pass
    result = {"content": "".join(text_parts)}
    if reasoning_parts:
        result["reasoning_content"] = "".join(reasoning_parts)
    return result if text_parts else None


def _transform_arena_response_to_openai(arena_response_obj: dict, model_name: str) -> dict:
    """
    Transform Arena response to OpenAI-compatible format.
    Extracts content from Arena API response and wraps in OpenAI schema.
    """
    try:
        # Extract content from Arena response  
        content = ""
        if isinstance(arena_response_obj, dict):
            # Try multiple possible content field names from Arena API
            content = (
                arena_response_obj.get("message") or 
                arena_response_obj.get("content") or 
                arena_response_obj.get("text") or 
                (str(arena_response_obj.get("choices", [{}])[0].get("message", {}).get("content") or ""))
            )
        
        # Build OpenAI-compatible response
        openai_response = {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": str(content).strip() if content else ""
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": max(1, len(str(content).split()) if content else 0),
                "total_tokens": 10 + max(1, len(str(content).split()) if content else 0)
            }
        }
        
        return openai_response
    except Exception as e:
        debug_print(f"⚠️ Error transforming response: {e}")
        return {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "error"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }




# Updated constants from gpt4free/g4f/Provider/needs_auth/LMArena.py
RECAPTCHA_SITEKEY = "6Led_uYrAAAAAKjxDIF58fgFtX3t8loNAK85bW9I"
RECAPTCHA_ACTION = "chat_submit"
# reCAPTCHA Enterprise v2 sitekey used when v3 scoring fails and LMArena prompts a checkbox challenge.
RECAPTCHA_V2_SITEKEY = "6Ld7ePYrAAAAAB34ovoFoDau1fqCJ6IyOjFEQaMn"
# Cloudflare Turnstile sitekey used by LMArena to mint anonymous-user signup tokens.
# (Used for POST /nextjs-api/sign-up before `arena-auth-prod-v1` exists.)
TURNSTILE_SITEKEY = "0x4AAAAAAA65vWDmG-O_lPtT"
STREAM_CREATE_EVALUATION_PATH = "/nextjs-api/stream/create-evaluation"

# LMArena occasionally changes the reCAPTCHA sitekey/action. We try to discover them from captured JS chunks on startup
# and persist them into config.json; these helpers read and apply those values with safe fallbacks.

# _is_windows, _normalize_camoufox_window_mode imported from browser_utils


USERSCRIPT_PROXY_LAST_POLL_AT: float = 0.0
_USERSCRIPT_PROXY_QUEUE: Optional[asyncio.Queue] = None
_USERSCRIPT_PROXY_JOBS: dict[str, dict] = {}


# Custom UUIDv7 implementation (using correct Unix epoch)
def uuid7():
    """
    Generate a UUIDv7 using Unix epoch (milliseconds since 1970-01-01)
    matching the browser's implementation.
    """
    timestamp_ms = int(time.time() * 1000)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    
    uuid_int = timestamp_ms << 80
    uuid_int |= (0x7000 | rand_a) << 64
    uuid_int |= (0x8000000000000000 | rand_b)
    
    hex_str = f"{uuid_int:032x}"
    return f"{hex_str[0:8]}-{hex_str[8:12]}-{hex_str[12:16]}-{hex_str[16:20]}-{hex_str[20:32]}"

def _get_signed_url_expiry(url: str) -> Optional[float]:
    """Extract expiry timestamp from an S3/R2 signed URL."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        # S3/R2 standard headers for signed URLs
        date_str = params.get("X-Amz-Date", [None])[0]
        expires_str = params.get("X-Amz-Expires", [None])[0]
        if not date_str or not expires_str:
            return None
        
        # Parse timestamp format: 20260425T071405Z
        dt = datetime.strptime(date_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return dt.timestamp() + int(expires_str)
    except (ValueError, TypeError, IndexError, AttributeError):
        return None

def check_link_expiry(url: str) -> bool:
    """Check if an S3/R2 signed URL is still valid based on its query params."""
    expiry_ts = _get_signed_url_expiry(url)
    if expiry_ts is None:
        return False
    # Return True if current time is before expiry (with 60s safety buffer)
    return time.time() < (expiry_ts - 60)

# Image upload helper functions
async def upload_image_to_lmarena(image_data: bytes, mime_type: str, filename: str) -> Optional[tuple]:
    """
    Upload an image to LMArena R2 storage and return the key and download URL.
    Uses MD5 caching to avoid re-uploading the same image.
    """
    try:
        # Validate inputs
        if not image_data:
            debug_print("❌ Image data is empty")
            return None
        
        # 0. Check MD5 Cache
        image_hash = hashlib.md5(image_data).hexdigest()
        cached = _state_module.IMAGES_CACHE.get(image_hash)
        if cached:
            # Use cached expiry directly if available, otherwise fallback to parsing URL
            expiry = cached.get("expiry")
            if expiry is None:
                expiry = _get_signed_url_expiry(cached.get("url", ""))
            
            if expiry and time.time() < (expiry - 60):
                debug_print(f"📦 Using cached image for hash {image_hash[:8]}...")
                return cached["key"], cached["url"]
            else:
                debug_print(f"📦 Cached image expired for hash {image_hash[:8]}. Re-uploading...")
                _state_module.IMAGES_CACHE.pop(image_hash, None)
        
        if not mime_type or not mime_type.startswith('image/'):
            debug_print(f"❌ Invalid MIME type: {mime_type}")
            return None
        
        # Step 1: Request upload URL
        debug_print(f"📤 Step 1: Requesting upload URL for {filename}")
        
        # Get Next-Action IDs from config
        config = get_config()
        upload_action_id = config.get("next_action_upload")
        signed_url_action_id = config.get("next_action_signed_url")
        
        if not upload_action_id or not signed_url_action_id:
            debug_print("❌ Next-Action IDs not found in config. Please refresh tokens from dashboard.")
            return None
        
        # Prepare headers for Next.js Server Action
        request_headers = get_request_headers()
        request_headers.update({
            "Accept": "text/x-component",
            "Content-Type": "text/plain;charset=UTF-8",
            "Next-Action": upload_action_id,
            "Referer": "https://arena.ai/?mode=direct",
        })
        
        import cloudscraper as _cs
        def _cs_upload():
            scraper = _cs.create_scraper()
            return scraper.post(
                "https://arena.ai/?mode=direct",
                headers=request_headers,
                data=json.dumps([filename, mime_type]),
                timeout=30.0,
            )
        try:
            response = await asyncio.to_thread(_cs_upload)
            response.raise_for_status()
        except (_cs.exceptions.CloudflareException, requests.exceptions.RequestException) as e:
            debug_print(f"❌ Error while requesting upload URL: {e}")
            return None
        
        # Parse response - format: 0:{...}\n1:{...}\n
        try:
            lines = response.text.strip().split('\n')
            upload_data = None
            for line in lines:
                if line.startswith('1:'):
                    upload_data = json.loads(line[2:])
                    break
            
            if not upload_data or not upload_data.get('success'):
                debug_print(f"❌ Failed to get upload URL: {response.text[:200]}")
                return None
            
            upload_url = upload_data['data']['uploadUrl']
            key = upload_data['data']['key']
            debug_print(f"✅ Got upload URL and key: {key}")
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            debug_print(f"❌ Failed to parse upload URL response: {e}")
            return None
        
        # Step 2: Upload image to R2 storage
        debug_print(f"📤 Step 2: Uploading image to R2 storage ({len(image_data)} bytes)")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    upload_url,
                    content=image_data,
                    headers={"Content-Type": mime_type},
                    timeout=60.0
                )
                response.raise_for_status()
                debug_print(f"✅ Image uploaded successfully")
        except httpx.TimeoutException:
            debug_print("❌ Timeout while uploading image to R2 storage")
            return None
        except httpx.HTTPError as e:
            debug_print(f"❌ HTTP error while uploading image: {e}")
            return None
        
        # Step 3: Get signed download URL (uses different Next-Action)
        debug_print(f"📤 Step 3: Requesting signed download URL")
        request_headers_step3 = request_headers.copy()
        request_headers_step3["Next-Action"] = signed_url_action_id
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://arena.ai/?mode=direct",
                    headers=request_headers_step3,
                    content=json.dumps([key]),
                    timeout=30.0
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            debug_print("❌ Timeout while requesting download URL")
            return None
        except httpx.HTTPError as e:
            debug_print(f"❌ HTTP error while requesting download URL: {e}")
            return None
        
        # Parse response
        try:
            lines = response.text.strip().split('\n')
            download_data = None
            for line in lines:
                if line.startswith('1:'):
                    download_data = json.loads(line[2:])
                    break
            
            if not download_data or not download_data.get('success'):
                debug_print(f"❌ Failed to get download URL: {response.text[:200]}")
                return None
            
            download_url = download_data['data']['url']
            debug_print(f"✅ Got signed download URL: {download_url[:100]}...")
            
            # Cache the uploaded image by MD5 to avoid redundant uploads.
            expiry_ts = _get_signed_url_expiry(download_url)
            if expiry_ts is None:
                expiry_ts = time.time() + 3600

            try:
                # Size limit for IMAGES_CACHE to prevent memory growth (FIFO eviction)
                if len(_state_module.IMAGES_CACHE) >= 1000:
                    # Clear 10% of cache if full
                    keys_to_remove = list(_state_module.IMAGES_CACHE)[:100]
                    for k in keys_to_remove:
                        _state_module.IMAGES_CACHE.pop(k, None)
                
                _state_module.IMAGES_CACHE[image_hash] = {"key": key, "url": download_url, "expiry": float(expiry_ts)}
            except Exception:
                pass

            return (key, download_url)
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            debug_print(f"❌ Failed to parse download URL response: {e}")
            return None
            
    except Exception as e:
        debug_print(f"❌ Unexpected error uploading image: {type(e).__name__}: {e}")
        return None

def _coerce_message_content_to_text(content) -> str:
    """Best-effort coercion of message content to plain text (no images)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
                elif "text" in part:
                    parts.append(str(part.get("text", "")))
                elif "content" in part:
                    parts.append(str(part.get("content", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join([p for p in parts if p is not None]).strip()
    return str(content)


async def process_message_content(content, model_capabilities: dict) -> tuple[str, List[dict]]:
    """
    Process message content, handle images if present and model supports them.
    
    Args:
        content: Message content (string or list of content parts)
        model_capabilities: Model's capability dictionary
    
    Returns:
        Tuple of (text_content, experimental_attachments)
    """
    # Check if model supports image input
    supports_images = model_capabilities.get('inputCapabilities', {}).get('image', False)
    
    # If content is a string, return it as-is
    if isinstance(content, str):
        return content, []
    
    # If content is a list (OpenAI format with multiple parts)
    if isinstance(content, list):
        text_parts = []
        attachments = []
        
        for part in content:
            if isinstance(part, dict):
                if part.get('type') == 'text':
                    text_parts.append(part.get('text', ''))
                elif 'text' in part:
                    text_parts.append(part.get('text', ''))
                elif 'content' in part:
                    text_parts.append(part.get('content', ''))
                    
                elif part.get('type') == 'image_url' and supports_images:
                    image_url = part.get('image_url', {})
                    if isinstance(image_url, dict):
                        url = image_url.get('url', '')
                    else:
                        url = image_url
                    
                    # Handle base64-encoded images
                    if url.startswith('data:'):
                        # Format: data:image/png;base64,iVBORw0KGgo...
                        try:
                            # Validate and parse data URI
                            if ',' not in url:
                                debug_print(f"❌ Invalid data URI format (no comma separator)")
                                continue
                            
                            header, data = url.split(',', 1)
                            
                            # Parse MIME type
                            if ';' not in header or ':' not in header:
                                debug_print(f"❌ Invalid data URI header format")
                                continue
                            
                            mime_type = header.split(';')[0].split(':')[1]
                            
                            # Validate MIME type
                            if not mime_type.startswith('image/'):
                                debug_print(f"❌ Invalid MIME type: {mime_type}")
                                continue
                            
                            # Decode base64
                            try:
                                image_data = base64.b64decode(data)
                            except Exception as e:
                                debug_print(f"❌ Failed to decode base64 data: {e}")
                                continue
                            
                            # Validate image size (max 10MB)
                            if len(image_data) > 10 * 1024 * 1024:
                                debug_print(f"❌ Image too large: {len(image_data)} bytes (max 10MB)")
                                continue
                            
                            # Generate filename
                            ext = mimetypes.guess_extension(mime_type) or '.png'
                            filename = f"upload-{uuid.uuid4()}{ext}"
                            
                            debug_print(f"🖼️  Processing base64 image: {filename}, size: {len(image_data)} bytes")
                            
                            # Upload to LMArena
                            upload_result = await upload_image_to_lmarena(image_data, mime_type, filename)
                            
                            if upload_result:
                                key, download_url = upload_result
                                # Add as attachment in LMArena format
                                attachments.append({
                                    "name": key,
                                    "contentType": mime_type,
                                    "url": download_url
                                })
                                debug_print(f"✅ Image uploaded and added to attachments")
                            else:
                                debug_print(f"⚠️  Failed to upload image, skipping")
                        except Exception as e:
                            debug_print(f"❌ Unexpected error processing base64 image: {type(e).__name__}: {e}")
                    
                    # Handle URL images (direct URLs)
                    elif url.startswith('http://') or url.startswith('https://'):
                        # For external URLs, we'd need to download and re-upload
                        # For now, skip this case
                        debug_print(f"⚠️  External image URLs not yet supported: {url[:100]}")
                        
                elif part.get('type') == 'image_url' and not supports_images:
                    debug_print(f"⚠️  Image provided but model doesn't support images")
            elif isinstance(part, str):
                text_parts.append(part)
        
        # Combine text parts
        text_content = '\n'.join(text_parts).strip()
        return text_content, attachments
    
    # Fallback
    return str(content), []

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await startup_event()
    except Exception as e:
        debug_print(f"❌ Error during startup: {e}")
    yield

app = FastAPI(lifespan=lifespan)

# Mount the new JS frontend (WEB directory) so the legacy Python bridge can serve the dashboard
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

WEB_DIR = Path(__file__).resolve().parent.parent.joinpath("WEB")
if WEB_DIR.exists():
    try:
        app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
        debug_print(f"✔ Mounted WEB static files at /web -> {WEB_DIR}")
    except Exception as _e:
        debug_print(f"❌ Failed to mount WEB static files: {_e}")

# Provide a compatibility route for the old dashboard path to serve the new index.html
@app.get("/dashboard")
async def dashboard_redirect():
    try:
        index = WEB_DIR.joinpath("index.html")
        if index.exists():
            return FileResponse(str(index))
    except Exception:
        pass
    return RedirectResponse(url="/web/")

# Compatibility helper: accept browser cookie dumps (JSON array/object) and combine split arena-auth cookies
@app.post("/api/merge_tokens")
async def merge_tokens(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = None

    cookies = None
    # Allow raw array or { cookies: [...] } or {"arena-auth-prod-v1.0":..., ...}
    if isinstance(body, list):
        cookies = body
    elif isinstance(body, dict):
        if "cookies" in body and isinstance(body["cookies"], list):
            cookies = body["cookies"]
        else:
            # Try to convert dict map into cookie objects
            cookies = []
            for k, v in body.items():
                # skip non-cookie fields
                if not isinstance(k, str):
                    continue
                cookies.append({"name": k, "value": v})
    if not cookies:
        raise HTTPException(status_code=400, detail="Missing cookie array or object")

    # Accept either a current combined cookie or split .0/.1 cookies.
    try:
        from .auth import _combine_split_arena_auth_cookies
        direct = next((str(c.get("value") or "").strip() for c in cookies
                       if str(c.get("name") or "") == "arena-auth-prod-v1"), "")
        combined = direct or _combine_split_arena_auth_cookies(cookies)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Combine failed: {e}")

    if not combined:
        raise HTTPException(status_code=400, detail="Could not find arena-auth cookie or split cookie parts in input")

    # Persist into config.auth_tokens if not present
    cfg = get_config()
    auths = cfg.get("auth_tokens") or []
    if not isinstance(auths, list):
        auths = []
    if combined not in auths:
        auths.append(combined)
    cfg["auth_tokens"] = auths
    # The internal Camoufox proxy reads the cookie from browser_cookies, while
    # direct HTTP transport reads auth_tokens. Keep both stores in sync.
    browser_cookies = cfg.get("browser_cookies")
    if not isinstance(browser_cookies, dict):
        browser_cookies = {}
        cfg["browser_cookies"] = browser_cookies
    browser_cookies["arena-auth-prod-v1"] = combined
    try:
        save_config(cfg, preserve_auth_tokens=False)
    except Exception:
        pass

    return {"ok": True, "token": combined}

# Add CORS middleware to handle preflight requests and avoid 405 errors
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",  # WARNING: For development only. Restrict to specific origins in production.
    allow_credentials=True,
    allow_methods=["*"],  # This includes GET, POST, PUT, DELETE, OPTIONS, etc.
    allow_headers=["*"],
)

# --- Constants & Global State ---
CONFIG_FILE = constants.CONFIG_FILE
MODELS_FILE = constants.MODELS_FILE
API_KEY_HEADER = APIKeyHeader(name="Authorization", auto_error=False)

# In-memory stores
# { "api_key": { "conversation_id": session_data } }
chat_sessions: Dict[str, Dict[str, dict]] = defaultdict(dict)
# Persist sessions to disk so follow-up survives bridge restarts
SESSIONS_FILE = os.path.join(os.path.dirname(__file__), "..", "Storage", "sessions", "chat_sessions.json")
if os.path.exists(SESSIONS_FILE):
    try:
        _loaded = json.load(open(SESSIONS_FILE))
        for k, v in _loaded.items():
            chat_sessions[k].update(v)
        debug_print(f"📂 Loaded {sum(len(v) for v in _loaded.values())} sessions from {SESSIONS_FILE}")
    except Exception as e:
        debug_print(f"⚠️ Failed to load sessions: {e}")

def _persist_sessions():
    try:
        os.makedirs(os.path.dirname(SESSIONS_FILE), exist_ok=True)
        json.dump(dict(chat_sessions), open(SESSIONS_FILE, "w"), indent=2)
    except Exception as e:
        debug_print(f"⚠️ Failed to persist sessions: {e}")
# { "session_id": "username" }
dashboard_sessions = {}
# { "api_key": [timestamp1, timestamp2, ...] }
api_key_usage = defaultdict(list)
# { "model_id": count }
# NOTE: the bridge runs as `python3 -m BRIDGE.main`, so main.py is imported TWICE —
# once as __main__ (serving the requests) and once as BRIDGE.main (via transport._m()
# / auth._m()). A plain module-global counter therefore exists twice, and the empty
# copy used by background savers wiped usage_stats on every scheduled save. Bind to
# the single shared object in BRIDGE.state and only ever mutate it IN PLACE.
model_usage_stats = _state_module.model_usage_stats
# Token cycling: current index for round-robin selection
current_token_index = 0
# Track config file path changes to reset per-config state in tests/dev.
_LAST_CONFIG_FILE: Optional[str] = None
# Track which token is assigned to each conversation (conversation_id -> token)
conversation_tokens: Dict[str, str] = {}
# Track failed tokens per request to avoid retrying with same token
request_failed_tokens: Dict[str, set] = {}

# Ephemeral Arena auth cookie captured from browser sessions (not persisted unless enabled).
EPHEMERAL_ARENA_AUTH_TOKEN: Optional[str] = None

# Supabase anon key (public client key) discovered from LMArena's JS bundles. Kept in-memory by default.
SUPABASE_ANON_KEY: Optional[str] = None

# --- New Global State for reCAPTCHA ---
RECAPTCHA_TOKEN: Optional[str] = None
# Initialize expiry far in the past to force a refresh on startup
RECAPTCHA_EXPIRY: datetime = datetime.now(timezone.utc) - timedelta(days=365)
# --------------------------------------

# --- Helper Functions ---

def get_config():
    global current_token_index, _LAST_CONFIG_FILE
    # If tests or callers swap CONFIG_FILE at runtime, reset the token round-robin index so token selection
    # is deterministic per config file.
    if _LAST_CONFIG_FILE != CONFIG_FILE:
        _LAST_CONFIG_FILE = CONFIG_FILE
        current_token_index = 0
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        debug_print(f"⚠️  Config file error: {e}, using defaults")
        config = {}
    except Exception as e:
        debug_print(f"⚠️  Unexpected error reading config: {e}, using defaults")
        config = {}

    # Ensure default keys exist
    try:
        _config_module._apply_config_defaults(config)
    except Exception as e:
        debug_print(f"⚠️  Error setting config defaults: {e}")

    # Overlay secrets from .env. config.json is runtime STATE (rewritten by
    # background tasks, symlinked to the repo root, mirrored by the dashboard) and
    # must never be the home of credentials — see BRIDGE/secrets_env.py.
    try:
        _overlay_secrets_from_env(config)
    except Exception as e:
        debug_print(f"⚠️  Error overlaying secrets from .env: {e}")

    return config


def _overlay_secrets_from_env(config: dict) -> None:
    """Inject .env-held secrets into an in-memory config dict."""
    env_keys = _secrets.api_keys()
    if env_keys:
        existing = {k.get("key"): k for k in (config.get("api_keys") or [])
                    if isinstance(k, dict)}
        merged = []
        for i, key in enumerate(env_keys):
            prev = existing.get(key) or {}
            merged.append({
                "name": prev.get("name") or ("Default Key" if i == 0 else f"Key {i + 1}"),
                "key": key,
                "rpm": prev.get("rpm", constants.DEFAULT_RATE_LIMIT_RPM),
                "created": prev.get("created", 0),
            })
        config["api_keys"] = merged

    env_tokens = _secrets.arena_auth_tokens()
    if env_tokens:
        config["auth_tokens"] = env_tokens
        config["auth_token"] = env_tokens[0]

    env_cf = _secrets.cf_clearance()
    if env_cf:
        config["cf_clearance"] = env_cf

    raw_cookies = _secrets.get("ARENA_BROWSER_COOKIES")
    if raw_cookies:
        try:
            parsed = json.loads(raw_cookies)
            if isinstance(parsed, dict):
                merged_cookies = dict(parsed)
                merged_cookies.update(config.get("browser_cookies") or {})
                config["browser_cookies"] = merged_cookies
        except Exception:
            pass


def load_usage_stats():
    """Load usage stats from config into the SHARED in-memory counter (in place)."""
    try:
        config = get_config()
        on_disk = config.get("usage_stats") or {}
    except Exception as e:
        debug_print(f"⚠️  Error loading usage stats: {e}, using empty stats")
        on_disk = {}
    # In-place update: rebinding would break the object shared with BRIDGE.state
    # and re-introduce the duplicate-counter bug described above.
    model_usage_stats.clear()
    for k, v in on_disk.items():
        try:
            model_usage_stats[k] = int(v)
        except (TypeError, ValueError):
            continue

def save_config(config, *, preserve_auth_tokens: bool = True):
    try:
        # Always read the current file: needed both for the auth-token guard and for
        # merging monotonic usage counters (see below).
        try:
            with open(CONFIG_FILE, "r") as f:
                on_disk = json.load(f)
        except Exception:
            on_disk = None

        # Avoid clobbering user-provided auth tokens when multiple tasks write config.json concurrently.
        # Background refreshes/cookie upserts shouldn't overwrite auth tokens that may have been added via the dashboard.
        if preserve_auth_tokens and isinstance(on_disk, dict):
            if "auth_tokens" in on_disk and isinstance(on_disk.get("auth_tokens"), list):
                config["auth_tokens"] = list(on_disk.get("auth_tokens") or [])
            if "auth_token" in on_disk:
                config["auth_token"] = str(on_disk.get("auth_token") or "")

        # Persist in-memory stats to the config dict before saving.
        # Merge with what's on disk and keep the MAX per model: these are
        # monotonic counters, and a background saver holding a stale/empty view
        # must never shrink them.
        merged_usage = {}
        if isinstance(on_disk, dict):
            for k, v in (on_disk.get("usage_stats") or {}).items():
                try:
                    merged_usage[k] = int(v)
                except (TypeError, ValueError):
                    continue
        for k, v in dict(model_usage_stats).items():
            try:
                merged_usage[k] = max(merged_usage.get(k, 0), int(v))
            except (TypeError, ValueError):
                continue
        config["usage_stats"] = merged_usage

        # Same for the two aggregate counters the dashboard shows: a stale caller
        # must not roll them back.
        if isinstance(on_disk, dict):
            try:
                config["total_requests"] = max(int(config.get("total_requests") or 0),
                                               int(on_disk.get("total_requests") or 0))
            except (TypeError, ValueError):
                pass
            disk_today = on_disk.get("usage_today")
            cur_today = config.get("usage_today")
            if isinstance(disk_today, dict):
                merged_today = dict(disk_today)
                if isinstance(cur_today, dict):
                    for k, v in cur_today.items():
                        try:
                            merged_today[k] = max(int(merged_today.get(k, 0)), int(v))
                        except (TypeError, ValueError):
                            continue
                config["usage_today"] = merged_today
        # Route every credential to .env and keep config.json free of secrets.
        # Background refresh tasks call save_config() constantly, so this is where
        # rotated arena tokens / cf_clearance / cookies get persisted.
        try:
            _persist_secrets_to_env(config)
        except Exception as e:
            debug_print(f"⚠️  Could not persist secrets to .env: {e}")

        on_disk_state = dict(config)
        _secrets.strip_secrets(on_disk_state)

        tmp_path = f"{CONFIG_FILE}.tmp"
        with open(tmp_path, "w") as f:
            json.dump(on_disk_state, f, indent=4)
        os.replace(tmp_path, CONFIG_FILE)
    except Exception as e:
        debug_print(f"❌ Error saving config: {e}")


def _persist_secrets_to_env(config: dict) -> None:
    """Write changed secret material from a config dict into .env (0600)."""
    updates = {}

    tokens = [t for t in (config.get("auth_tokens") or []) if t]
    if not tokens and config.get("auth_token"):
        tokens = [config["auth_token"]]
    if tokens and tokens != _secrets.arena_auth_tokens():
        updates["ARENA_AUTH_TOKEN"] = ",".join(tokens)

    cf = str(config.get("cf_clearance") or "").strip()
    if cf and cf != _secrets.cf_clearance():
        updates["ARENA_CF_CLEARANCE"] = cf

    cookies = config.get("browser_cookies")
    if isinstance(cookies, dict) and cookies:
        blob = json.dumps(cookies, separators=(",", ":"), sort_keys=True)
        if blob != _secrets.get("ARENA_BROWSER_COOKIES"):
            updates["ARENA_BROWSER_COOKIES"] = blob

    keys = [k.get("key") for k in (config.get("api_keys") or [])
            if isinstance(k, dict) and k.get("key")]
    if keys and keys != _secrets.api_keys():
        updates["BRIDGE_API_KEY"] = keys[0]
        updates["BRIDGE_API_KEYS"] = ",".join(keys[1:]) if len(keys) > 1 else None

    if updates:
        _secrets.set_many(updates)
        debug_print("🔐 Secrets synced to .env: " + ", ".join(sorted(updates)))

def get_request_headers():
    """Get request headers with the first available auth token (for compatibility)"""
    config = get_config()
    
    # Try to get token from auth_tokens first, then fallback to single token
    auth_tokens = config.get("auth_tokens", [])
    if auth_tokens:
        token = auth_tokens[0]  # Just use first token for non-API requests
    else:
        token = config.get("auth_token", "").strip()
        if not token:
            cookie_store = config.get("browser_cookies")
            if isinstance(cookie_store, dict) and bool(config.get("persist_arena_auth_cookie")):
                token = str(cookie_store.get("arena-auth-prod-v1") or "").strip()
                if token:
                    config["auth_tokens"] = [token]
                    save_config(config, preserve_auth_tokens=False)
        if not token:
            raise HTTPException(status_code=500, detail="Arena auth token not set in dashboard.")
    
    return get_request_headers_with_token(token)

# --- Dashboard Authentication ---

async def get_current_session(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id and session_id in dashboard_sessions:
        return dashboard_sessions[session_id]
    return None

# --- API Key Authentication & Rate Limiting ---

async def rate_limit_api_key(key: str = Depends(API_KEY_HEADER)):
    config = get_config()
    api_keys = config.get("api_keys", [])

    api_key_str = None
    if key and key.startswith("Bearer "):
        api_key_str = key[7:].strip()

    # If no API keys configured, allow anonymous access (optional auth)
    if not api_keys:
        return {"key": "anonymous", "name": "Anonymous", "rpm": 9999}

    # Keys ARE configured -> a valid key is mandatory. Previously this fell back to
    # api_keys[0] when the caller sent no Authorization header, which made the whole
    # bridge (and every arena auth token behind it) usable by anyone who found the
    # public cloudflared API tunnel.
    if not api_key_str:
        raise HTTPException(
            status_code=401,
            detail="Missing API key. Send 'Authorization: Bearer <key>'.",
        )

    key_data = next((k for k in api_keys if k["key"] == api_key_str), None)
    if not key_data:
        raise HTTPException(status_code=401, detail="Invalid API Key.")

    # Rate Limiting
    rate_limit = key_data.get("rpm", 60)
    current_time = time.time()

    # Clean up old timestamps (older than 60 seconds)
    api_key_usage[api_key_str] = [t for t in api_key_usage[api_key_str] if current_time - t < 60]

    if len(api_key_usage[api_key_str]) >= rate_limit:
        # Calculate seconds until oldest request expires (60 seconds window)
        oldest_timestamp = min(api_key_usage[api_key_str])
        retry_after = int(60 - (current_time - oldest_timestamp))
        retry_after = max(1, retry_after)  # At least 1 second

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please try again later.",
            headers={"Retry-After": str(retry_after)}
        )

    api_key_usage[api_key_str].append(current_time)

    return key_data

# --- Core Logic ---

async def get_initial_data():
    debug_print("Starting initial data retrieval...")
    try:
        async with AsyncCamoufox(headless=True, main_world_eval=True) as browser:
            page = await browser.new_page()
            
            # Set up route interceptor BEFORE navigating
            debug_print("  🎯 Setting up route interceptor for JS chunks...")
            captured_responses = []
            
            async def capture_js_route(route):
                """Intercept and capture JS chunk responses"""
                url = route.request.url
                # Capture Supabase anon key from request headers (sent as apikey on every supabase request)
                if 'supabase.co' in url:
                    global SUPABASE_ANON_KEY
                    try:
                        _apikey = route.request.headers.get('apikey', '')
                        if _apikey and not str(SUPABASE_ANON_KEY or "").strip():
                            SUPABASE_ANON_KEY = _apikey
                            debug_print(f"✅ Captured Supabase anon key from request headers: {_apikey[:16]}...")
                            _cfg = get_config()
                            if _cfg.get("supabase_anon_key") != _apikey:
                                _cfg["supabase_anon_key"] = _apikey
                                save_config(_cfg, preserve_auth_tokens=True)
                    except Exception:
                        pass
                    await route.continue_()
                    return
                if '/_next/static/chunks/' in url and '.js' in url:
                    try:
                        # Fetch the original response
                        response = await route.fetch()
                        # Get the response body
                        body = await response.body()
                        text = body.decode('utf-8')

                        # debug_print(f"    📥 Captured JS chunk: {url.split('/')[-1][:50]}...")
                        captured_responses.append({'url': url, 'text': text})
                        
                        # Continue with the original response (don't modify)
                        await route.fulfill(response=response, body=body)
                    except Exception as e:
                        debug_print(f"    ⚠️  Error capturing response: {e}")
                        # If something fails, just continue normally
                        await route.continue_()
                else:
                    # Not a JS chunk, just continue normally
                    await route.continue_()
            
            # Register the route interceptor
            await page.route('**/*', capture_js_route)

            # Load existing cookies from config so the server sees our old session
            # and may refresh/rotate arena-auth-prod-v1 via Set-Cookie.
            try:
                _cfg = get_config()
                _bc = _cfg.get("browser_cookies") or {}
                _playwright_cookies = []
                for _ck, _cv in _bc.items():
                    if not isinstance(_ck, str) or not isinstance(_cv, str) or not _cv:
                        continue
                    _playwright_cookies.append({
                        "name": _ck, "value": _cv, "domain": ".arena.ai",
                        "path": "/", "httpOnly": False, "secure": True,
                        "sameSite": "Lax",
                    })
                if _playwright_cookies:
                    await page.context.add_cookies(_playwright_cookies)
                    debug_print(f"  🍪 Loaded {len(_playwright_cookies)} cookies from config")
            except Exception as e:
                debug_print(f"  ⚠️  Could not load cookies: {e}")

            debug_print("Navigating to arena.ai...")
            await page.goto("https://arena.ai/", wait_until="domcontentloaded")

            debug_print("Waiting for Cloudflare challenge to complete...")
            challenge_passed = False
            for i in range(12): # Up to 120 seconds
                try:
                    title = await page.title()
                except Exception:
                    title = ""
                
                if "Just a moment" not in title:
                    challenge_passed = True
                    break
                
                debug_print(f"  ⏳ Waiting for Cloudflare challenge... (attempt {i+1}/12)")
                await click_turnstile(page)
                
                try:
                    await page.wait_for_function(
                        "() => document.title.indexOf('Just a moment...') === -1", 
                        timeout=10000
                    )
                    challenge_passed = True
                    break
                except Exception:
                    pass
            
            if challenge_passed:
                debug_print("✅ Cloudflare challenge passed.")
            else:
                debug_print("❌ Cloudflare challenge took too long or failed.")
                # Even if the challenge didn't clear, persist any cookies we did get.
                # Sometimes Cloudflare/BM cookies are still set and can help subsequent attempts.
                try:
                    cookies = await page.context.cookies()
                    _capture_ephemeral_arena_auth_token_from_cookies(cookies)
                    try:
                        user_agent = await page.evaluate("() => navigator.userAgent")
                    except Exception:
                        user_agent = None

                    config = get_config()
                    ua_for_config = None
                    if not normalize_user_agent_value(config.get("user_agent")):
                        ua_for_config = user_agent
                    if _upsert_browser_session_into_config(config, cookies, user_agent=ua_for_config):
                        save_config(config)
                except Exception:
                    pass
                return

            # Give it time to capture all JS responses
            await asyncio.sleep(5)

            # Persist cookies + UA for downstream httpx/chrome-fetch alignment.
            cookies = await page.context.cookies()
            _capture_ephemeral_arena_auth_token_from_cookies(cookies)
            try:
                user_agent = await page.evaluate("() => navigator.userAgent")
            except Exception:
                user_agent = None

            config = get_config()
            # Prefer keeping an existing UA (often set by Chrome contexts) instead of overwriting with Camoufox UA.
            ua_for_config = None
            if not normalize_user_agent_value(config.get("user_agent")):
                ua_for_config = user_agent
            if _upsert_browser_session_into_config(config, cookies, user_agent=ua_for_config):
                save_config(config)

            if str(config.get("cf_clearance") or "").strip():
                debug_print(f"✅ Saved cf_clearance token: {str(config.get('cf_clearance'))[:20]}...")
            else:
                debug_print("⚠️ Could not find cf_clearance cookie.")

            page_body = ""

            # Extract models
            debug_print("Extracting models from page...")
            try:
                page_body = await page.content()
                match = re.search(r'{\\"initialModels\\":(\[.*?\]),\\"initialModel[A-Z]Id', page_body, re.DOTALL)
                if match:
                    models_json = match.group(1).encode().decode('unicode_escape')
                    models = json.loads(models_json)
                    # `initialModels` mirrors the leaderboard, which includes models that are NOT
                    # selectable in the chat UI (e.g. gpt-5.6-sol-*). The chat/direct-battle mode
                    # only accepts models the UI marks `userSelectable: true`. Filter here so we
                    # don't advertise (or try to send) models arena.ai will reject with 404.
                    selectable = [m for m in models if m.get("userSelectable")]
                    # The chat UI additionally only exposes models that have a `provider`
                    # (stealth models without a provider can't be chosen in chat / direct-battle).
                    # Keep only userSelectable AND provider-bearing models so the advertised
                    # list matches what the chat UI actually offers (~300, no gpt-5.6-sol).
                    selectable_with_provider = [m for m in selectable if m.get("provider")]
                    filtered = selectable_with_provider or selectable or models  # never persist an empty list
                    # CRITICAL: initialModels from the HTML can be a *different schema* (name/rank/org
                    # without id/publicName/provider). Never overwrite an existing models list that has
                    # valid `id`s with a batch that lacks them — that breaks create-evaluation (404).
                    # Even if existing models also lack id (previous corruption), keep them rather
                    # than replace with a leaderboard-only schema that has no id at all.
                    if filtered:
                        html_has_ids = any(m.get("id") and m.get("publicName") for m in filtered)
                        if not html_has_ids:
                            existing_models = get_models()
                            existing_has_ids = any(m.get("id") and m.get("publicName") for m in existing_models)
                            if existing_has_ids or (existing_models and len(existing_models) >= len(filtered)):
                                debug_print("⚠️ HTML models lack 'id' — keeping existing models (don't clobber RT list).")
                                filtered = existing_models
                    save_models(filtered)
                    debug_print(f"✅ Saved {len(filtered)} models (userSelectable + provider, was {len(models)})")
                else:
                    debug_print("⚠️ Could not find models in page")
            except Exception as e:
                debug_print(f"❌ Error extracting models: {e}")

            # Extract Next-Action IDs from captured JavaScript responses (Aggressive Discovery)
            debug_print(f"\nExtracting Next-Action IDs from {len(captured_responses)} captured JS responses...")
            try:
                if not captured_responses:
                    debug_print("  ⚠️  No JavaScript responses were captured")
                else:
                    debug_print(f"  📦 Scanning {len(captured_responses)} JavaScript chunks for Server Actions...")
                    # Regex pattern based on Next.js server-reference generation:
                    # (0,a.createServerReference)("HASH",a.callServer,void 0,a.findSourceMapURL,"ACTION_NAME")
                    action_pattern = r'\(0,[a-zA-Z_$][\w$]*\.createServerReference\)\(["\']([\w\d]*?)["\'],[a-zA-Z_$][\w$]*\.callServer,void 0,[a-zA-Z_$][\w$]*\.findSourceMapURL,["\'](\w+)["\']\)'
                    
                    found_count = 0
                    for item in captured_responses:
                        text = str(item.get('text', ''))
                        matches = re.findall(action_pattern, text)
                        for action_id, action_name in matches:
                            if _state_module.DISCOVERED_ACTIONS.get(action_name) != action_id:
                                _state_module.DISCOVERED_ACTIONS[action_name] = action_id
                                found_count += 1
                    
                    if found_count > 0:
                        debug_print(f"  ✅ Updated {found_count} Next-Action IDs in memory")
                        if "generateUploadUrl" in _state_module.DISCOVERED_ACTIONS:
                            config["next_action_upload"] = _state_module.DISCOVERED_ACTIONS["generateUploadUrl"]
                        if "getSignedUrl" in _state_module.DISCOVERED_ACTIONS:
                            config["next_action_signed_url"] = _state_module.DISCOVERED_ACTIONS["getSignedUrl"]
                        save_config(config)
                    
                    if _state_module.DISCOVERED_ACTIONS:
                        debug_print(f"✅ Discovered {len(_state_module.DISCOVERED_ACTIONS)} Server Actions (New/Updated: {found_count})")
                    
            except Exception as e:
                debug_print(f"❌ Error during Server Action discovery: {e}")
                debug_print("   This is optional - continuing without them")

            # Extract reCAPTCHA sitekey/action from captured JS responses (helps keep up with LMArena changes).
            debug_print(f"\nExtracting reCAPTCHA params from {len(captured_responses)} captured JS responses...")
            try:
                discovered_sitekey: Optional[str] = None
                discovered_action: Optional[str] = None

                for item in captured_responses or []:
                    if not isinstance(item, dict):
                        continue
                    text = item.get("text")
                    if not isinstance(text, str) or not text:
                        continue
                    sitekey, action = extract_recaptcha_params_from_text(text)
                    if sitekey and not discovered_sitekey:
                        discovered_sitekey = sitekey
                    if action and not discovered_action:
                        discovered_action = action
                    if discovered_sitekey and discovered_action:
                        break

                # Fallback: try the HTML we already captured.
                if (not discovered_sitekey or not discovered_action) and page_body:
                    sitekey, action = extract_recaptcha_params_from_text(page_body)
                    if sitekey and not discovered_sitekey:
                        discovered_sitekey = sitekey
                    if action and not discovered_action:
                        discovered_action = action

                if discovered_sitekey:
                    config["recaptcha_sitekey"] = discovered_sitekey
                if discovered_action:
                    config["recaptcha_action"] = discovered_action

                if discovered_sitekey or discovered_action:
                    save_config(config)
                    debug_print("✅ Saved reCAPTCHA params to config")
                    if discovered_sitekey:
                        debug_print(f"   Sitekey: {discovered_sitekey[:20]}...")
                    if discovered_action:
                        debug_print(f"   Action: {discovered_action}")
                else:
                    debug_print("⚠️ Could not extract reCAPTCHA params; using defaults")
            except Exception as e:
                debug_print(f"❌ Error extracting reCAPTCHA params: {e}")
                debug_print("   This is optional - continuing without them")

            # Extract Supabase anon key from captured JS responses (in-memory only).
            # This enables refreshing expired `arena-auth-prod-v1` sessions without user interaction.
            try:
                global SUPABASE_ANON_KEY
                if not str(SUPABASE_ANON_KEY or "").strip():
                    discovered_key: Optional[str] = None
                    for item in captured_responses or []:
                        if not isinstance(item, dict):
                            continue
                        text = item.get("text")
                        if not isinstance(text, str) or not text:
                            continue
                        discovered_key = extract_supabase_anon_key_from_text(text)
                        if discovered_key:
                            break
                    if (not discovered_key) and page_body:
                        discovered_key = extract_supabase_anon_key_from_text(page_body)
                    if discovered_key:
                        SUPABASE_ANON_KEY = discovered_key
                        debug_print(f"✅ Discovered Supabase anon key: {discovered_key[:16]}...")
                        # Persist to config so token refresh survives restarts
                        try:
                            _cfg = get_config()
                            if _cfg.get("supabase_anon_key") != discovered_key:
                                _cfg["supabase_anon_key"] = discovered_key
                                save_config(_cfg, preserve_auth_tokens=True)
                        except Exception:
                            pass
                    else:
                        # Diagnostic: dump JWT candidates so we can find the anon key format
                        import re as _re
                        _jwt_re = _re.compile(r"eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+")
                        _cands = set()
                        for _item in (captured_responses or []):
                            _txt = str(_item.get("text") or "")
                            _cands.update(_jwt_re.findall(_txt))
                        if page_body:
                            _cands.update(_jwt_re.findall(page_body))
                        _roles = []
                        for _c in list(_cands)[:30]:
                            try:
                                _p = _c.split(".")[1]
                                _pad = _p + "=" * (-len(_p) % 4)
                                _pl = json.loads(base64.urlsafe_b64decode(_pad))
                                _roles.append(f"{_pl.get('role')}|{_pl.get('ref')}|{_c[:35]}...")
                            except Exception:
                                pass
                        if _roles:
                            debug_print(f"🔍 JWT candidates found ({len(_roles)}): {_roles[:5]}")
            except Exception:
                pass

            debug_print("✅ Initial data retrieval complete")
    except Exception as e:
        debug_print(f"❌ An error occurred during initial data retrieval: {e}")

async def periodic_refresh_task():
    """Background task to refresh cf_clearance and models every 30 minutes"""
    while True:
        try:
            # Wait 30 minutes (1800 seconds)
            await asyncio.sleep(1800)
            debug_print("\n" + "="*60)
            debug_print("🔄 Starting scheduled 30-minute refresh...")
            debug_print("="*60)
            await get_initial_data()
            debug_print("✅ Scheduled refresh completed")
            debug_print("="*60 + "\n")
        except Exception as e:
            debug_print(f"❌ Error in periodic refresh task: {e}")
            # Continue the loop even if there's an error
            continue

async def startup_event():
    # Prevent unit tests (TestClient/ASGITransport) from clobbering the user's real config.json
    # and running slow browser/network startup routines.
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return

    # Ignore SIGPIPE to prevent Playwright Node.js EPIPE from killing the process
    import signal
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)

    try:
        # Ensure config and models files exist
        config = get_config()
        if not config.get("api_keys"):
            # Fresh install with no key anywhere: mint one and store it in .env
            # (save_config -> _persist_secrets_to_env does the actual write), so the
            # credential never lands in config.json.
            generated = "sk-" + "".join(random.choices(
                "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=48))
            config["api_keys"] = [
                {
                    "name": "Default Key",
                    "key": generated,
                    "rpm": 60,
                    "created": int(time.time()),
                }
            ]
            debug_print(f"🔑 Generated bridge API key -> .env ({_secrets.redact(generated)})")
        save_config(config)
        save_models(get_models())
        # Load usage stats from config
        load_usage_stats()
        
        # 1. First, get initial data (cookies, models, etc.)
        # We await this so we have the cookie BEFORE trying reCAPTCHA
        await get_initial_data() 

        # Best-effort: if the user-configured auth cookies are expired base64 sessions, try to refresh one so the
        # Camoufox proxy worker can start with a valid `arena-auth-prod-v1` cookie.
        try:
            refreshed = await maybe_refresh_expired_auth_tokens()
        except Exception:
            refreshed = None
        if refreshed:
            debug_print("🔄 Refreshed arena-auth-prod-v1 session (startup).")
        
        # 2. Do not prefetch reCAPTCHA at startup.
        # The internal Camoufox userscript-proxy mints tokens in-page for strict models, and non-strict
        # requests can refresh on-demand. Avoid launching extra browser instances at startup.

        # 3. Start background tasks
        asyncio.create_task(periodic_refresh_task())
        
        # Mark userscript proxy as active at startup to allow immediate delegation
        # to the internal Camoufox proxy worker.
        global last_userscript_poll, USERSCRIPT_PROXY_LAST_POLL_AT
        # Do not mark the internal proxy alive merely because its task was
        # scheduled. It must prove liveness through an actual poll/push.
        last_userscript_poll = 0.0
        USERSCRIPT_PROXY_LAST_POLL_AT = 0.0
        
        async def safe_proxy_worker():
            try:
                await camoufox_proxy_worker()
            except (SystemExit, KeyboardInterrupt):
                pass
            except Exception as e:
                debug_print(f"⚠️ Camoufox proxy worker crashed ({type(e).__name__}): {e}")
        asyncio.create_task(safe_proxy_worker())
        
    except Exception as e:
        debug_print(f"❌ Error during startup: {e}")
        # Continue anyway - server should still start


@app.get("/proxy/tasks")
async def get_proxy_tasks(api_key: dict = Depends(rate_limit_api_key)):
    """
    Endpoint for the Userscript to poll for new tasks.
    Requires a valid API key to prevent unauthorized task stealing.
    """
    global last_userscript_poll
    last_userscript_poll = time.time()
    
    # In a real multi-user scenario, we might want to filter tasks by user/session.
    # For this bridge, we assume a single trust domain.
    current_tasks = list(proxy_task_queue)
    proxy_task_queue.clear()
    return current_tasks

@app.post("/proxy/result/{task_id}")
async def post_proxy_result(task_id: str, request: Request, api_key: dict = Depends(rate_limit_api_key)):
    """
    Endpoint for the Userscript to post results (chunks or full response).
    """
    try:
        data = await request.json()
        if task_id in proxy_pending_tasks:
            future = proxy_pending_tasks[task_id]
            if not future.done():
                future.set_result(data)
        return {"status": "ok"}
    except Exception as e:
        debug_print(f"❌ Error processing proxy result for {task_id}: {e}")
        return {"status": "error", "message": str(e)}

@app.post("/api/v1/userscript/poll")
async def userscript_poll(request: Request):
    """
    Long-poll endpoint for the Tampermonkey/Violetmonkey proxy client (docs/lmbridge-proxy.user.js).
    Returns 204 when no jobs are available.
    """
    _userscript_proxy_check_secret(request)

    global USERSCRIPT_PROXY_LAST_POLL_AT, last_userscript_poll
    now = time.time()
    USERSCRIPT_PROXY_LAST_POLL_AT = now
    # Keep legacy proxy detection working too.
    last_userscript_poll = now

    try:
        data = await request.json()
    except Exception:
        data = {}

    cfg = get_config()
    timeout_seconds = data.get("timeout_seconds")
    if timeout_seconds is None:
        timeout_seconds = cfg.get("userscript_proxy_poll_timeout_seconds", 25)
    try:
        timeout_seconds = int(timeout_seconds)
    except Exception:
        timeout_seconds = 25
    timeout_seconds = max(0, min(timeout_seconds, 60))

    _cleanup_userscript_proxy_jobs(cfg)

    queue = _get_userscript_proxy_queue()
    end = time.time() + float(timeout_seconds)
    while True:
        remaining = end - time.time()
        if remaining <= 0:
            return Response(status_code=204)
        try:
            job_id = await asyncio.wait_for(queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            return Response(status_code=204)

        job = _USERSCRIPT_PROXY_JOBS.get(str(job_id))
        if not isinstance(job, dict):
            continue
        # Mark as picked up as soon as we hand the job to a poller so the server-side pickup timeout
        # doesn't trip while the poller/browser is starting.
        try:
            picked = job.get("picked_up_event")
            if isinstance(picked, asyncio.Event) and not picked.is_set():
                picked.set()
                if not job.get("picked_up_at_monotonic"):
                    job["picked_up_at_monotonic"] = time.monotonic()
            if str(job.get("phase") or "") == "queued":
                job["phase"] = "picked_up"
        except Exception:
            pass
        return {"job_id": str(job_id), "payload": job.get("payload") or {}}


@app.post("/api/v1/userscript/push")
async def userscript_push(request: Request):
    """
    Receives streamed lines from the userscript proxy and feeds them into the waiting request.
    """
    _userscript_proxy_check_secret(request)

    try:
        data = await request.json()
    except Exception:
        data = {}

    job_id = str(data.get("job_id") or "").strip()
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing job_id")

    job = _USERSCRIPT_PROXY_JOBS.get(job_id)
    if not isinstance(job, dict):
        raise HTTPException(status_code=404, detail="Unknown job_id")

    fetch_started = data.get("upstream_fetch_started")
    if fetch_started is None:
        fetch_started = data.get("fetch_started")
    status_code = data.get("status")
    if fetch_started or isinstance(status_code, int):
        try:
            if not job.get("upstream_fetch_started_at_monotonic"):
                job["upstream_fetch_started_at_monotonic"] = time.monotonic()
        except Exception:
            pass

    if isinstance(status_code, int):
        job["status_code"] = int(status_code)
        status_event = job.get("status_event")
        if isinstance(status_event, asyncio.Event):
            status_event.set()
    headers = data.get("headers")
    if isinstance(headers, dict):
        job["headers"] = headers

    error = data.get("error")
    if error:
        job["error"] = str(error)

    lines = data.get("lines") or []
    if isinstance(lines, list):
        for line in lines:
            if line is None:
                continue
            await job["lines_queue"].put(str(line))

    if bool(data.get("done")):
        job["done"] = True
        done_event = job.get("done_event")
        if isinstance(done_event, asyncio.Event):
            done_event.set()
        status_event = job.get("status_event")
        if isinstance(status_event, asyncio.Event):
            status_event.set()
        await job["lines_queue"].put(None)

    return {"status": "ok"}


# --- OpenAI Compatible API Endpoints ---

@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint for monitoring"""
    try:
        models = get_models()
        config = get_config()
        
        # Basic health checks
        has_cf_clearance = bool(config.get("cf_clearance"))
        has_models = len(models) > 0
        has_api_keys = len(config.get("api_keys", [])) > 0
        
        status = "healthy" if (has_cf_clearance and has_models) else "degraded"
        
        return {
            "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "checks": {
                "cf_clearance": has_cf_clearance,
                "models_loaded": has_models,
                "model_count": len(models),
                "api_keys_configured": has_api_keys
            }
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(e)
        }

# Dashboard refresh endpoint used by WEB/server.js.
@app.post("/api/v1/refresh-tokens")
async def refresh_tokens_endpoint(api_key: dict = Depends(rate_limit_api_key)):
    """Force-refresh the arena auth token via Supabase refresh_token grant (criterion 14).
    get_initial_data() only re-fetches pages; it does NOT extend the JWT expiry."""
    try:
        cfg = get_config()
        tokens = cfg.get("auth_tokens", []) or []
        refreshed_any = False
        if tokens:
            # Try each refresh strategy in order: supabase (needs anon key) -> lmarena http (cookie rotation)
            anon = cfg.get("supabase_anon_key", "") or ""
            for i, raw_tok in enumerate(tokens):
                try:
                    if not str(raw_tok or "").startswith("base64-"):
                        continue
                    new_tok = None
                    if anon:
                        new_tok = await refresh_arena_auth_token_via_supabase(
                            str(raw_tok), anon_key=anon or None
                        )
                    if not new_tok:
                        # LMArena rotates the cookie server-side; no anon key needed
                        debug_print(f"🔄 Token {i}: trying lmarena_http refresh...")
                        try:
                            new_tok = await refresh_arena_auth_token_via_lmarena_http(
                                str(raw_tok), config=cfg
                            )
                            debug_print(f"  lmarena_http result: {'OK' if new_tok else 'None'}")
                        except Exception as _re:
                            debug_print(f"  lmarena_http exception: {_re}")
                            new_tok = None
                    if new_tok:
                        tokens[i] = new_tok
                        refreshed_any = True
                except Exception as e:
                    debug_print(f"⚠️ Token {i} refresh failed: {e}")
            if refreshed_any:
                cfg["auth_tokens"] = tokens
                # CRITICAL: preserve_auth_tokens=False — otherwise save_config re-reads the
                # OLD tokens from disk and overwrites the freshly rotated ones (criterion 14 bug).
                save_config(cfg, preserve_auth_tokens=False)
                debug_print("✅ refresh-tokens: supabase refresh succeeded, tokens rotated")
        if not refreshed_any:
            # Fallback: full Camoufox re-fetch (slow but may recover cookies)
            debug_print("🔄 refresh-tokens: supabase refresh not possible, falling back to get_initial_data()")
            await get_initial_data()
        return {"ok": True, "auth_tokens": get_config().get("auth_tokens", []), "models": get_models()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Refresh failed: {exc}")


# --- Ollama-compatible stubs (OpenWebUI probes these endpoints) ---

@app.get("/api/v1/api/tags")
async def ollama_tags(api_key: dict = Depends(rate_limit_api_key)):
    models = get_models()
    
    valid_models = [m for m in models 
                   if (m.get('capabilities', {}).get('outputCapabilities', {}).get('text')
                       or m.get('capabilities', {}).get('outputCapabilities', {}).get('search')
                       or m.get('capabilities', {}).get('outputCapabilities', {}).get('image'))
                   and m.get('organization')]
    
    ollama_models = [
        {
            "name": model.get("publicName", ""),
            "model": model.get("publicName", ""),
            "modified_at": "2024-01-01T00:00:00Z",
            "size": 0
        }
        for model in valid_models if model.get("publicName")
    ]
    return {"models": ollama_models}


@app.get("/api/v1/api/ps")
async def ollama_ps(api_key: dict = Depends(rate_limit_api_key)):
    return {"models": []}


@app.get("/api/v1/api/version")
async def ollama_version(api_key: dict = Depends(rate_limit_api_key)):
    return {"version": "0.1.0"}

@app.get("/api/v1/models")
async def list_models(api_key: dict = Depends(rate_limit_api_key)):
    try:
        models = get_models()
        
        # Filter for models with text OR search OR image output capability AND a provider
        # (stealth models without provider can't be selected in chat UI — always include
        # image models, no special key needed)
        valid_models = [m for m in models 
                       if (m.get('capabilities', {}).get('outputCapabilities', {}).get('text')
                           or m.get('capabilities', {}).get('outputCapabilities', {}).get('search')
                           or m.get('capabilities', {}).get('outputCapabilities', {}).get('image')
                           or m.get('capabilities', {}).get('outputCapabilities', {}).get('video')
                           or m.get('capabilities', {}).get('outputCapabilities', {}).get('web'))
                       and m.get('provider')]
        
        return {
            "object": "list",
            "data": [
                {
                    "id": model.get("publicName"),
                    "name": model.get("publicName"),
                    "publicName": model.get("publicName"),
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": model.get("organization", "lmarena"),
                    "organization": model.get("organization"),
                    "rank": model.get("rank", 0),
                    "capabilities": model.get("capabilities", {}),
                    "rankByModality": model.get("rankByModality", {})
                } for model in valid_models if model.get("publicName")
            ]
        }
    except Exception as e:
        debug_print(f"❌ Error listing models: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load models: {str(e)}")


@app.get("/api/v1/deployments/{message_id}/download")
async def download_deployment(message_id: str, api_key: dict = Depends(rate_limit_api_key)):  # noqa: ARG001
    """
    Download a deployed webdev site as a ZIP archive.
    Fetches the site's HTML (with the embed header so we get the real app,
    not the arena.site wrapper banner) and all linked assets, then packs
    them into a zip file. Mirrors the client-side JSZip download in the
    arena.ai chat UI (criterion 12).
    """
    import zipfile
    import io
    import re
    from urllib.parse import urljoin

    site_url = f"https://{message_id}.arena.site/"
    headers = {"User-Agent": "Mozilla/5.0", "Sec-Fetch-Dest": "iframe"}

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        try:
            resp = await client.get(f"{site_url}?embed=true", headers=headers)
            resp.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Failed to fetch site: {e}")

        html = resp.text
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("index.html", html)
            seen = set()
            for tag_attr in ['src="', 'href="']:
                for match in re.finditer(re.escape(tag_attr) + r'([^"]+)', html):
                    asset_url = match.group(1)
                    if asset_url.startswith(("data:", "#", "http://", "https://")) or asset_url in seen:
                        continue
                    seen.add(asset_url)
                    full_url = urljoin(site_url, asset_url)
                    try:
                        asset_resp = await client.get(full_url, headers=headers, timeout=15)
                        if asset_resp.status_code == 200:
                            zip_path = asset_url.lstrip("/")
                            if zip_path:
                                zf.writestr(zip_path, asset_resp.content)
                    except Exception:
                        pass

        zip_buffer.seek(0)
        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{message_id}.zip"'}
        )


@app.get("/api/v1/_debug/stream")
async def debug_stream(api_key: dict = Depends(rate_limit_api_key)):  # noqa: ARG001
    async def _gen():
        yield ": keep-alive\n\n"
        await asyncio.sleep(0.05)
        yield 'data: {"ok":true}\n\n'
        yield "data: [DONE]\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")

@app.post("/api/v1/chat/completions")
async def api_chat_completions(request: Request, api_key: dict = Depends(rate_limit_api_key)):
    debug_print("\n" + "="*80)
    debug_print("🔵 NEW API REQUEST RECEIVED")
    debug_print("="*80)
    
    try:
        # Parse request body with error handling
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            debug_print(f"❌ Invalid JSON in request body: {e}")
            raise HTTPException(status_code=400, detail=f"Invalid JSON in request body: {str(e)}")
        except Exception as e:
            debug_print(f"❌ Failed to read request body: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to read request body: {str(e)}")
        
        debug_print(f"📥 Request body keys: {list(body.keys())}")
        
        # Validate required fields
        model_public_name = body.get("model")
        messages = body.get("messages", [])
        stream = body.get("stream", False)
        
        debug_print(f"🌊 Stream mode: {stream}")
        debug_print(f"🤖 Requested model: {model_public_name}")
        debug_print(f"💬 Number of messages: {len(messages)}")
        
        if not model_public_name:
            debug_print("❌ Missing 'model' in request")
            raise HTTPException(status_code=400, detail="Missing 'model' in request body.")
        
        if not messages:
            debug_print("❌ Missing 'messages' in request")
            raise HTTPException(status_code=400, detail="Missing 'messages' in request body.")
        
        if not isinstance(messages, list):
            debug_print("❌ 'messages' must be an array")
            raise HTTPException(status_code=400, detail="'messages' must be an array.")
        
        if len(messages) == 0:
            debug_print("❌ 'messages' array is empty")
            raise HTTPException(status_code=400, detail="'messages' array cannot be empty.")

        # Find model ID from public name
        try:
            models = get_models()
            debug_print(f"📚 Total models loaded: {len(models)}")
        except Exception as e:
            debug_print(f"❌ Failed to load models: {e}")
            raise HTTPException(
                status_code=503,
                detail="Failed to load model list from LMArena. Please try again later."
            )
        
        model_id = None
        model_org = None
        model_capabilities = {}
        
        for m in models:
            if m.get("publicName") == model_public_name:
                model_id = m.get("id")
                model_org = m.get("organization")
                model_capabilities = m.get("capabilities", {})
                break
        
        if not model_id:
            debug_print(f"❌ Model '{model_public_name}' not found in model list")
            raise HTTPException(
                status_code=404, 
                detail=f"Model '{model_public_name}' not found. Use /api/v1/models to see available models."
            )
        
        # Check if model is a stealth model (no organization)
        if not model_org:
            debug_print(f"❌ Model '{model_public_name}' is a stealth model (no organization)")
            raise HTTPException(
                status_code=403,
                detail="You do not have access to stealth models. Contact cloudwaddie for more info."
            )
        
        debug_print(f"✅ Found model ID: {model_id}")
        debug_print(f"🔧 Model capabilities: {model_capabilities}")
        
        # Determine modality based on model capabilities.
        # Priority: image > video > webdev > search > chat
        # Allow explicit override via request body (e.g. {"modality": "webdev"}) for testing.
        out_caps = model_capabilities.get("outputCapabilities", {})
        if body.get("modality"):
            modality = str(body.get("modality")).strip().lower()
            debug_print(f"🔧 Modality OVERRIDE from request body: {modality}")
        elif out_caps.get("image"): modality = "image"
        elif out_caps.get("video"): modality = "video"
        elif out_caps.get("web"): modality = "webdev"
        elif out_caps.get("search"): modality = "search"
        else: modality = "chat"
        
        debug_print(f"🔍 Model modality: {modality}")

        # Log usage
        try:
            model_usage_stats[model_public_name] += 1
            # Save stats immediately after incrementing
            config = get_config()
            config["usage_stats"] = dict(model_usage_stats)
            # Total requests counter
            config["total_requests"] = config.get("total_requests", 0) + 1
            # Today's requests (reset daily — keyed by YYYY-MM-DD date)
            today = datetime.now().strftime("%Y-%m-%d")
            usage_today = config.get("usage_today", {})
            usage_today[today] = usage_today.get(today, 0) + 1
            config["usage_today"] = usage_today
            save_config(config)
        except Exception as e:
            # Don't fail the request if usage logging fails
            debug_print(f"⚠️  Failed to log usage stats: {e}")

        # Extract system prompt if present and prepend to first user message
        system_prompt = ""
        system_messages = [m for m in messages if m.get("role") == "system"]
        if system_messages:
            system_prompt = "\n\n".join([_coerce_message_content_to_text(m.get("content", "")) for m in system_messages])
            debug_print(f"📋 System prompt found: {system_prompt[:100]}..." if len(system_prompt) > 100 else f"📋 System prompt: {system_prompt}")
        
        # Process last message content (may include images)
        try:
            last_message_content = messages[-1].get("content", "")
            try:
                prompt, experimental_attachments = await process_message_content(last_message_content, model_capabilities)
            except Exception as e:
                debug_print(f"❌ Failed to process message content: {e}")
                raise HTTPException(status_code=400, detail=f"Invalid message content: {str(e)}")
            
            # If there's a system prompt and this is the first user message, prepend it
            if system_prompt:
                prompt = f"{system_prompt}\n\n{prompt}"
                debug_print(f"✅ System prompt prepended to user message")
        except Exception as e:
            debug_print(f"❌ Failed to process message content: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"Failed to process message content: {str(e)}"
            )
        
        # Validate prompt
        if not prompt:
            # If no text but has attachments, that's okay for vision models
            if not experimental_attachments:
                debug_print("❌ Last message has no content")
                raise HTTPException(status_code=400, detail="Last message must have content.")
        
        # Log prompt length for debugging character limit issues
        debug_print(f"📝 User prompt length: {len(prompt)} characters")
        debug_print(f"🖼️  Attachments: {len(experimental_attachments)} images")
        debug_print(f"📝 User prompt preview: {prompt[:100]}..." if len(prompt) > 100 else f"📝 User prompt: {prompt}")
        
        # Check for reasonable character limit (LMArena appears to have limits)
        # Typical limit seems to be around 32K-64K characters based on testing
        MAX_PROMPT_LENGTH = 113567  # User hardcoded limit
        if len(prompt) > MAX_PROMPT_LENGTH:
            error_msg = f"Prompt too long ({len(prompt)} characters). LMArena has a character limit of approximately {MAX_PROMPT_LENGTH} characters. Please reduce the message size."
            debug_print(f"❌ {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
        
        # Use API key + conversation tracking
        api_key_str = api_key["key"]

        # --- NEW: Get reCAPTCHA v3 Token for Payload ---
        # For strict models, we defer token minting to the in-browser fetch transport to avoid extra
        # automation-driven token requests (which can lower scores and increase flakiness).
        use_browser_fetch_for_model = model_public_name in STRICT_BROWSER_FETCH_MODELS
        strict_chrome_fetch_model = use_browser_fetch_for_model  # compat alias

        recaptcha_token = ""
        if strict_chrome_fetch_model:
            # If the internal proxy is active, we MUST NOT use a cached token, as it causes 403s.
            # Instead, we pass an empty string and let the in-page minting handle it.
            if (time.time() - last_userscript_poll) < 15:
                debug_print("🔐 Strict model + Proxy: token will be minted in-page.")
                recaptcha_token = ""
            else:
                # Best-effort: use a cached token so browser transports don't have to wait on grecaptcha to load.
                # (They can still mint in-session if needed.)
                recaptcha_token = get_cached_recaptcha_token()
                if recaptcha_token:
                    debug_print("🔐 Strict model: using cached reCAPTCHA v3 token in payload.")
                else:
                    debug_print("🔐 Strict model: reCAPTCHA token will be minted in the Chrome fetch session.")
        else:
            # reCAPTCHA v3 tokens can behave like single-use tokens; force a fresh token for streaming requests.
            # For streaming, we defer this until inside generate_stream to avoid blocking initial headers.
            if stream:
                recaptcha_token = ""
            else:
                recaptcha_token = await refresh_recaptcha_token(force_new=False)
                if not recaptcha_token:
                    debug_print("❌ Cannot proceed, failed to get reCAPTCHA token.")
                    raise HTTPException(
                        status_code=503,
                        detail="Service Unavailable: Failed to acquire reCAPTCHA token. The bridge server may be blocked."
                    )
                debug_print(f"🔑 Using reCAPTCHA v3 token: {recaptcha_token[:20]}...")
        # -----------------------------------------------
        
        # Generate conversation ID from context (API key + model + first user message)
        import hashlib
        first_user_message = next((m.get("content", "") for m in messages if m.get("role") == "user"), "")
        if isinstance(first_user_message, list):
            # Handle array content format
            first_user_message = str(first_user_message)
        conversation_key = f"{api_key_str}_{model_public_name}_{first_user_message[:100]}"
        conversation_id = hashlib.sha256(conversation_key.encode()).hexdigest()[:16]

        # Follow-up support: if the client passes back a conversation_id (returned in
        # every chat.completion response), continue THAT session instead of hashing a
        # new one from the (now different) message content.
        explicit_cid = body.get("conversation_id") or body.get("session_id")
        if explicit_cid:
            debug_print(f"🔄 Client requested conversation_id: {explicit_cid}")
            # Only reuse it if we actually know this session for this API key; otherwise
            # the id is stale (e.g. bridge restarted) and we must start fresh.
            per_key_check = chat_sessions.get(api_key_str, {})
            if explicit_cid in per_key_check:
                conversation_id = str(explicit_cid)
                debug_print(f"✅ Continuing known session {conversation_id}")
            else:
                debug_print(f"⚠️ Unknown conversation_id {explicit_cid}, starting new session")
        
        debug_print(f"🔑 API Key: {api_key_str[:20]}...")
        debug_print(f"💭 Auto-generated Conversation ID: {conversation_id}")
        debug_print(f"🔑 Conversation key: {conversation_key[:100]}...")

        # Headers are prepared after selecting an auth token (or when falling back to browser-only transports).
        headers: dict[str, str] = {}
        
        # Check if conversation exists for this API key (robust to tests patching chat_sessions to a plain dict)
        per_key_sessions = chat_sessions.setdefault(api_key_str, {})
        session = per_key_sessions.get(conversation_id)
        
        # Detect retry: if session exists and last message is same user message (no assistant response after it)
        is_retry = False
        retry_message_id = None
        
        if session and len(session.get("messages", [])) >= 2:
            stored_messages = session["messages"]
            # Check if last stored message is from user with same content
            if stored_messages[-1]["role"] == "user" and stored_messages[-1]["content"] == prompt:
                # This is a retry - client sent same message again without assistant response
                is_retry = True
                retry_message_id = stored_messages[-1]["id"]
                # Get the assistant message ID that needs to be regenerated
                if len(stored_messages) >= 2 and stored_messages[-2]["role"] == "assistant":
                    # There was a previous assistant response - we'll retry that one
                    retry_message_id = stored_messages[-2]["id"]
                    debug_print(f"🔁 RETRY DETECTED - Regenerating assistant message {retry_message_id}")
        
        if is_retry and retry_message_id:
            debug_print(f"🔁 Using RETRY endpoint")
            # Use LMArena's retry endpoint
            # Format: PUT /nextjs-api/stream/retry-evaluation-session-message/{sessionId}/messages/{messageId}
            payload = {}
            url = f"https://arena.ai/nextjs-api/stream/retry-evaluation-session-message/{session['conversation_id']}/messages/{retry_message_id}"
            debug_print(f"📤 Target URL: {url}")
            debug_print(f"📦 Using PUT method for retry")
            http_method = "PUT"
        elif not session:
            debug_print("🆕 Creating NEW conversation session")
            # New conversation - Generate all IDs at once (like the browser does)
            session_id = str(uuid7())
            user_msg_id = str(uuid7())
            model_msg_id = str(uuid7())
            model_b_msg_id = str(uuid7())
            
            debug_print(f"🔑 Generated session_id: {session_id}")
            debug_print(f"👤 Generated user_msg_id: {user_msg_id}")
            debug_print(f"🤖 Generated model_msg_id: {model_msg_id}")
            debug_print(f"🤖 Generated model_b_msg_id: {model_b_msg_id}")
             
            # arena.ai changed its API: the old "direct" mode is no longer accepted for new
            # conversations ("400 'direct' mode is not allowed when starting a new conversation").
            # Current valid modes (matching upstream g4f):
            #   - "direct-battle": single model (only modelAId)  <- bridge uses this
            #   - "side-by-side": two models (modelAId + modelBId)
            #   - "battle": neither specified
            # For direct-battle (single model) upstream omits modelBMessageId; we follow suit.
            payload = {
                "id": session_id,
                "mode": "direct-battle",
                "modelAId": model_id,
                "userMessageId": user_msg_id,
                "modelAMessageId": model_msg_id,
                "userMessage": {
                    "content": prompt,
                    "experimental_attachments": experimental_attachments,
                    "metadata": {}
                },
                "modality": modality,
                "recaptchaV3Token": recaptcha_token, # <--- ADD TOKEN HERE
            }
            url = f"https://arena.ai{STREAM_CREATE_EVALUATION_PATH}"
            debug_print(f"📤 Target URL: {url}")
            debug_print(f"📦 Payload structure: Simple userMessage format")
            debug_print(f"🔍 Full payload: {json.dumps(payload, indent=2)}")
            http_method = "POST"
        else:
            debug_print("🔄 Using EXISTING conversation session")
            # Follow-up message - Generate new message IDs
            user_msg_id = str(uuid7())
            debug_print(f"👤 Generated followup user_msg_id: {user_msg_id}")
            model_msg_id = str(uuid7())
            debug_print(f"🤖 Generated followup model_msg_id: {model_msg_id}")
            model_b_msg_id = str(uuid7())
            debug_print(f"🤖 Generated followup model_b_msg_id: {model_b_msg_id}")
             
            payload = {
                "id": session["conversation_id"],
                "modelAId": model_id,
                "userMessageId": user_msg_id,
                "modelAMessageId": model_msg_id,
                "modelBMessageId": model_b_msg_id,
                "userMessage": {
                    "content": prompt,
                    "experimental_attachments": experimental_attachments,
                    "metadata": {}
                },
                "modality": modality,
                "recaptchaV3Token": recaptcha_token, # <--- ADD TOKEN HERE
            }
            url = f"https://arena.ai/nextjs-api/stream/post-to-evaluation/{session['conversation_id']}"
            debug_print(f"📤 Target URL: {url}")
            debug_print(f"📦 Payload structure: Simple userMessage format")
            debug_print(f"🔍 Full payload: {json.dumps(payload, indent=2)}")
            http_method = "POST"

        debug_print(f"\n🚀 Making API request to LMArena...")
        # WebDev generation can take 5-10+ minutes (model writes code + deploys a site).
        # Give webdev a much larger upstream timeout; keep 120s for everything else.
        upstream_request_timeout = 900 if modality == "webdev" else 120
        debug_print(f"⏱️  Timeout set to: {upstream_request_timeout} seconds (modality={modality})")
        
        # Initialize failed tokens tracking for this request
        request_id = str(uuid.uuid4())
        failed_tokens = set()
        force_browser_transports_in_stream = False
        
        # Get initial auth token using round-robin (excluding any failed ones)
        current_token = ""
        try:
            current_token = get_next_auth_token(exclude_tokens=failed_tokens)
        except HTTPException:
            debug_print("⚠️ No auth token configured; enabling browser/proxy transports.")
            current_token = ""
            force_browser_transports_in_stream = True

        # Strict models: if round-robin picked a placeholder/invalid-looking token but there is a better token
        # available, switch to the first plausible token without mutating user config.
        if strict_chrome_fetch_model and current_token and not is_probably_valid_arena_auth_token(current_token):
            try:
                cfg_now = get_config()
                tokens_now = cfg_now.get("auth_tokens", [])
                if not isinstance(tokens_now, list):
                    tokens_now = []
            except Exception:
                tokens_now = []
            better = ""
            for cand in tokens_now:
                cand = str(cand or "").strip()
                if not cand or cand == current_token or cand in failed_tokens:
                    continue
                if is_probably_valid_arena_auth_token(cand):
                    better = cand
                    break
            if better:
                debug_print("🔑 Switching to a plausible auth token for strict model streaming.")
                current_token = better
            else:
                debug_print("⚠️ Selected auth token format looks unusual; continuing with it (no better token found).")

        # If we still don't have a usable token (e.g. only expired base64 sessions remain), try to refresh one
        # in-memory only (do not rewrite the user's config.json auth tokens).
        if (not current_token) or (not is_probably_valid_arena_auth_token(current_token)):
            try:
                refreshed = await maybe_refresh_expired_auth_tokens(exclude_tokens=failed_tokens)
            except Exception:
                refreshed = None
            if refreshed:
                debug_print("🔄 Refreshed arena-auth-prod-v1 session.")
                current_token = refreshed
        headers = get_request_headers_with_token(current_token, recaptcha_token)
        if current_token:
            debug_print(f"🔑 Using token (round-robin): {current_token[:20]}...")
        else:
            debug_print("🔑 No auth token configured (will rely on browser session cookies).")
        
        async def make_request_with_retry(url, payload, http_method, max_retries=3):
            nonlocal current_token, headers, failed_tokens, recaptcha_token

            for attempt in range(max_retries):
                try:
                    import cloudscraper as _cs
                    def _cs_request():
                        scraper = _cs.create_scraper()
                        if http_method == "PUT":
                            return scraper.put(url, json=payload, headers=headers, timeout=upstream_request_timeout)
                        else:
                            return scraper.post(url, json=payload, headers=headers, timeout=upstream_request_timeout)
                    response = await asyncio.to_thread(_cs_request)

                    log_http_status(response.status_code, "LMArena API")

                    # Log the upstream body for ANY non-2xx response we don't otherwise handle here.
                    # This is critical for 400/5xx where arena.ai returns a JSON reason in the body
                    # (e.g. which payload field is invalid), which raise_for_status() below discards.
                    if not (200 <= response.status_code < 300):
                        try:
                            _err_body = str(response.text or "")[:1000]
                            debug_print(f"📥 {response.status_code} response body: {_err_body}")
                        except Exception:
                            pass

                    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                        debug_print(f"⏱️  Attempt {attempt + 1}/{max_retries} - Rate limit with token {current_token[:20]}...")
                        retry_after = response.headers.get("Retry-After")
                        sleep_seconds = get_rate_limit_sleep_seconds(retry_after, attempt)
                        debug_print(f"  Retry-After header: {retry_after!r}")

                        if attempt < max_retries - 1:
                            try:
                                current_token = get_next_auth_token(exclude_tokens=failed_tokens)
                                headers = get_request_headers_with_token(current_token, recaptcha_token)
                                debug_print(f"🔄 Retrying with next token: {current_token[:20]}...")
                                await asyncio.sleep(sleep_seconds)
                                continue
                            except HTTPException as e:
                                debug_print(f"❌ No more tokens available: {e.detail}")
                                break

                    elif response.status_code == HTTPStatus.FORBIDDEN:
                        try:
                            error_body = response.json()
                        except Exception:
                            error_body = None
                        if isinstance(error_body, dict) and error_body.get("error") == "recaptcha validation failed":
                            debug_print(
                                f"🤖 Attempt {attempt + 1}/{max_retries} - reCAPTCHA validation failed. Refreshing token..."
                            )
                            new_token = await refresh_recaptcha_token(force_new=True)
                            if new_token and isinstance(payload, dict):
                                payload["recaptchaV3Token"] = new_token
                                recaptcha_token = new_token
                            if attempt < max_retries - 1:
                                headers = get_request_headers_with_token(current_token, recaptcha_token)
                                await asyncio.sleep(1)
                                continue

                    elif response.status_code == HTTPStatus.UNAUTHORIZED:
                        debug_print(f"🔒 Attempt {attempt + 1}/{max_retries} - Auth failed with token {current_token[:20]}...")
                        failed_tokens.add(current_token)
                        debug_print(f"📝 Failed tokens so far: {len(failed_tokens)}")
                        # Log the upstream 401 body so we can see WHY arena.ai rejected the token.
                        # arena.ai often returns a JSON reason (expired JWT / invalid session / missing cookie),
                        # which is otherwise invisible and makes a fresh-looking token fail opaquely.
                        try:
                            _body_401 = str(response.text or "")[:1000]
                            debug_print(f"📥 401 response body: {_body_401}")
                            try:
                                _h_401 = {
                                    str(k): v for k, v in response.headers.items()
                                    if str(k).lower() in ("www-authenticate", "x-powered-by", "server", "date", "content-type")
                                }
                                if _h_401:
                                    debug_print(f"📥 401 response headers (filtered): {_h_401}")
                            except Exception:
                                pass
                        except Exception:
                            pass

                        if attempt < max_retries - 1:
                            try:
                                current_token = get_next_auth_token(exclude_tokens=failed_tokens)
                                headers = get_request_headers_with_token(current_token, recaptcha_token)
                                debug_print(f"🔄 Retrying with next token: {current_token[:20]}...")
                                await asyncio.sleep(1)
                                continue
                            except HTTPException as e:
                                debug_print(f"❌ No more tokens available: {e.detail}")
                                break

                    response.raise_for_status()

                    # arena.ai answers chat completions with an SSE body
                    # (Content-Type: text/event-stream, lines like a0:"text").
                    # Calling response.json() on that always raises
                    # "Expecting value: line 1 column 1 (char 0)", which used to be
                    # logged as a scary warning even though the caller parses the
                    # SSE body correctly a few lines below. Detect SSE up front and
                    # hand the raw response back without the pointless attempt.
                    _ctype = str(response.headers.get("Content-Type") or "").lower()
                    _head = str(getattr(response, "text", "") or "")[:64].lstrip()
                    _is_sse = ("text/event-stream" in _ctype
                               or _head.startswith(("a0:", "ag:", "ad:", "data:")))
                    if _is_sse:
                        debug_print("🌊 SSE response detected — parsing stream body downstream")
                        return response

                    # Transform Arena response to OpenAI format
                    try:
                        arena_data = response.json()
                        openai_response = _transform_arena_response_to_openai(arena_data, model_public_name)
                        debug_print(f"✅ Transformed Arena response to OpenAI format")
                        return JSONResponse(content=openai_response)
                    except Exception as e:
                        debug_print(f"⚠️ Failed to transform response: {e}, returning raw response")
                        return response

                except (requests.exceptions.HTTPError, _cs.exceptions.CloudflareException) as e:
                    status_code = getattr(getattr(e, 'response', None), 'status_code', None)
                    if status_code and status_code not in [429, 401]:
                        raise
                    if attempt == max_retries - 1:
                        raise

            raise HTTPException(status_code=503, detail="Max retries exceeded")

        if stream:
            async def generate_stream():
                nonlocal current_token, headers, failed_tokens, recaptcha_token
                nonlocal session_id, user_msg_id, model_msg_id, model_b_msg_id
                
                # Safety: don't keep client sockets open forever on repeated upstream failures.
                try:
                    stream_total_timeout_seconds = float(get_config().get("stream_total_timeout_seconds", 600))
                except Exception:
                    stream_total_timeout_seconds = 600.0
                stream_total_timeout_seconds = max(30.0, min(stream_total_timeout_seconds, 3600.0))
                stream_started_at = time.monotonic()

                # Flush an immediate comment to keep the client connection alive while we do heavy lifting upstream
                yield ": keep-alive\n\n"
                await asyncio.sleep(0)
                
                async def wait_for_task(task):
                    while True:
                        done, _ = await asyncio.wait({task}, timeout=1.0)
                        if task in done:
                            break
                        yield ": keep-alive\n\n"

                chunk_id = f"chatcmpl-{uuid.uuid4()}"

                # Shared fallback: if no first chunk arrives within the deadline, retry the
                # request as NON-STREAM and return SSE lines for the full OpenAI-compatible
                # response. Returns [] if the fallback itself fails (caller yields a timeout error).
                async def _stream_fallback() -> list:
                    try:
                        # NOTE: do NOT add a "stream" key to the payload — upstream create-evaluation
                        # rejects unknown fields with 400 Bad Request. The stream/non-stream distinction
                        # is purely how WE read the response (cloudscraper buffered vs httpx streaming);
                        # the upstream always returns the same SSE-formatted body.
                        _fb_payload = dict(payload or {})
                        # Generate FRESH IDs — the original payload's IDs were already consumed by
                        # the stream's create-evaluation; reusing them causes 400 "already exists".
                        _fb_session_id = str(uuid7())
                        _fb_payload["id"] = _fb_session_id
                        _fb_payload["userMessageId"] = str(uuid7())
                        _fb_payload["modelAMessageId"] = str(uuid7())
                        _fb_payload["modelBMessageId"] = str(uuid7())
                        # If the original URL was a post-to-evaluation for a session that never
                        # completed (404 "session not found"), fall back to a fresh create-evaluation
                        # with the new session id. This avoids posting to a dead conversation.
                        _fb_url = url
                        _fb_http_method = http_method
                        if "/post-to-evaluation/" in str(_fb_url or ""):
                            _fb_url = f"https://arena.ai{STREAM_CREATE_EVALUATION_PATH}"
                            _fb_http_method = "POST"
                            # create-evaluation REQUIRES a mode; follow-up payloads omit it.
                            _fb_payload["mode"] = "direct-battle"
                            debug_print("🔄 Stream fallback: switching post-to-evaluation -> fresh create-evaluation")
                        # Mint a FRESH reCAPTCHA v3 token for the fallback request. The stream path
                        # defers token minting (recaptcha_token is "" at this point), but upstream
                        # rejects requests without a valid token with 429 "prompt failed". Non-stream
                        # mints before every request — mirror that here (force_new=False reuses the
                        # cached token; force_new=True would launch a headful browser and take minutes).
                        if isinstance(_fb_payload, dict) and not str(_fb_payload.get("recaptchaV3Token") or "").strip():
                            try:
                                _fb_token = await refresh_recaptcha_token(force_new=False)
                            except Exception:
                                _fb_token = None
                            if _fb_token:
                                _fb_payload["recaptchaV3Token"] = _fb_token
                                # Also update the nonlocal headers so make_request_with_retry
                                # sends the token in the Authorization / cookie headers too.
                                nonlocal current_token, headers, recaptcha_token
                                recaptcha_token = _fb_token
                                headers = get_request_headers_with_token(current_token, _fb_token)
                                debug_print(f"🔑 Stream fallback: minted fresh reCAPTCHA token (len={len(str(_fb_token))}), updated headers")
                        _fb_resp = await make_request_with_retry(_fb_url, _fb_payload, _fb_http_method)
                        _fb_code = getattr(_fb_resp, "status_code", None)
                        if _fb_resp is not None and _fb_code and 200 <= _fb_code < 300:
                            try:
                                _fb_arena = _fb_resp.json()
                            except Exception as _fb_json_e:
                                # Upstream may return SSE lines (ag:/a0:/ad:) instead of JSON.
                                # Parse the raw text body the same way the non-stream path does.
                                debug_print(f"⚠️ Stream fallback body not JSON ({_fb_json_e}); parsing SSE text")
                                _fb_text = str(getattr(_fb_resp, "text", "") or "")
                                _fb_arena = _parse_arena_sse_text_to_dict(_fb_text)
                                if not _fb_arena:
                                    debug_print(f"⚠️ Could not parse fallback SSE body: {_fb_text[:200]}")
                                    return []
                            _fb_openai = _transform_arena_response_to_openai(_fb_arena, model_public_name)
                            _fb_msg = (_fb_openai.get("choices") or [{}])[0].get("message") or {}
                            _fb_c = _fb_msg.get("content") or ""
                            _fb_r = _fb_msg.get("reasoning_content") or ""
                            _fb_u = _fb_openai.get("usage")
                            _lines = []
                            if _fb_r:
                                _lines.append(f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model_public_name, 'choices': [{'index': 0, 'delta': {'reasoning_content': _fb_r}, 'finish_reason': None}]})}\n\n")
                            if _fb_c:
                                _lines.append(f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model_public_name, 'choices': [{'index': 0, 'delta': {'content': _fb_c}, 'finish_reason': None}]})}\n\n")
                            if _fb_u:
                                _lines.append(f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': int(time.time()), 'model': model_public_name, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}], 'usage': _fb_u})}\n\n")
                            _lines.append("data: [DONE]\n\n")
                            return _lines
                        debug_print(f"Stream fallback non-stream failed (status={_fb_code}).")
                    except Exception as _fb_e:
                        debug_print(f"Stream fallback error: {_fb_e}")
                    return []
                
                # Send regular keep-alive comments while waiting for upstream. In tests
                # and ASGI clients, do not let keep-alives starve a ready upstream result.
                async def wait_with_keepalive(seconds: float):
                    end_time = time.time() + float(seconds)
                    while time.time() < end_time:
                        yield ": keep-alive\n\n"
                        await asyncio.sleep(min(1.0, end_time - time.time()))

                # Use browser transports (Userscript proxy / Chrome/Camoufox) proactively for:
                #   - models known to be strict with reCAPTCHA
                #   - any streaming request when no auth token is available (browser session may be able to sign up / reuse cookies)
                disable_userscript_proxy_env = bool(os.environ.get("LM_BRIDGE_DISABLE_USERSCRIPT_PROXY"))
                proxy_active_at_start = False
                if not disable_userscript_proxy_env:
                    try:
                        proxy_active_at_start = _userscript_proxy_is_active()
                    except Exception:
                        proxy_active_at_start = False

                # If the userscript proxy is active (internal Camoufox worker / extension poller), route streaming
                # through it immediately to avoid side-channel reCAPTCHA token minting (which can launch headful Chrome).
                #
                # NEW (fix stream chunking): the userscript proxy / browser transports drive arena.ai's chat UI,
                # which creates a BATTLE-mode evaluation (modelAId + modelAMessageId). Upstream then waits for a
                # second model and never emits data chunks → 0 chunks, only keep-alives. When we hold a valid
                # auth token, prefer direct HTTP streaming (same path as non-stream, which works reliably) and
                # only fall back to browser transports if direct HTTP fails. Opt out via config
                # `stream_prefer_direct_http: false` if browser-transport streaming is ever needed.
                try:
                    prefer_direct_http = bool(get_config().get("stream_prefer_direct_http", True))
                except Exception:
                    prefer_direct_http = True
                has_usable_token = bool(str(current_token or "").strip()) and is_probably_valid_arena_auth_token(
                    str(current_token or "").strip()
                )
                use_browser_transports = (
                    force_browser_transports_in_stream
                    or (model_public_name in STRICT_BROWSER_FETCH_MODELS)
                    or (proxy_active_at_start and not (prefer_direct_http and has_usable_token))
                )
                if use_browser_transports and force_browser_transports_in_stream and has_usable_token and prefer_direct_http:
                    # A token exists but the non-strict fallback decided browser transports; keep them for
                    # strict models only. (force_browser_transports_in_stream is set when NO token exists.)
                    pass
                if not use_browser_transports and has_usable_token and prefer_direct_http:
                    debug_print("🔀 Direct HTTP streaming (valid token present, bypassing browser transports for reliable SSE chunks).")
                    # Cloudscraper-only path: the upstream is behind Cloudflare and httpx can't bypass it.
                    # Non-stream works via cloudscraper in make_request_with_retry (synchronous thread).
                    # For streaming, immediately do a non-stream fetch via make_request_with_retry and
                    # emit the full response as a single chunk. This is the "optimal" fallback — instead
                    # of waiting 60s for the first-chunk deadline, we get the complete response in ~30s
                    # and deliver it as one SSE chunk, then [DONE]. Real streaming (multiple chunks from
                    # upstream SSE) would require an async Cloudflare bypass, which we don't have yet.
                    debug_print("⚡ Streaming via cloudscraper non-stream fallback (single-chunk delivery).")
                    _fb_lines = await _stream_fallback()
                    if _fb_lines:
                        for _fb_line in _fb_lines:
                            yield _fb_line
                        return
                    debug_print("⚠️ Cloudscraper fallback failed; falling through to browser transports.")
                    use_browser_transports = True
                prefer_chrome_transport = False
                if use_browser_transports and (model_public_name in STRICT_BROWSER_FETCH_MODELS):
                    debug_print(f"🔐 Strict model detected ({model_public_name}), enabling browser fetch transport.")
                elif use_browser_transports and force_browser_transports_in_stream:
                    debug_print("⚠️ Stream mode without auth token: preferring userscript proxy / browser fetch transports.")
                elif use_browser_transports and proxy_active_at_start:
                    debug_print("🦊 Userscript proxy is ACTIVE: routing stream through proxy and skipping side-channel reCAPTCHA mint.")

                # Non-strict models: mint a fresh side-channel token before the first upstream attempt so we don't
                # send an empty `recaptchaV3Token` (which commonly yields 403 "recaptcha validation failed").
                if (not use_browser_transports) and (not str(recaptcha_token or "").strip()):
                    try:
                        refresh_task = asyncio.create_task(refresh_recaptcha_token(force_new=True))
                        async for ka in wait_for_task(refresh_task):
                            yield ka
                        new_token = refresh_task.result()
                    except Exception:
                        new_token = None
                    if new_token:
                        recaptcha_token = new_token
                        if isinstance(payload, dict):
                            payload["recaptchaV3Token"] = new_token
                        headers = get_request_headers_with_token(current_token, recaptcha_token)
                
                first_chunk_received = False
                recaptcha_403_failures = 0
                no_delta_failures = 0
                attempt = 0
                recaptcha_403_consecutive = 0
                recaptcha_403_last_transport: Optional[str] = None
                strict_token_prefill_attempted = False
                disable_userscript_for_request = False
                force_proxy_recaptcha_mint = False

                retry_429_count = 0
                retry_403_count = 0

                max_retries = 3
                current_retry_attempt = 0
                
                # Infinite retry loop (until client disconnects, max attempts reached, or we get success)
                while True:
                    attempt += 1

                    # Abort if the client disconnects.
                    try:
                        if await request.is_disconnected():
                            return
                    except Exception:
                        pass

                    # First-chunk deadline: if no data chunk received within 60s, try non-stream fallback.
                    if not first_chunk_received and (time.monotonic() - stream_started_at) > 60:
                        _fb_lines = await _stream_fallback()
                        if _fb_lines:
                            for _fb_line in _fb_lines:
                                yield _fb_line
                            return
                        error_chunk = {
                            "error": {
                                "message": "Upstream timed out: no data chunk received within 60s",
                                "type": "upstream_timeout",
                                "code": HTTPStatus.GATEWAY_TIMEOUT,
                            }
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    
                    # Stop retrying after a configurable deadline or too many attempts to avoid infinite hangs.
                    if (time.monotonic() - stream_started_at) > stream_total_timeout_seconds or attempt > 20:
                        error_chunk = {
                            "error": {
                                "message": "Upstream retry timeout or max attempts exceeded while streaming from LMArena.",
                                "type": "upstream_timeout",
                                "code": HTTPStatus.GATEWAY_TIMEOUT,
                            }
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                        return
                    # Reset response data for each attempt
                    response_text = ""
                    reasoning_text = ""
                    citations = []
                    unhandled_preview: list[str] = []

                    try:
                        async with AsyncExitStack() as stack:
                            debug_print(f"📡 Sending {http_method} request for streaming (attempt {attempt})...")
                            stream_context = None
                            transport_used = "httpx"
                            
                            # Userscript proxy is now a backup-only transport.  We check
                            # availability here but defer actually using it until after
                            # browser transports have been attempted.
                            use_userscript = False
                            cfg_now = None
                            userscript_proxy_available = False
                            if (
                                use_browser_transports
                                and not disable_userscript_for_request
                                and not disable_userscript_proxy_env
                            ):
                                try:
                                    cfg_now = get_config()
                                except Exception:
                                    cfg_now = None

                                try:
                                    proxy_active = _userscript_proxy_is_active(cfg_now)
                                except Exception:
                                    proxy_active = False

                                if not proxy_active:
                                    try:
                                        grace_seconds = float((cfg_now or {}).get("userscript_proxy_grace_seconds", 0.5))
                                    except Exception:
                                        grace_seconds = 0.5
                                    grace_seconds = max(0.0, min(grace_seconds, 2.0))
                                    if grace_seconds > 0:
                                        deadline = time.time() + grace_seconds
                                        while time.time() < deadline:
                                            try:
                                                if _userscript_proxy_is_active(cfg_now):
                                                    proxy_active = True
                                                    break
                                            except Exception:
                                                pass
                                            yield ": keep-alive\n\n"
                                            await asyncio.sleep(0.05)

                                if proxy_active:
                                    userscript_proxy_available = True
                                    debug_print("🌐 Userscript Proxy is ACTIVE (will use as backup after browser transports).")
                                # Default behavior: mint in-page (higher success rate than side-channel cached tokens).
                                # Optional: allow pre-filling a cached token for speed via config flag.
                                try:
                                    prefill_cached = bool((cfg_now or {}).get("userscript_proxy_prefill_cached_recaptcha", False))
                                except Exception:
                                    prefill_cached = False
                                if (
                                    prefill_cached
                                    and isinstance(payload, dict)
                                    and not force_proxy_recaptcha_mint
                                    and not str(payload.get("recaptchaV3Token") or "").strip()
                                ):
                                    try:
                                        cached = get_cached_recaptcha_token()
                                    except Exception:
                                        cached = ""
                                    if cached:
                                        debug_print(f"🔐 Using cached reCAPTCHA v3 token for proxy (len={len(str(cached))})")
                                        payload["recaptchaV3Token"] = cached

                            # Strict models: when we're about to fall back to buffered browser fetch transports (not the
                            # streaming proxy), a side-channel token can avoid hangs while grecaptcha loads in-page.
                            if (
                                stream_context is None
                                and use_browser_transports
                                and not use_userscript
                                and isinstance(payload, dict)
                                and not strict_token_prefill_attempted
                                and not str(payload.get("recaptchaV3Token") or "").strip()
                            ):
                                strict_token_prefill_attempted = True
                                try:
                                    refresh_task = asyncio.create_task(refresh_recaptcha_token(force_new=True))
                                except Exception:
                                    refresh_task = None
                                if refresh_task is not None:
                                    while True:
                                        done, _ = await asyncio.wait({refresh_task}, timeout=1.0)
                                        if not first_chunk_received and (time.monotonic() - stream_started_at) > 60:
                                            debug_print("⚠️ First-chunk deadline hit while refreshing token. Trying non-stream fallback.")
                                            _fb_lines = await _stream_fallback()
                                            if _fb_lines:
                                                for _fb_line in _fb_lines:
                                                    yield _fb_line
                                                return
                                            err = {
                                                "error": {
                                                    "message": "Upstream timed out: no data chunk received within 60s",
                                                    "type": "upstream_timeout",
                                                    "code": 504,
                                                }
                                            }
                                            yield f"data: {json.dumps(err)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return
                                        if refresh_task in done:
                                            break
                                        yield ": keep-alive\n\n"
                                    try:
                                        new_token = refresh_task.result()
                                    except Exception:
                                        new_token = None
                                    if new_token:
                                        payload["recaptchaV3Token"] = new_token

                            if stream_context is None and use_browser_transports:
                                browser_fetch_attempts = 5
                                try:
                                    browser_fetch_attempts = int(get_config().get("chrome_fetch_recaptcha_max_attempts", 5))
                                except Exception:
                                    browser_fetch_attempts = 5

                                # If we have a cached side-channel reCAPTCHA token, prefer passing it into the browser
                                # fetch transports (they will reuse it on the first attempt and only mint in-page if
                                # needed). This helps when in-page grecaptcha is slow/flaky.
                                if isinstance(payload, dict) and not str(payload.get("recaptchaV3Token") or "").strip():
                                    try:
                                        cached_token = get_cached_recaptcha_token()
                                    except Exception:
                                        cached_token = ""
                                    if cached_token:
                                        payload["recaptchaV3Token"] = cached_token

                                async def _try_chrome_fetch() -> Optional[BrowserFetchStreamResponse]:
                                    debug_print("🌐 Using Chrome fetch transport for streaming...")
                                    try:
                                        auth_for_browser = str(current_token or "").strip()
                                        try:
                                            cand = str(EPHEMERAL_ARENA_AUTH_TOKEN or "").strip()
                                        except Exception:
                                            cand = ""
                                        if cand:
                                            try:
                                                if (
                                                    is_probably_valid_arena_auth_token(cand)
                                                    and not is_arena_auth_token_expired(cand, skew_seconds=0)
                                                    and (
                                                        (not auth_for_browser)
                                                        or (not is_probably_valid_arena_auth_token(auth_for_browser))
                                                        or is_arena_auth_token_expired(auth_for_browser, skew_seconds=0)
                                                    )
                                                ):
                                                    auth_for_browser = cand
                                            except Exception:
                                                auth_for_browser = cand

                                        try:
                                            chrome_outer_timeout = float(get_config().get("chrome_fetch_outer_timeout_seconds", 120))
                                        except Exception:
                                            chrome_outer_timeout = 120.0
                                        chrome_outer_timeout = max(20.0, min(chrome_outer_timeout, 300.0))

                                        return await asyncio.wait_for(
                                            fetch_lmarena_stream_via_chrome(
                                                http_method=http_method,
                                                url=url,
                                                payload=payload if isinstance(payload, dict) else {},
                                                auth_token=auth_for_browser,
                                                timeout_seconds=120,
                                                max_recaptcha_attempts=browser_fetch_attempts,
                                            ),
                                            timeout=chrome_outer_timeout,
                                        )
                                    except asyncio.TimeoutError:
                                        debug_print("⚠️ Chrome fetch transport timed out (launch/nav hang).")
                                        return None
                                    except Exception as e:
                                        debug_print(f"⚠️ Chrome fetch transport error: {e}")
                                        return None

                                async def _try_camoufox_fetch() -> Optional[BrowserFetchStreamResponse]:
                                    debug_print("🦊 Using Camoufox fetch transport for streaming...")
                                    try:
                                        auth_for_browser = str(current_token or "").strip()
                                        try:
                                            cand = str(EPHEMERAL_ARENA_AUTH_TOKEN or "").strip()
                                        except Exception:
                                            cand = ""
                                        if cand:
                                            try:
                                                if (
                                                    is_probably_valid_arena_auth_token(cand)
                                                    and not is_arena_auth_token_expired(cand, skew_seconds=0)
                                                    and (
                                                        (not auth_for_browser)
                                                        or (not is_probably_valid_arena_auth_token(auth_for_browser))
                                                        or is_arena_auth_token_expired(auth_for_browser, skew_seconds=0)
                                                    )
                                                ):
                                                    auth_for_browser = cand
                                            except Exception:
                                                auth_for_browser = cand

                                        try:
                                            camoufox_outer_timeout = float(
                                                get_config().get("camoufox_fetch_outer_timeout_seconds", 180)
                                            )
                                        except Exception:
                                            camoufox_outer_timeout = 180.0
                                        camoufox_outer_timeout = max(20.0, min(camoufox_outer_timeout, 300.0))

                                        return await asyncio.wait_for(
                                            fetch_lmarena_stream_via_camoufox(
                                                http_method=http_method,
                                                url=url,
                                                payload=payload if isinstance(payload, dict) else {},
                                                auth_token=auth_for_browser,
                                                timeout_seconds=120,
                                                max_recaptcha_attempts=browser_fetch_attempts,
                                            ),
                                            timeout=camoufox_outer_timeout,
                                        )
                                    except asyncio.TimeoutError:
                                        debug_print("⚠️ Camoufox fetch transport timed out (launch/nav hang).")
                                        return None
                                    except Exception as e:
                                        debug_print(f"⚠️ Camoufox fetch transport error: {e}")
                                        return None

                                if prefer_chrome_transport:
                                    chrome_task = asyncio.create_task(_try_chrome_fetch())
                                    while True:
                                        done, _ = await asyncio.wait({chrome_task}, timeout=1.0)
                                        if not first_chunk_received and (time.monotonic() - stream_started_at) > 60:
                                            debug_print("\u26a0\ufe0f First-chunk deadline hit while waiting for browser transport. Trying non-stream fallback.")
                                            _fb_lines = await _stream_fallback()
                                            if _fb_lines:
                                                for _fb_line in _fb_lines:
                                                    yield _fb_line
                                                return
                                            err = {
                                                "error": {
                                                    "message": "Upstream timed out: no data chunk received within 60s",
                                                    "type": "upstream_timeout",
                                                    "code": 504,
                                                }
                                            }
                                            yield f"data: {json.dumps(err)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return
                                        if chrome_task in done:
                                            try:
                                                stream_context = chrome_task.result()
                                            except Exception:
                                                stream_context = None
                                            break
                                        yield ": keep-alive\n\n"
                                    if stream_context is not None:
                                        transport_used = "chrome"
                                    if stream_context is None:
                                        camoufox_task = asyncio.create_task(_try_camoufox_fetch())
                                        while True:
                                            done, _ = await asyncio.wait({camoufox_task}, timeout=1.0)
                                        if not first_chunk_received and (time.monotonic() - stream_started_at) > 60:
                                            debug_print("\u26a0\ufe0f First-chunk deadline hit while waiting for browser transport. Trying non-stream fallback.")
                                            _fb_lines = await _stream_fallback()
                                            if _fb_lines:
                                                for _fb_line in _fb_lines:
                                                    yield _fb_line
                                                return
                                            err = {
                                                "error": {
                                                    "message": "Upstream timed out: no data chunk received within 60s",
                                                    "type": "upstream_timeout",
                                                    "code": 504,
                                                }
                                            }
                                            yield f"data: {json.dumps(err)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return
                                            if camoufox_task in done:
                                                try:
                                                    stream_context = camoufox_task.result()
                                                except Exception:
                                                    stream_context = None
                                                break
                                            yield ": keep-alive\n\n"
                                        if stream_context is not None:
                                            transport_used = "camoufox"
                                else:
                                    camoufox_task = asyncio.create_task(_try_camoufox_fetch())
                                    while True:
                                        done, _ = await asyncio.wait({camoufox_task}, timeout=1.0)
                                        if not first_chunk_received and (time.monotonic() - stream_started_at) > 60:
                                            debug_print("\u26a0\ufe0f First-chunk deadline hit while waiting for browser transport. Trying non-stream fallback.")
                                            _fb_lines = await _stream_fallback()
                                            if _fb_lines:
                                                for _fb_line in _fb_lines:
                                                    yield _fb_line
                                                return
                                            err = {
                                                "error": {
                                                    "message": "Upstream timed out: no data chunk received within 60s",
                                                    "type": "upstream_timeout",
                                                    "code": 504,
                                                }
                                            }
                                            yield f"data: {json.dumps(err)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return
                                        if camoufox_task in done:
                                            try:
                                                stream_context = camoufox_task.result()
                                            except Exception:
                                                stream_context = None
                                            break
                                        yield ": keep-alive\n\n"
                                    if stream_context is not None:
                                        transport_used = "camoufox"
                                    if stream_context is None:
                                        chrome_task = asyncio.create_task(_try_chrome_fetch())
                                        while True:
                                            done, _ = await asyncio.wait({chrome_task}, timeout=1.0)
                                        if not first_chunk_received and (time.monotonic() - stream_started_at) > 60:
                                            debug_print("\u26a0\ufe0f First-chunk deadline hit while waiting for browser transport. Trying non-stream fallback.")
                                            _fb_lines = await _stream_fallback()
                                            if _fb_lines:
                                                for _fb_line in _fb_lines:
                                                    yield _fb_line
                                                return
                                            err = {
                                                "error": {
                                                    "message": "Upstream timed out: no data chunk received within 60s",
                                                    "type": "upstream_timeout",
                                                    "code": 504,
                                                }
                                            }
                                            yield f"data: {json.dumps(err)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return
                                            if chrome_task in done:
                                                try:
                                                    stream_context = chrome_task.result()
                                                except Exception:
                                                    stream_context = None
                                                break
                                            yield ": keep-alive\n\n"
                                        if stream_context is not None:
                                            transport_used = "chrome"

                            # Userscript proxy: backup transport after browser transports fail.
                            if stream_context is None and userscript_proxy_available and not disable_userscript_for_request:
                                use_userscript = True
                                debug_print(
                                    f"📫 Delegating request to Userscript Proxy (poll active {int(time.time() - last_userscript_poll)}s ago)..."
                                )
                                proxy_auth_token = str(current_token or "").strip()
                                try:
                                    if (
                                        proxy_auth_token
                                        and not str(proxy_auth_token).startswith("base64-")
                                        and is_arena_auth_token_expired(proxy_auth_token, skew_seconds=0)
                                    ):
                                        proxy_auth_token = ""
                                except Exception:
                                    pass
                                stream_context = await fetch_via_proxy_queue(
                                    url=url,
                                    payload=payload if isinstance(payload, dict) else {},
                                    http_method=http_method,
                                    timeout_seconds=120,
                                    streaming=True,
                                    auth_token=proxy_auth_token,
                                )
                                if stream_context is None:
                                    debug_print("⚠️ Userscript Proxy returned None (timeout?). Falling back to cloudscraper...")
                                    use_userscript = False
                                else:
                                    transport_used = "userscript"

                            if stream_context is None:
                                # Last-resort: httpx streaming fallback.
                                client = await stack.enter_async_context(httpx.AsyncClient())
                                if http_method == "PUT":
                                    stream_context = client.stream('PUT', url, json=payload, headers=headers, timeout=120)
                                else:
                                    stream_context = client.stream('POST', url, json=payload, headers=headers, timeout=120)
                                transport_used = "httpx"

                            # Userscript proxy jobs report their upstream HTTP status asynchronously.
                            # Wait for the status (or completion) before branching on status_code, while still
                            # keeping the client connection alive.
                            if transport_used == "userscript":
                                proxy_job_id = ""
                                try:
                                    proxy_job_id = str(getattr(stream_context, "job_id", "") or "").strip()
                                except Exception:
                                    proxy_job_id = ""

                                proxy_job = _USERSCRIPT_PROXY_JOBS.get(proxy_job_id) if proxy_job_id else None
                                status_event = None
                                done_event = None
                                picked_up_event = None
                                lines_queue = None
                                if isinstance(proxy_job, dict):
                                    status_event = proxy_job.get("status_event")
                                    done_event = proxy_job.get("done_event")
                                    picked_up_event = proxy_job.get("picked_up_event")
                                    lines_queue = proxy_job.get("lines_queue")
 
                                if isinstance(status_event, asyncio.Event) and not status_event.is_set():
                                    try:
                                        pickup_timeout_seconds = float(
                                            get_config().get("userscript_proxy_pickup_timeout_seconds", 10)
                                        )
                                    except Exception:
                                        pickup_timeout_seconds = 10.0
                                    pickup_timeout_seconds = max(0.5, min(pickup_timeout_seconds, 15.0))

                                    try:
                                        proxy_status_timeout_seconds = float(
                                            get_config().get("userscript_proxy_status_timeout_seconds", 30)
                                        )
                                    except Exception:
                                        proxy_status_timeout_seconds = 30.0
                                    proxy_status_timeout_seconds = max(5.0, min(proxy_status_timeout_seconds, 300.0))

                                    # Time between pickup and the proxy actually starting the upstream fetch. When the
                                    # Camoufox proxy needs to perform anonymous signup / Turnstile preflight, this can
                                    # legitimately take much longer than the upstream-status timeout.
                                    try:
                                        proxy_preflight_timeout_seconds = float(
                                            get_config().get(
                                                "userscript_proxy_preflight_timeout_seconds",
                                                proxy_status_timeout_seconds,
                                            )
                                        )
                                    except Exception:
                                        proxy_preflight_timeout_seconds = proxy_status_timeout_seconds
                                    proxy_preflight_timeout_seconds = max(
                                        5.0, min(proxy_preflight_timeout_seconds, 600.0)
                                    )

                                    try:
                                        proxy_signup_preflight_timeout_seconds = float(
                                            get_config().get(
                                                "userscript_proxy_signup_preflight_timeout_seconds",
                                                240,
                                            )
                                        )
                                    except Exception:
                                        proxy_signup_preflight_timeout_seconds = 240.0
                                    proxy_signup_preflight_timeout_seconds = max(
                                        proxy_preflight_timeout_seconds,
                                        min(proxy_signup_preflight_timeout_seconds, 900.0),
                                    )
 
                                    started = time.monotonic()
                                    proxy_status_timed_out = False
                                    while True:
                                        if status_event.is_set():
                                            break
                                        if isinstance(done_event, asyncio.Event) and done_event.is_set():
                                            break
                                        # If the proxy is already streaming lines, don't stall waiting for a separate
                                        # status report.
                                        if isinstance(lines_queue, asyncio.Queue) and not lines_queue.empty():
                                            break
                                        # If an error has already been recorded, stop waiting and let downstream handle it.
                                        try:
                                            if isinstance(proxy_job, dict) and proxy_job.get("error"):
                                                break
                                        except Exception:
                                            pass

                                        # Abort quickly if the client disconnected.
                                        try:
                                            if await request.is_disconnected():
                                                try:
                                                    await _finalize_userscript_proxy_job(
                                                        proxy_job_id, error="client disconnected", remove=True
                                                    )
                                                except Exception:
                                                    pass
                                                return
                                        except Exception:
                                            pass

                                        now_mono = time.monotonic()
                                        elapsed = now_mono - started
                                        picked_up = True
                                        if isinstance(picked_up_event, asyncio.Event):
                                            picked_up = bool(picked_up_event.is_set())

                                        if (not picked_up) and elapsed >= pickup_timeout_seconds:
                                            debug_print(
                                                f"⚠️ Userscript proxy did not pick up job within {int(pickup_timeout_seconds)}s."
                                            )
                                            disable_userscript_for_request = True
                                            try:
                                                _mark_userscript_proxy_inactive()
                                            except Exception:
                                                pass
                                            try:
                                                await _finalize_userscript_proxy_job(
                                                    proxy_job_id, error="userscript proxy pickup timeout", remove=True
                                                )
                                            except Exception:
                                                pass
                                            proxy_status_timed_out = True
                                            break

                                        if picked_up and isinstance(proxy_job, dict):
                                            pickup_at = proxy_job.get("picked_up_at_monotonic")
                                            try:
                                                pickup_at_mono = float(pickup_at)
                                            except Exception:
                                                pickup_at_mono = 0.0
                                            if pickup_at_mono <= 0:
                                                pickup_at_mono = float(now_mono)
                                                proxy_job["picked_up_at_monotonic"] = pickup_at_mono

                                            upstream_fetch_started_at = proxy_job.get(
                                                "upstream_fetch_started_at_monotonic"
                                            )
                                            try:
                                                upstream_fetch_started_at_mono = float(
                                                    upstream_fetch_started_at
                                                )
                                            except Exception:
                                                upstream_fetch_started_at_mono = 0.0

                                            if upstream_fetch_started_at_mono > 0:
                                                status_elapsed = now_mono - upstream_fetch_started_at_mono
                                                if status_elapsed < 0:
                                                    status_elapsed = 0.0
                                                if status_elapsed >= proxy_status_timeout_seconds:
                                                    debug_print(
                                                        f"⚠️ Userscript proxy did not report upstream status within {int(proxy_status_timeout_seconds)}s."
                                                    )
                                                    # Treat the proxy as unavailable for the rest of this request and fall back
                                                    # to other transports (Chrome/Camoufox/httpx). Otherwise we'd keep queuing
                                                    # jobs that will never be picked up and stall for a long time.
                                                    disable_userscript_for_request = True
                                                    try:
                                                        _mark_userscript_proxy_inactive()
                                                    except Exception:
                                                        pass
                                                    try:
                                                        await _finalize_userscript_proxy_job(
                                                            proxy_job_id,
                                                            error="userscript proxy status timeout",
                                                            remove=True,
                                                        )
                                                    except Exception:
                                                        pass
                                                    proxy_status_timed_out = True
                                                    break
                                            else:
                                                phase = str(proxy_job.get("phase") or "")
                                                preflight_timeout = proxy_preflight_timeout_seconds
                                                if phase == "signup":
                                                    preflight_timeout = proxy_signup_preflight_timeout_seconds
                                                preflight_started_at_mono = pickup_at_mono
                                                if phase == "fetch":
                                                    upstream_started_at = proxy_job.get(
                                                        "upstream_started_at_monotonic"
                                                    )
                                                    try:
                                                        upstream_started_at_mono = float(
                                                            upstream_started_at
                                                        )
                                                    except Exception:
                                                        upstream_started_at_mono = 0.0
                                                    if upstream_started_at_mono > 0:
                                                        preflight_started_at_mono = (
                                                            upstream_started_at_mono
                                                        )

                                                preflight_elapsed = now_mono - preflight_started_at_mono
                                                if preflight_elapsed < 0:
                                                    preflight_elapsed = 0.0
                                                if preflight_elapsed >= preflight_timeout:
                                                    phase_note = phase or "unknown"
                                                    debug_print(
                                                        f"⚠️ Userscript proxy did not start upstream fetch within {int(preflight_timeout)}s (phase={phase_note})."
                                                    )
                                                    disable_userscript_for_request = True
                                                    try:
                                                        _mark_userscript_proxy_inactive()
                                                    except Exception:
                                                        pass
                                                    try:
                                                        await _finalize_userscript_proxy_job(
                                                            proxy_job_id,
                                                            error="userscript proxy preflight timeout",
                                                            remove=True,
                                                        )
                                                    except Exception:
                                                        pass
                                                    proxy_status_timed_out = True
                                                    break
 
                                        yield ": keep-alive\n\n"
                                        await asyncio.sleep(1.0)

                                    if proxy_status_timed_out:
                                        async for ka in wait_with_keepalive(0.5):
                                            yield ka
                                        continue
                            
                            async with stream_context as response:
                                # Log status with human-readable message
                                log_http_status(response.status_code, "LMArena API Stream")

                                # Redirects break SSE streaming and usually indicate an origin change (arena.ai vs
                                # lmarena.ai) or bot-mitigation. Switch to browser transports (userscript proxy when
                                # active) and retry instead of trying to parse the redirect body as stream data.
                                try:
                                    status_int = int(getattr(response, "status_code", 0) or 0)
                                except Exception:
                                    status_int = 0
                                if 300 <= status_int < 400:
                                    location = ""
                                    try:
                                        location = str(
                                            response.headers.get("location")
                                            or response.headers.get("Location")
                                            or ""
                                        ).strip()
                                    except Exception:
                                        location = ""

                                    if transport_used == "httpx":
                                        debug_print(
                                            f"Upstream returned redirect {status_int} ({location or 'no Location header'}). "
                                            "Enabling browser transports and retrying..."
                                        )
                                        use_browser_transports = True
                                    else:
                                        debug_print(
                                            f"Upstream returned redirect {status_int} ({location or 'no Location header'}). Retrying..."
                                        )

                                    async for ka in wait_with_keepalive(0.5):
                                        yield ka
                                    continue

                                # Fail fast on non-retryable upstream errors (4xx/5xx that have no dedicated
                                # retry handler below). Previously these spun forever sending keep-alives with
                                # zero data chunks to the client.
                                _scode = int(response.status_code or 0)
                                if _scode >= 400 and _scode not in (
                                    HTTPStatus.UNAUTHORIZED,
                                    HTTPStatus.FORBIDDEN,
                                    HTTPStatus.TOO_MANY_REQUESTS,
                                ):
                                    _err_text = ""
                                    try:
                                        _err_bytes = await response.aread()
                                        _err_text = (
                                            _err_bytes.decode("utf-8", errors="replace")[:300]
                                            if isinstance(_err_bytes, (bytes, bytearray))
                                            else str(_err_bytes)[:300]
                                        )
                                    except Exception:
                                        pass
                                    debug_print(f"🚨 Stream upstream HTTP {_scode}: {_err_text}")
                                    error_chunk = {
                                        "error": {
                                            "message": f"Upstream error {_scode}: {_err_text or 'no body'}",
                                            "type": "upstream_error",
                                            "code": _scode,
                                        }
                                    }
                                    yield f"data: {json.dumps(error_chunk)}\n\n"
                                    yield "data: [DONE]\n\n"
                                    return

                                # Check for retry-able errors before processing stream
                                if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                                    retry_429_count += 1
                                    if retry_429_count > 3:
                                        error_chunk = {
                                            "error": {
                                                "message": "Too Many Requests (429) from upstream. Retries exhausted.",
                                                "type": "rate_limit_error",
                                                "code": HTTPStatus.TOO_MANY_REQUESTS,
                                            }
                                        }
                                        yield f"data: {json.dumps(error_chunk)}\n\n"
                                        yield "data: [DONE]\n\n"
                                        return

                                    retry_after = None
                                    try:
                                        retry_after = response.headers.get("Retry-After")
                                    except Exception:
                                        retry_after = None
                                    if not retry_after:
                                        try:
                                            retry_after = response.headers.get("retry-after")
                                        except Exception:
                                            retry_after = None
                                    retry_after_value = 0.0
                                    if isinstance(retry_after, str):
                                        try:
                                            retry_after_value = float(retry_after.strip())
                                        except Exception:
                                            retry_after_value = 0.0
                                    sleep_seconds = get_rate_limit_sleep_seconds(retry_after, attempt)
                                    
                                    debug_print(
                                        f"⏱️  Stream attempt {attempt} - Upstream rate limited. Waiting {sleep_seconds}s..."
                                    )
                                    
                                    # Rotate token on rate limit to avoid spinning on the same blocked account.
                                    old_token = current_token
                                    token_rotated = False
                                    if current_token:
                                        try:
                                            rotation_exclude = set(failed_tokens)
                                            rotation_exclude.add(current_token)
                                            current_token = get_next_auth_token(
                                                exclude_tokens=rotation_exclude, allow_ephemeral_fallback=False
                                            )
                                            headers = get_request_headers_with_token(current_token, recaptcha_token)
                                            token_rotated = True
                                            debug_print(f"🔄 Retrying stream with next token: {current_token[:20]}...")
                                        except HTTPException:
                                            # Only one token (or all tokens excluded). Keep the current token and retry
                                            # after backoff instead of failing fast.
                                            debug_print("⚠️ No alternative token available; retrying with same token after backoff.")

                                    # reCAPTCHA v3 tokens can be single-use and may expire while we back off.
                                    # Clear it so the next browser fetch attempt mints a fresh token.
                                    if isinstance(payload, dict):
                                        payload["recaptchaV3Token"] = ""

                                    # If we rotated tokens, allow a fast retry when the backoff would exceed the remaining
                                    # stream deadline (common when one token is rate-limited but another isn't).
                                    if token_rotated and current_token and current_token != old_token:
                                        remaining_budget = float(stream_total_timeout_seconds) - float(
                                            time.monotonic() - stream_started_at
                                        )
                                        if float(sleep_seconds) > max(0.0, remaining_budget):
                                            sleep_seconds = min(float(sleep_seconds), 1.0)
                                    
                                    async for ka in wait_with_keepalive(sleep_seconds):
                                        yield ka
                                    continue
                                
                                elif response.status_code == HTTPStatus.FORBIDDEN:
                                    # Userscript proxy note:
                                    # The in-page fetch script can report an initial 403 while it mints/retries
                                    # reCAPTCHA (v3 retry + v2 fallback) and may later update the status to 200
                                    # without needing a new proxy job.
                                    if transport_used == "userscript":
                                        proxy_job_id = ""
                                        try:
                                            proxy_job_id = str(getattr(stream_context, "job_id", "") or "").strip()
                                        except Exception:
                                            proxy_job_id = ""

                                        proxy_job = _USERSCRIPT_PROXY_JOBS.get(proxy_job_id) if proxy_job_id else None
                                        proxy_done_event = None
                                        if isinstance(proxy_job, dict):
                                            proxy_done_event = proxy_job.get("done_event")

                                        # Give the proxy a chance to finish its in-page reCAPTCHA retry path before we
                                        # abandon this response and queue a new job (which can lead to pickup timeouts).
                                        try:
                                            grace_seconds = float(
                                                get_config().get("userscript_proxy_recaptcha_grace_seconds", 25)
                                            )
                                        except Exception:
                                            grace_seconds = 25.0
                                        grace_seconds = max(0.0, min(grace_seconds, 90.0))

                                        if (
                                            grace_seconds > 0.0
                                            and isinstance(proxy_done_event, asyncio.Event)
                                            and not proxy_done_event.is_set()
                                        ):
                                            # Important: do not enqueue a new proxy job while the current one is still
                                            # running. The internal Camoufox worker is single-threaded and will not pick
                                            # up new jobs until `page.evaluate()` returns.
                                            remaining_budget = float(stream_total_timeout_seconds) - float(
                                                time.monotonic() - stream_started_at
                                            )
                                            remaining_budget = max(0.0, remaining_budget)
                                            max_wait_seconds = min(max(float(grace_seconds), 200.0), remaining_budget)

                                            debug_print(
                                                f"⏳ Userscript proxy reported 403. Waiting up to {int(max_wait_seconds)}s for in-page retry..."
                                            )
                                            started = time.monotonic()
                                            warned_extended = False
                                            while (time.monotonic() - started) < float(max_wait_seconds):
                                                if response.status_code != HTTPStatus.FORBIDDEN:
                                                    debug_print(
                                                        f"✅ Userscript proxy recovered from 403 (status: {response.status_code})."
                                                    )
                                                    break
                                                if proxy_done_event.is_set():
                                                    break
                                                # If the proxy job already has an error, don't wait the full window.
                                                try:
                                                    if isinstance(proxy_job, dict) and proxy_job.get("error"):
                                                        break
                                                except Exception:
                                                    pass
                                                if (not warned_extended) and (time.monotonic() - started) >= float(
                                                    grace_seconds
                                                ):
                                                    warned_extended = True
                                                    debug_print(
                                                        "⏳ Still 403 after grace window; waiting for proxy job completion..."
                                                    )
                                                yield ": keep-alive\n\n"
                                                await asyncio.sleep(0.5)

                                    # If the userscript proxy recovered (status changed after in-page retries),
                                    # proceed to normal stream parsing below.
                                    if response.status_code != HTTPStatus.FORBIDDEN:
                                        pass
                                    else:
                                        retry_403_count += 1
                                        if retry_403_count > 5:
                                            error_chunk = {
                                                "error": {
                                                    "message": "Forbidden (403) from upstream. Retries exhausted.",
                                                    "type": "forbidden_error",
                                                    "code": HTTPStatus.FORBIDDEN,
                                                }
                                            }
                                            yield f"data: {json.dumps(error_chunk)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return

                                        body_text = ""
                                        error_body = None
                                        try:
                                            body_bytes = await response.aread()
                                            body_text = body_bytes.decode("utf-8", errors="replace")
                                            error_body = json.loads(body_text)
                                        except Exception:
                                            error_body = None
                                            # If it's not JSON, we'll use the body_text for keyword matching.

                                        is_recaptcha_failure = False
                                        try:
                                            if (
                                                isinstance(error_body, dict)
                                                and error_body.get("error") == "recaptcha validation failed"
                                            ):
                                                is_recaptcha_failure = True
                                            elif "recaptcha validation failed" in str(body_text).lower():
                                                is_recaptcha_failure = True
                                        except Exception:
                                            is_recaptcha_failure = False

                                        if transport_used == "userscript":
                                            # The proxy is our only truly streaming browser transport. Prefer retrying
                                            # it with a fresh in-page token mint over switching to buffered browser
                                            # fetch fallbacks (which can stall SSE).
                                            force_proxy_recaptcha_mint = True
                                            if is_recaptcha_failure:
                                                recaptcha_403_failures += 1
                                                if recaptcha_403_failures >= 5:
                                                    debug_print(
                                                        "? Too many reCAPTCHA failures in userscript proxy. Failing fast."
                                                    )
                                                    error_chunk = {
                                                        "error": {
                                                            "message": (
                                                                "Forbidden: reCAPTCHA validation failed repeatedly in userscript proxy."
                                                            ),
                                                            "type": "recaptcha_error",
                                                            "code": HTTPStatus.FORBIDDEN,
                                                        }
                                                    }
                                                    yield f"data: {json.dumps(error_chunk)}\n\n"
                                                    yield "data: [DONE]\n\n"
                                                    return

                                            if isinstance(payload, dict):
                                                payload["recaptchaV3Token"] = ""
                                                payload.pop("recaptchaV2Token", None)

                                            async for ka in wait_with_keepalive(1.5):
                                                yield ka
                                            continue

                                        if is_recaptcha_failure:
                                            # Track consecutive reCAPTCHA failures so we can escalate to browser
                                            # transports even for non-strict models.
                                            recaptcha_403_failures += 1
                                            if recaptcha_403_last_transport == transport_used:
                                                recaptcha_403_consecutive += 1
                                            else:
                                                recaptcha_403_consecutive = 1
                                                recaptcha_403_last_transport = transport_used

                                            if transport_used in ("chrome", "camoufox"):
                                                try:
                                                    debug_print(
                                                        "Refreshing token/cookies (side-channel) after browser fetch 403..."
                                                    )
                                                    refresh_task = asyncio.create_task(
                                                        refresh_recaptcha_token(force_new=True)
                                                    )
                                                    async for ka in wait_for_task(refresh_task):
                                                        yield ka
                                                    new_token = refresh_task.result()
                                                except Exception:
                                                    new_token = None
                                                # Prefer reusing a fresh side-channel token on the next attempt; if we
                                                # couldn't get one, fall back to in-page minting.
                                                if isinstance(payload, dict):
                                                    payload["recaptchaV3Token"] = new_token or ""
                                            else:
                                                debug_print("Refreshing token (side-channel)...")
                                                try:
                                                    refresh_task = asyncio.create_task(
                                                        refresh_recaptcha_token(force_new=True)
                                                    )
                                                    async for ka in wait_for_task(refresh_task):
                                                        yield ka
                                                    new_token = refresh_task.result()
                                                except Exception:
                                                    new_token = None
                                                if new_token and isinstance(payload, dict):
                                                    payload["recaptchaV3Token"] = new_token

                                            if recaptcha_403_consecutive >= 2 and transport_used == "chrome":
                                                debug_print(
                                                    "Switching to Camoufox-first after repeated Chrome reCAPTCHA failures."
                                                )
                                                use_browser_transports = True
                                                prefer_chrome_transport = False
                                                recaptcha_403_consecutive = 0
                                                recaptcha_403_last_transport = None
                                            elif recaptcha_403_consecutive >= 2 and transport_used != "chrome":
                                                debug_print(
                                                    "🌐 Switching to Chrome fetch transport after repeated reCAPTCHA failures."
                                                )
                                                use_browser_transports = True
                                                prefer_chrome_transport = True
                                                recaptcha_403_consecutive = 0
                                                recaptcha_403_last_transport = None

                                            async for ka in wait_with_keepalive(1.5):
                                                yield ka
                                            continue

                                        # If 403 but not recaptcha, might be other auth issue, but let's retry anyway
                                        async for ka in wait_with_keepalive(2.0):
                                            yield ka
                                        continue

                                elif response.status_code == HTTPStatus.UNAUTHORIZED:
                                    debug_print(f"🔒 Stream token expired")
                                    # Add current token to failed set
                                    failed_tokens.add(current_token)
                                    # Log the upstream 401 body so we can see WHY arena.ai rejected the token.
                                    # Read the body without consuming the stream permanently (best-effort, capped).
                                    try:
                                        _peek = await response.aread()
                                        _peek_text = _peek.decode("utf-8", errors="replace") if isinstance(_peek, (bytes, bytearray)) else str(_peek)
                                        debug_print(f"📥 stream 401 response body: {_peek_text[:1000]}")
                                    except Exception:
                                        pass

                                    # Best-effort: refresh the current base64 session in-memory before rotating.
                                    refreshed_token: Optional[str] = None
                                    if current_token:
                                        try:
                                            cfg_now = get_config()
                                        except Exception:
                                            cfg_now = {}
                                        if not isinstance(cfg_now, dict):
                                            cfg_now = {}
                                        try:
                                            refreshed_token = await refresh_arena_auth_token_via_lmarena_http(
                                                current_token, cfg_now
                                            )
                                        except Exception:
                                            refreshed_token = None
                                        if not refreshed_token:
                                            try:
                                                refreshed_token = await refresh_arena_auth_token_via_supabase(current_token)
                                            except Exception:
                                                refreshed_token = None

                                    if refreshed_token:
                                        global EPHEMERAL_ARENA_AUTH_TOKEN
                                        EPHEMERAL_ARENA_AUTH_TOKEN = refreshed_token
                                        current_token = refreshed_token
                                        headers = get_request_headers_with_token(current_token, recaptcha_token)
                                        # Ensure the next browser attempt mints a fresh token for the refreshed session.
                                        if isinstance(payload, dict):
                                            payload["recaptchaV3Token"] = ""
                                        debug_print("🔄 Refreshed arena-auth-prod-v1 session after 401. Retrying...")
                                        async for ka in wait_with_keepalive(1.0):
                                            yield ka
                                        continue
                                    
                                    try:
                                        # Try with next available token (excluding failed ones)
                                        current_token = get_next_auth_token(exclude_tokens=failed_tokens)
                                        headers = get_request_headers_with_token(current_token, recaptcha_token)
                                        debug_print(f"🔄 Retrying stream with next token: {current_token[:20]}...")
                                        async for ka in wait_with_keepalive(1.0):
                                            yield ka
                                        continue
                                    except HTTPException:
                                        debug_print("No more tokens available for streaming request.")
                                        error_chunk = {
                                            "error": {
                                                "message": (
                                                    "Unauthorized: Your LMArena auth token has expired or is invalid. "
                                                    "Please get a new auth token from the dashboard."
                                                ),
                                                "type": "authentication_error",
                                                "code": HTTPStatus.UNAUTHORIZED,
                                            }
                                        }
                                        yield f"data: {json.dumps(error_chunk)}\n\n"
                                        yield "data: [DONE]\n\n"
                                        return
                                
                                log_http_status(response.status_code, "Stream Connection")
                                response.raise_for_status()
                                
                                no_data_keepalive_count = 0
                                # Wrapped iterator to yield keep-alives while waiting for upstream lines.
                                # NOTE: Avoid asyncio.wait_for() here; cancelling __anext__ can break the iterator.
                                async def _aiter_with_keepalive(it):
                                    pending: Optional[asyncio.Task] = asyncio.create_task(it.__anext__())
                                    try:
                                        while True:
                                            done, _ = await asyncio.wait({pending}, timeout=1.0)
                                            if pending not in done:
                                                yield None
                                                continue
                                            try:
                                                item = pending.result()
                                            except StopAsyncIteration:
                                                break
                                            pending = asyncio.create_task(it.__anext__())
                                            yield item
                                    finally:
                                        if pending is not None and not pending.done():
                                            pending.cancel()

                                async for maybe_line in _aiter_with_keepalive(response.aiter_lines().__aiter__()):
                                    if maybe_line is None:
                                        yield ": keep-alive\n\n"
                                        no_data_keepalive_count += 1
                                        if no_data_keepalive_count >= 30 and not response_text.strip() and not reasoning_text.strip():
                                            debug_print("⚠️ No data chunk received after 30s of keep-alive. Failing fast.")
                                            error_chunk = {
                                                "error": {
                                                    "message": "Upstream timed out: no data received after 30s",
                                                    "type": "upstream_timeout",
                                                    "code": 504,
                                                }
                                            }
                                            yield f"data: {json.dumps(error_chunk)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return
                                        continue

                                    line = str(maybe_line).strip()
                                    # Normalize possible SSE framing (e.g. `data: a0:"..."`).
                                    if line.startswith("data:"):
                                        line = line[5:].lstrip()
                                    if not line:
                                        continue

                                    # First-chunk deadline: if upstream sends only keep-alive
                                    # comments without any data chunk for timeout seconds,
                                    # fail fast instead of holding the client socket open.
                                    if not response_text.strip() and not reasoning_text.strip():
                                        elapsed = time.monotonic() - stream_started_at
                                        timeout = 30.0
                                        try:
                                            timeout = float(get_config().get("stream_first_chunk_timeout", 30.0))
                                        except Exception:
                                            pass
                                        if elapsed >= timeout:
                                            debug_print(f"\u26a0\ufe0f No data chunk in {elapsed:.0f}s (timeout={timeout:.0f}s). Failing fast.")
                                            err = {
                                                "error": {
                                                    "message": f"Upstream timed out: no data chunk after {timeout:.0f}s",
                                                    "type": "upstream_timeout",
                                                    "code": 504,
                                                }
                                            }
                                            yield f"data: {json.dumps(err)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return
                                    
                                    # Parse thinking/reasoning chunks: ag:"thinking text"
                                    if line.startswith("ag:"):
                                        chunk_data = line[3:]
                                        try:
                                            reasoning_chunk = json.loads(chunk_data)
                                            reasoning_text += reasoning_chunk
                                            first_chunk_received = True
                                            
                                            # Send SSE-formatted chunk with reasoning_content
                                            chunk_response = {
                                                "id": chunk_id,
                                                "object": "chat.completion.chunk",
                                                "created": int(time.time()),
                                                "model": model_public_name,
                                                "choices": [{
                                                    "index": 0,
                                                    "delta": {
                                                        "reasoning_content": reasoning_chunk
                                                    },
                                                    "finish_reason": None
                                                }]
                                            }
                                            yield f"data: {json.dumps(chunk_response)}\n\n"
                                            
                                        except json.JSONDecodeError:
                                            continue
                                    
                                    # Parse text chunks: a0:"Hello "
                                    elif line.startswith("a0:"):
                                        chunk_data = line[3:]
                                        try:
                                            text_chunk = json.loads(chunk_data)
                                            response_text += text_chunk
                                            first_chunk_received = True
                                            
                                            # Send SSE-formatted chunk
                                            chunk_response = {
                                                "id": chunk_id,
                                                "object": "chat.completion.chunk",
                                                "created": int(time.time()),
                                                "model": model_public_name,
                                                "choices": [{
                                                    "index": 0,
                                                    "delta": {
                                                        "content": text_chunk
                                                    },
                                                    "finish_reason": None
                                                }]
                                            }
                                            yield f"data: {json.dumps(chunk_response)}\n\n"
                                            
                                        except json.JSONDecodeError:
                                            continue
                                    
                                    # Parse image generation: a2:[{...}] (for image models)
                                    elif line.startswith("a2:"):
                                        image_data = line[3:]
                                        try:
                                            image_list = json.loads(image_data)
                                            # OpenAI format: return URL in content
                                            if isinstance(image_list, list) and len(image_list) > 0:
                                                image_obj = image_list[0]
                                                otype = image_obj.get('type')
                                                if otype == 'image':
                                                    image_url = image_obj.get('image', '')
                                                    # Format as markdown for streaming
                                                    response_text = f"![Generated Image]({image_url})"
                                                    first_chunk_received = True
                                                    chunk_response = {
                                                        "id": chunk_id,
                                                        "object": "chat.completion.chunk",
                                                        "created": int(time.time()),
                                                        "model": model_public_name,
                                                        "choices": [{
                                                            "index": 0,
                                                            "delta": {
                                                                "content": response_text
                                                            },
                                                            "finish_reason": None
                                                        }]
                                                    }
                                                    yield f"data: {json.dumps(chunk_response)}\n\n"
                                                elif otype == 'webdev':
                                                    # WebDev: LMArena deploys the site at
                                                    # https://{modelAMessageId}.arena.site
                                                    site_url = f"https://{model_msg_id}.arena.site"
                                                    files = image_obj.get('event', {}).get('files', [])
                                                    n = len(files) if isinstance(files, list) else 0
                                                    response_text = (f"**[Web Dev Deployed]**\n"
                                                                     f"Live site: {site_url}\n"
                                                                     f"Files: {n+1} (index.html + {n} assets)")
                                                    first_chunk_received = True
                                                    chunk_response = {
                                                        "id": chunk_id,
                                                        "object": "chat.completion.chunk",
                                                        "created": int(time.time()),
                                                        "model": model_public_name,
                                                        "choices": [{
                                                            "index": 0,
                                                            "delta": {"content": response_text},
                                                            "finish_reason": None
                                                        }]
                                                    }
                                                    yield f"data: {json.dumps(chunk_response)}\n\n"
                                        except json.JSONDecodeError:
                                            pass
                                    
                                    # Parse citations/tool calls: ac:{...} (for search models)
                                    elif line.startswith("ac:"):
                                        citation_data = line[3:]
                                        try:
                                            citation_obj = json.loads(citation_data)
                                            # Extract source information from argsTextDelta
                                            if 'argsTextDelta' in citation_obj:
                                                args_data = json.loads(citation_obj['argsTextDelta'])
                                                if 'source' in args_data:
                                                    source = args_data['source']
                                                    # Can be a single source or array of sources
                                                    if isinstance(source, list):
                                                        citations.extend(source)
                                                    elif isinstance(source, dict):
                                                        citations.append(source)
                                            debug_print(f"  🔗 Citation added: {citation_obj.get('toolCallId')}")
                                        except json.JSONDecodeError:
                                            pass
                                    
                                    # Parse error messages
                                    elif line.startswith("a3:"):
                                        error_data = line[3:]
                                        try:
                                            error_message = json.loads(error_data)
                                            print(f"  ❌ Error in stream: {error_message}")
                                        except json.JSONDecodeError:
                                            pass
                                    
                                    # Parse metadata for finish
                                    elif line.startswith("ad:"):
                                        metadata_data = line[3:]
                                        try:
                                            metadata = json.loads(metadata_data)
                                            finish_reason = metadata.get("finishReason", "stop")
                                            
                                            # Send final chunk with finish_reason
                                            final_chunk = {
                                                "id": chunk_id,
                                                "object": "chat.completion.chunk",
                                                "created": int(time.time()),
                                                "model": model_public_name,
                                                "choices": [{
                                                    "index": 0,
                                                    "delta": {},
                                                    "finish_reason": finish_reason
                                                }]
                                            }
                                            yield f"data: {json.dumps(final_chunk)}\n\n"
                                        except json.JSONDecodeError:
                                            continue
                                    
                                    # Support for standard OpenAI-style JSON chunks (some proxies or new LMArena endpoints)
                                    elif line.startswith("{"):
                                        try:
                                            chunk_obj = json.loads(line)
                                            # If it looks like an OpenAI chunk, extract the delta content
                                            if "choices" in chunk_obj and isinstance(chunk_obj["choices"], list) and len(chunk_obj["choices"]) > 0:
                                                delta = chunk_obj["choices"][0].get("delta", {})
                                                
                                                # Handle thinking/reasoning
                                                if "reasoning_content" in delta:
                                                    r_chunk = str(delta["reasoning_content"] or "")
                                                    reasoning_text += r_chunk
                                                    chunk_response = {
                                                        "id": chunk_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": model_public_name,
                                                        "choices": [{"index": 0, "delta": {"reasoning_content": r_chunk}, "finish_reason": None}]
                                                    }
                                                    yield f"data: {json.dumps(chunk_response)}\n\n"

                                                # Handle text content
                                                if "content" in delta:
                                                    c_chunk = str(delta["content"] or "")
                                                    response_text += c_chunk
                                                    first_chunk_received = True
                                                    chunk_response = {
                                                        "id": chunk_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": model_public_name,
                                                        "choices": [{"index": 0, "delta": {"content": c_chunk}, "finish_reason": None}]
                                                    }
                                                    yield f"data: {json.dumps(chunk_response)}\n\n"
                                        except Exception:
                                            pass

                                    else:
                                        # Capture a small preview of unhandled upstream lines for troubleshooting.
                                        if len(unhandled_preview) < 5:
                                            unhandled_preview.append(line)
                                        continue
                            
                            # If we got no usable deltas, treat it as an upstream failure and retry.
                            if (not response_text.strip()) and (not reasoning_text.strip()) and (not citations):
                                upstream_hint: Optional[str] = None
                                proxy_status: Optional[int] = None
                                proxy_headers: Optional[dict] = None
                                if transport_used == "userscript":
                                    try:
                                        proxy_job_id = str(getattr(stream_context, "job_id", "") or "").strip()
                                        proxy_job = _USERSCRIPT_PROXY_JOBS.get(proxy_job_id)
                                        if isinstance(proxy_job, dict):
                                            if proxy_job.get("error"):
                                                upstream_hint = str(proxy_job.get("error") or "")
                                            status = proxy_job.get("status_code")
                                            headers = proxy_job.get("headers")
                                            if isinstance(headers, dict):
                                                proxy_headers = headers
                                            if isinstance(status, int) and int(status) >= 400:
                                                proxy_status = int(status)
                                                upstream_hint = upstream_hint or f"Userscript proxy upstream HTTP {int(status)}"
                                    except Exception:
                                        pass

                                if not upstream_hint and unhandled_preview:
                                    # Common case: upstream returns a JSON error body (not a0:/ad: lines).
                                    try:
                                        obj = json.loads(unhandled_preview[0])
                                        if isinstance(obj, dict):
                                            upstream_hint = str(obj.get("error") or obj.get("message") or "")
                                    except Exception:
                                        pass
                                    
                                    if not upstream_hint:
                                        upstream_hint = unhandled_preview[0][:500]

                                debug_print(f"⚠️ Stream produced no content deltas (transport={transport_used}, attempt {attempt}). Retrying...")
                                if upstream_hint:
                                    debug_print(f"   Upstream hint: {upstream_hint[:200]}")
                                    if "recaptcha" in upstream_hint.lower():
                                        recaptcha_403_failures += 1
                                        if recaptcha_403_failures >= 5:
                                            debug_print("❌ Too many reCAPTCHA failures (detected in body). Failing fast.")
                                            error_chunk = {
                                                "error": {
                                                    "message": f"Forbidden: reCAPTCHA validation failed. Upstream hint: {upstream_hint[:200]}",
                                                    "type": "recaptcha_error",
                                                    "code": HTTPStatus.FORBIDDEN,
                                                }
                                            }
                                            yield f"data: {json.dumps(error_chunk)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return
                                elif unhandled_preview:
                                    debug_print(f"   Upstream preview: {unhandled_preview[0][:200]}")
                                
                                no_delta_failures += 1
                                if no_delta_failures >= 10:
                                    debug_print("❌ Too many attempts with no content produced. Failing fast.")
                                    error_chunk = {
                                        "error": {
                                            "message": f"Upstream failure: The request produced no content after multiple retries. Last hint: {upstream_hint[:200] if upstream_hint else 'None'}",
                                            "type": "upstream_error",
                                            "code": HTTPStatus.BAD_GATEWAY,
                                        }
                                    }
                                    yield f"data: {json.dumps(error_chunk)}\n\n"
                                    yield "data: [DONE]\n\n"
                                    return

                                # If the userscript proxy actually returned an upstream HTTP error, don't spin forever
                                # sending keep-alives: treat them as the equivalent upstream status and fall back.
                                if transport_used == "userscript" and proxy_status in (
                                    HTTPStatus.UNAUTHORIZED,
                                    HTTPStatus.FORBIDDEN,
                                ):
                                    # Mirror the regular 401/403 handling, but based on the proxy job status instead
                                    # of `response.status_code` (which can be stale for userscript jobs).
                                    if proxy_status == HTTPStatus.UNAUTHORIZED:
                                        debug_print("🔒 Userscript proxy upstream 401. Rotating auth token...")
                                        failed_tokens.add(current_token)
                                        # (Pruning disabled)

                                        try:
                                            current_token = get_next_auth_token(exclude_tokens=failed_tokens)
                                            headers = get_request_headers_with_token(current_token, recaptcha_token)
                                        except HTTPException:
                                            error_chunk = {
                                                "error": {
                                                    "message": (
                                                        "Unauthorized: Your LMArena auth token has expired or is invalid. "
                                                        "Please get a new auth token from the dashboard."
                                                    ),
                                                    "type": "authentication_error",
                                                    "code": HTTPStatus.UNAUTHORIZED,
                                                }
                                            }
                                            yield f"data: {json.dumps(error_chunk)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return

                                    if proxy_status == HTTPStatus.FORBIDDEN:
                                        recaptcha_403_failures += 1
                                        if recaptcha_403_failures >= 5:
                                            debug_print("❌ Too many reCAPTCHA failures in userscript proxy. Failing fast.")
                                            error_chunk = {
                                                "error": {
                                                    "message": "Forbidden: reCAPTCHA validation failed repeatedly in userscript proxy.",
                                                    "type": "recaptcha_error",
                                                    "code": HTTPStatus.FORBIDDEN,
                                                }
                                            }
                                            yield f"data: {json.dumps(error_chunk)}\n\n"
                                            yield "data: [DONE]\n\n"
                                            return

                                        # Common case: the proxy session gets flagged (reCAPTCHA). Retry with a fresh
                                        # in-page token mint rather than switching to buffered browser fetch fallbacks.
                                        force_proxy_recaptcha_mint = True
                                        debug_print("🚫 Userscript proxy upstream 403: retrying userscript (fresh reCAPTCHA).")
                                        if isinstance(payload, dict):
                                            payload["recaptchaV3Token"] = ""
                                            payload.pop("recaptchaV2Token", None)

                                    yield ": keep-alive\n\n"
                                    continue

                                # If the proxy upstream is rate-limited, respect Retry-After/backoff.
                                if transport_used == "userscript" and proxy_status == HTTPStatus.TOO_MANY_REQUESTS:
                                    retry_after = None
                                    if isinstance(proxy_headers, dict):
                                        retry_after = proxy_headers.get("retry-after") or proxy_headers.get("Retry-After")
                                    retry_after_value = 0.0
                                    if isinstance(retry_after, str):
                                        try:
                                            retry_after_value = float(retry_after.strip())
                                        except Exception:
                                            retry_after_value = 0.0
                                    sleep_seconds = get_rate_limit_sleep_seconds(retry_after, attempt)
                                    debug_print(f"⏱️  Userscript proxy upstream 429. Waiting {sleep_seconds}s...")
                                    
                                    # Rotate token on userscript rate limit too.
                                    old_token = current_token
                                    token_rotated = False
                                    try:
                                        rotation_exclude = set(failed_tokens)
                                        if current_token:
                                            rotation_exclude.add(current_token)
                                        current_token = get_next_auth_token(
                                            exclude_tokens=rotation_exclude, allow_ephemeral_fallback=False
                                        )
                                        headers = get_request_headers_with_token(current_token, recaptcha_token)
                                        token_rotated = True
                                        debug_print(f"🔄 Retrying stream with next token (after proxy 429): {current_token[:20]}...")
                                    except HTTPException:
                                        # Only one token (or all tokens excluded). Keep the current token and retry
                                        # after backoff instead of failing fast.
                                        debug_print(
                                            "⚠️ No alternative token available after userscript proxy rate limit; retrying with same token after backoff."
                                        )

                                    # reCAPTCHA v3 tokens can be single-use and may expire while we back off.
                                    # Clear it so the next proxy attempt mints a fresh token in-page.
                                    if isinstance(payload, dict):
                                        payload["recaptchaV3Token"] = ""

                                    # If we rotated tokens, allow a fast retry when waiting would blow past the remaining
                                    # stream deadline (common when one token is rate-limited but another isn't).
                                    if token_rotated and current_token and current_token != old_token:
                                        remaining_budget = float(stream_total_timeout_seconds) - float(
                                            time.monotonic() - stream_started_at
                                        )
                                        if float(sleep_seconds) > max(0.0, remaining_budget):
                                            sleep_seconds = min(float(sleep_seconds), 1.0)

                                    # If we still can't wait within the remaining deadline, fail now instead of sending
                                    # keep-alives indefinitely.
                                    if (time.monotonic() - stream_started_at + float(sleep_seconds)) > stream_total_timeout_seconds:
                                        error_chunk = {
                                            "error": {
                                                "message": f"Upstream rate limit (429) would exceed stream deadline ({int(sleep_seconds)}s backoff).",
                                                "type": "rate_limit_error",
                                                "code": HTTPStatus.TOO_MANY_REQUESTS,
                                            }
                                        }
                                        yield f"data: {json.dumps(error_chunk)}\n\n"
                                        yield "data: [DONE]\n\n"
                                        return

                                    async for ka in wait_with_keepalive(sleep_seconds):
                                        yield ka
                                else:
                                    # New-session create-evaluation retries must use fresh IDs. Reusing IDs after an
                                    # upstream no-delta/error response can trigger 400 duplicate/invalid request errors.
                                    if (
                                        (not session)
                                        and isinstance(payload, dict)
                                        and http_method.upper() == "POST"
                                        and STREAM_CREATE_EVALUATION_PATH in url
                                    ):
                                        session_id = str(uuid7())
                                        user_msg_id = str(uuid7())
                                        model_msg_id = str(uuid7())
                                        model_b_msg_id = str(uuid7())
                                        payload["id"] = session_id
                                        payload["userMessageId"] = user_msg_id
                                        payload["modelAMessageId"] = model_msg_id
                                        # Keep direct-battle mode consistent on retry: a single-model
                                        # conversation must NOT carry modelBMessageId (arena.ai rejects the
                                        # old "direct"/side-by-side shape with 400 for new conversations).
                                        payload["mode"] = "direct-battle"
                                        payload.pop("modelBMessageId", None)
                                        debug_print("🔁 Retrying create-evaluation with fresh session/message IDs.")
                                    async for ka in wait_with_keepalive(1.5):
                                        yield ka
                                continue

                            # Update session - Store message history with IDs (including reasoning and citations if present)
                            assistant_message = {
                                "id": model_msg_id, 
                                "role": "assistant", 
                                "content": response_text.strip()
                            }
                            if reasoning_text:
                                assistant_message["reasoning_content"] = reasoning_text.strip()
                            if citations:
                                # Deduplicate citations by URL
                                unique_citations = []
                                seen_urls = set()
                                for citation in citations:
                                    citation_url = citation.get('url')
                                    if citation_url and citation_url not in seen_urls:
                                        seen_urls.add(citation_url)
                                        unique_citations.append(citation)
                                assistant_message["citations"] = unique_citations
                            
                            if not session:
                                chat_sessions[api_key_str][conversation_id] = {
                                    "conversation_id": session_id,
                                    "model": model_public_name,
                                    "messages": [
                                        {"id": user_msg_id, "role": "user", "content": prompt},
                                        assistant_message
                                    ]
                                }
                                debug_print(f"💾 Saved new session for conversation {conversation_id}")
                            else:
                                # Append new messages to history
                                chat_sessions[api_key_str][conversation_id]["messages"].append(
                                    {"id": user_msg_id, "role": "user", "content": prompt}
                                )
                                chat_sessions[api_key_str][conversation_id]["messages"].append(
                                    assistant_message
                                )
                                debug_print(f"💾 Updated existing session for conversation {conversation_id}")
                            _persist_sessions()
                            
                            yield "data: [DONE]\n\n"
                            debug_print(f"✅ Stream completed - {len(response_text)} chars sent")
                            return  # Success, exit retry loop
                                
                    except asyncio.CancelledError:
                        # Client disconnected or server shutdown. Avoid leaking proxy jobs or surfacing noisy uvicorn
                        # "response not completed" warnings on cancellation.
                        try:
                            if transport_used == "userscript":
                                jid = str(getattr(stream_context, "job_id", "") or "").strip()
                                if jid:
                                    await _finalize_userscript_proxy_job(jid, error="client disconnected", remove=True)
                        except Exception:
                            pass
                        return
                    except httpx.HTTPStatusError as e:
                        # Handle retry-able errors
                        if e.response.status_code == 429:
                            current_retry_attempt += 1
                            if current_retry_attempt > max_retries:
                                error_msg = "LMArena API error 429: Too many requests. Max retries exceeded. Terminating stream."
                                debug_print(f"❌ {error_msg}")
                                error_chunk = {
                                    "error": {
                                        "message": error_msg,
                                        "type": "api_error",
                                        "code": e.response.status_code,
                                    }
                                }
                                yield f"data: {json.dumps(error_chunk)}\n\n"
                                yield "data: [DONE]\n\n"
                                return

                            retry_after_header = e.response.headers.get("Retry-After")
                            sleep_seconds = get_rate_limit_sleep_seconds(
                                retry_after_header, current_retry_attempt
                            )
                            debug_print(
                                f"⏱️ LMArena API returned 429 (Too Many Requests). "
                                f"Retrying in {sleep_seconds} seconds (attempt {current_retry_attempt}/{max_retries})."
                            )
                            async for ka in wait_with_keepalive(sleep_seconds):
                                yield ka
                            continue # Continue to the next iteration of the while True loop
                        elif e.response.status_code == 403:
                            current_retry_attempt += 1
                            if current_retry_attempt > max_retries:
                                error_msg = "LMArena API error 403: Forbidden. Max retries exceeded. Terminating stream."
                                debug_print(f"❌ {error_msg}")
                                error_chunk = {
                                    "error": {
                                        "message": error_msg,
                                        "type": "api_error",
                                        "code": e.response.status_code,
                                    }
                                }
                                yield f"data: {json.dumps(error_chunk)}\n\n"
                                yield "data: [DONE]\n\n"
                                return
                            
                            debug_print(
                                f"🚫 LMArena API returned 403 (Forbidden). "
                                f"Retrying with exponential backoff (attempt {current_retry_attempt}/{max_retries})."
                            )
                            sleep_seconds = get_general_backoff_seconds(current_retry_attempt)
                            async for ka in wait_with_keepalive(sleep_seconds):
                                yield ka
                            continue # Continue to the next iteration of the while True loop
                        elif e.response.status_code == 401:
                            # Existing 401 handling (token rotation) will implicitly use the retry loop.
                            # We need to ensure max_retries applies here too.
                            current_retry_attempt += 1
                            if current_retry_attempt > max_retries:
                                error_msg = "LMArena API error 401: Unauthorized. Max retries exceeded. Terminating stream."
                                debug_print(f"❌ {error_msg}")
                                error_chunk = {
                                    "error": {
                                        "message": error_msg,
                                        "type": "api_error",
                                        "code": e.response.status_code,
                                    }
                                }
                                yield f"data: {json.dumps(error_chunk)}\n\n"
                                yield "data: [DONE]\n\n"
                                return
                            # The original code has `continue` here, which leads to `async for ka in wait_with_keepalive(2.0): yield ka`.
                            # This is fine for 401 to allow token rotation and retry.
                            async for ka in wait_with_keepalive(2.0):
                                yield ka
                            continue
                        else:
                            # Provide user-friendly error messages for non-retryable errors
                            try:
                                body_text = ""
                                try:
                                    raw = await e.response.aread()
                                    if isinstance(raw, (bytes, bytearray)):
                                        body_text = raw.decode("utf-8", errors="replace")
                                    else:
                                        body_text = str(raw)
                                except Exception:
                                    body_text = ""
                                body_text = str(body_text or "").strip()
                                if body_text:
                                    preview = body_text[:800]
                                    error_msg = f"LMArena API error {e.response.status_code}: {preview}"
                                else:
                                    error_msg = f"LMArena API error: {e.response.status_code}"
                            except Exception:
                                error_msg = f"LMArena API error: {e.response.status_code}"
                            
                            error_type = "api_error"
                            
                            debug_print(f"❌ {error_msg}")
                            error_chunk = {
                                "error": {
                                    "message": error_msg,
                                    "type": error_type,
                                    "code": e.response.status_code
                                }
                            }
                            yield f"data: {json.dumps(error_chunk)}\n\n"
                            yield "data: [DONE]\n\n"
                            return
                    except Exception as e:
                        debug_print(f"❌ Stream error: {str(e)}")
                        # If it's a connection error, we might want to retry indefinitely too? 
                        # For now, let's treat generic exceptions as transient if possible, or just fail safely.
                        # Given "until real content deltas arrive", we should probably be aggressive with retries.
                        # But legitimate internal errors should probably surface.
                        # Let's retry on network-like errors if we can distinguish them.
                        # For now, yield error.
                        error_chunk = {
                            "error": {
                                "message": str(e),
                                "type": "internal_error"
                            }
                        }
                        yield f"data: {json.dumps(error_chunk)}\n\n"
                        yield "data: [DONE]\n\n"
                        return
            return StreamingResponse(generate_stream(), media_type="text/event-stream")
        
        # Handle non-streaming mode with retry
        try:
            response = None
            if time.time() - last_userscript_poll < 15 and not os.environ.get("LM_BRIDGE_DISABLE_USERSCRIPT_PROXY"):
                debug_print(f"🌐 Userscript Proxy is ACTIVE. Delegating non-streaming request...")
                response = await fetch_via_proxy_queue(
                    url=url,
                    payload=payload if isinstance(payload, dict) else {},
                    http_method=http_method,
                    timeout_seconds=120,
                    auth_token=current_token,
                )
                if response:
                    # Raise for status to trigger the standard error handling block below if needed
                    response.raise_for_status()
                else:
                    debug_print("⚠️ Userscript Proxy returned None. Falling back...")

            if response is None:
                if strict_chrome_fetch_model or force_browser_transports_in_stream:
                    debug_print(f"🌐 Using Chrome fetch transport for non-streaming strict model ({model_public_name})...")
                    # Chrome fetch transport has its own internal reCAPTCHA retries, 
                    # but we add an outer loop here to handle token rotation (401) and rate limits (429).
                    max_chrome_retries = 3
                    for chrome_attempt in range(max_chrome_retries):
                        response = await fetch_lmarena_stream_via_chrome(
                            http_method=http_method,
                            url=url,
                            payload=payload if isinstance(payload, dict) else {},
                            auth_token=current_token,
                            timeout_seconds=120,
                        )
                        
                        if response is None:
                            debug_print(f"⚠️ Chrome fetch transport failed (attempt {chrome_attempt+1}). Trying Camoufox...")
                            response = await fetch_lmarena_stream_via_camoufox(
                                http_method=http_method,
                                url=url,
                                payload=payload if isinstance(payload, dict) else {},
                                auth_token=current_token,
                                timeout_seconds=120,
                            )
                            if response is None:
                                break # Critical error
                        
                        if response.status_code == HTTPStatus.UNAUTHORIZED:
                            debug_print(f"🔒 Token {current_token[:20]}... expired in Chrome fetch (attempt {chrome_attempt+1})")
                            failed_tokens.add(current_token)
                            # (Pruning disabled)
                            if chrome_attempt < max_chrome_retries - 1:
                                try:
                                    current_token = get_next_auth_token(exclude_tokens=failed_tokens)
                                    debug_print(f"🔄 Rotating to next token: {current_token[:20]}...")
                                    continue
                                except HTTPException:
                                    break
                        elif response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                            debug_print(f"⏱️  Rate limit in Chrome fetch (attempt {chrome_attempt+1})")
                            if chrome_attempt < max_chrome_retries - 1:
                                sleep_seconds = get_rate_limit_sleep_seconds(response.headers.get("Retry-After"), chrome_attempt)
                                await asyncio.sleep(sleep_seconds)
                                continue
                        
                        # If success or non-retryable error, break and use this response
                        break
                else:
                    response = await make_request_with_retry(url, payload, http_method)
            
            if response is None:
                debug_print("⚠️ Browser transports returned None; falling back to direct httpx.")
                response = await make_request_with_retry(url, payload, http_method)

            if response is None:
                raise HTTPException(
                    status_code=502,
                    detail="Failed to fetch response from LMArena (transport returned None)",
                )
                
            log_http_status(response.status_code, "LMArena API Response")

            # Buffer the response body as bytes. The response object can be one of:
            #   - an httpx.AsyncClient response or BrowserFetchStreamResponse -> async, has `.aread()`
            #   - a `requests`/cloudscraper Response (from make_request_with_retry) -> sync, has `.content`
            # Calling `.aread()` on the latter crashes with AttributeError; handle both.
            if hasattr(response, "aread"):
                response_bytes = await response.aread()
            elif hasattr(response, "content"):
                # requests.Response.content is already buffered bytes.
                response_bytes = response.content or b""
                # For streaming requests.Response, ensure the body is fully read.
                if hasattr(response, "raw") and response.raw is not None:
                    try:
                        response.raw.drain()
                    except Exception:
                        pass
            else:
                # Fallback: try .read() (sync) or stringify.
                try:
                    response_bytes = response.read() or b""
                except Exception:
                    response_bytes = str(getattr(response, "text", "")).encode("utf-8")
            response_text_body = response_bytes.decode("utf-8", errors="replace") if isinstance(response_bytes, (bytes, bytearray)) else str(response_bytes)
            
            debug_print(f"📏 Response length: {len(response_text_body)} characters")
            debug_print(f"📋 Response headers: {dict(response.headers)}")
            
            debug_print(f"🔍 Processing response...")
            debug_print(f"📄 First 500 chars of response:\n{response_text_body[:500]}")
            
            # Process response in lmarena format
            # Format: ag:"thinking" for reasoning, a0:"text chunk" for content, ac:{...} for citations, ad:{...} for metadata
            response_text = ""
            reasoning_text = ""
            citations = []
            finish_reason = None
            line_count = 0
            text_chunks_found = 0
            reasoning_chunks_found = 0
            citation_chunks_found = 0
            metadata_found = 0
            
            debug_print(f"📊 Parsing response lines...")
            
            error_message = None
            for line in response_text_body.splitlines():
                line_count += 1
                line = line.strip()
                if line.startswith("data: "):
                    line = line[6:].strip()
                if not line:
                    continue
                
                # Parse thinking/reasoning chunks: ag:"thinking text"
                if line.startswith("ag:"):
                    chunk_data = line[3:]  # Remove "ag:" prefix
                    reasoning_chunks_found += 1
                    try:
                        # Parse as JSON string (includes quotes)
                        reasoning_chunk = json.loads(chunk_data)
                        reasoning_text += reasoning_chunk
                        if reasoning_chunks_found <= 3:  # Log first 3 reasoning chunks
                            debug_print(f"  🧠 Reasoning chunk {reasoning_chunks_found}: {repr(reasoning_chunk[:50])}")
                    except json.JSONDecodeError as e:
                        debug_print(f"  ⚠️ Failed to parse reasoning chunk on line {line_count}: {chunk_data[:100]} - {e}")
                        continue
                
                # Parse text chunks: a0:"Hello "
                elif line.startswith("a0:"):
                    chunk_data = line[3:]  # Remove "a0:" prefix
                    text_chunks_found += 1
                    try:
                        # Parse as JSON string (includes quotes)
                        text_chunk = json.loads(chunk_data)
                        response_text += text_chunk
                        if text_chunks_found <= 3:  # Log first 3 chunks
                            debug_print(f"  ✅ Chunk {text_chunks_found}: {repr(text_chunk[:50])}")
                    except json.JSONDecodeError as e:
                        debug_print(f"  ⚠️ Failed to parse text chunk on line {line_count}: {chunk_data[:100]} - {e}")
                        continue
                
                # Parse image generation: a2:[{...}] (for image models)
                elif line.startswith("a2:"):
                    image_data = line[3:]  # Remove "a2:" prefix
                    try:
                        image_list = json.loads(image_data)
                        # OpenAI format expects URL in content
                        if isinstance(image_list, list) and len(image_list) > 0:
                            image_obj = image_list[0]
                            otype = image_obj.get('type')
                            if otype == 'image':
                                image_url = image_obj.get('image', '')
                                # Format as markdown
                                response_text = f"![Generated Image]({image_url})"
                            elif otype == 'webdev':
                                # WebDev: LMArena deploys site at https://{modelAMessageId}.arena.site
                                site_url = f"https://{model_msg_id}.arena.site"
                                files = image_obj.get('event', {}).get('files', [])
                                n = len(files) if isinstance(files, list) else 0
                                if response_text:
                                    response_text += f"\n\n**[Web Dev Deployed]**\nLive site: {site_url}\nFiles: index.html + {n} assets"
                                else:
                                    response_text = (f"**[Web Dev Deployed]**\n"
                                                     f"Live site: {site_url}\n"
                                                     f"Files: index.html + {n} assets")
                    except json.JSONDecodeError as e:
                        debug_print(f"  ⚠️ Failed to parse image data on line {line_count}: {image_data[:100]} - {e}")
                        continue
                
                # Parse citations/tool calls: ac:{...} (for search models)
                elif line.startswith("ac:"):
                    citation_data = line[3:]  # Remove "ac:" prefix
                    citation_chunks_found += 1
                    try:
                        citation_obj = json.loads(citation_data)
                        # Extract source information from argsTextDelta
                        if 'argsTextDelta' in citation_obj:
                            args_data = json.loads(citation_obj['argsTextDelta'])
                            if 'source' in args_data:
                                source = args_data['source']
                                # Can be a single source or array of sources
                                if isinstance(source, list):
                                    citations.extend(source)
                                elif isinstance(source, dict):
                                    citations.append(source)
                        if citation_chunks_found <= 3:  # Log first 3 citations
                            debug_print(f"  🔗 Citation chunk {citation_chunks_found}: {citation_obj.get('toolCallId')}")
                    except json.JSONDecodeError as e:
                        debug_print(f"  ⚠️ Failed to parse citation chunk on line {line_count}: {citation_data[:100]} - {e}")
                        continue
                
                # Parse error messages: a3:"An error occurred"
                elif line.startswith("a3:"):
                    error_data = line[3:]  # Remove "a3:" prefix
                    try:
                        error_message = json.loads(error_data)
                        debug_print(f"  ❌ Error message received: {error_message}")
                    except json.JSONDecodeError as e:
                        debug_print(f"  ⚠️ Failed to parse error message on line {line_count}: {error_data[:100]} - {e}")
                        error_message = error_data
                
                # Parse metadata: ad:{"finishReason":"stop"}
                elif line.startswith("ad:"):
                    metadata_data = line[3:]  # Remove "ad:" prefix
                    metadata_found += 1
                    try:
                        metadata = json.loads(metadata_data)
                        finish_reason = metadata.get("finishReason")
                        debug_print(f"  📋 Metadata found: finishReason={finish_reason}")
                    except json.JSONDecodeError as e:
                        debug_print(f"  ⚠️ Failed to parse metadata on line {line_count}: {metadata_data[:100]} - {e}")
                        continue
                elif line.strip():  # Non-empty line that doesn't match expected format
                    if line_count <= 5:  # Log first 5 unexpected lines
                        debug_print(f"  ❓ Unexpected line format {line_count}: {line[:100]}")

            debug_print(f"\n📊 Parsing Summary:")
            debug_print(f"  - Total lines: {line_count}")
            debug_print(f"  - Reasoning chunks found: {reasoning_chunks_found}")
            debug_print(f"  - Text chunks found: {text_chunks_found}")
            debug_print(f"  - Citation chunks found: {citation_chunks_found}")
            debug_print(f"  - Metadata entries: {metadata_found}")
            debug_print(f"  - Final response length: {len(response_text)} chars")
            debug_print(f"  - Final reasoning length: {len(reasoning_text)} chars")
            debug_print(f"  - Citations found: {len(citations)}")
            debug_print(f"  - Finish reason: {finish_reason}")
            
            if not response_text:
                debug_print(f"\n⚠️  WARNING: Empty response text!")
                debug_print(f"📄 Full raw response:\n{response_text_body}")
                if error_message:
                    error_detail = f"LMArena API error: {error_message}"
                    print(f"❌ {error_detail}")
                    # Return OpenAI-compatible error response
                    return {
                        "error": {
                            "message": error_detail,
                            "type": "upstream_error",
                            "code": "lmarena_error"
                        }
                    }
                else:
                    error_detail = "LMArena API returned empty response. This could be due to: invalid auth token, expired cf_clearance, model unavailable, or API rate limiting."
                    debug_print(f"❌ {error_detail}")
                    # Return OpenAI-compatible error response
                    return {
                        "error": {
                            "message": error_detail,
                            "type": "upstream_error",
                            "code": "empty_response"
                        }
                    }
            else:
                debug_print(f"✅ Response text preview: {response_text[:200]}...")
            
            # Update session - Store message history with IDs (including reasoning and citations if present)
            assistant_message = {
                "id": model_msg_id, 
                "role": "assistant", 
                "content": response_text.strip()
            }
            if reasoning_text:
                assistant_message["reasoning_content"] = reasoning_text.strip()
            if citations:
                # Deduplicate citations by URL
                unique_citations = []
                seen_urls = set()
                for citation in citations:
                    citation_url = citation.get('url')
                    if citation_url and citation_url not in seen_urls:
                        seen_urls.add(citation_url)
                        unique_citations.append(citation)
                assistant_message["citations"] = unique_citations
            
            if not session:
                chat_sessions[api_key_str][conversation_id] = {
                    "conversation_id": session_id,
                    "model": model_public_name,
                    "messages": [
                        {"id": user_msg_id, "role": "user", "content": prompt},
                        assistant_message
                    ]
                }
                debug_print(f"💾 Saved new session for conversation {conversation_id}")
                _persist_sessions()
            else:
                # Append new messages to history
                chat_sessions[api_key_str][conversation_id]["messages"].append(
                    {"id": user_msg_id, "role": "user", "content": prompt}
                )
                chat_sessions[api_key_str][conversation_id]["messages"].append(
                    assistant_message
                )
                debug_print(f"💾 Updated existing session for conversation {conversation_id}")

            # Build message object with reasoning and citations if present
            message_obj = {
                "role": "assistant",
                "content": response_text.strip(),
            }
            if reasoning_text:
                message_obj["reasoning_content"] = reasoning_text.strip()
            if citations:
                # Deduplicate citations by URL
                unique_citations = []
                seen_urls = set()
                for citation in citations:
                    citation_url = citation.get('url')
                    if citation_url and citation_url not in seen_urls:
                        seen_urls.add(citation_url)
                        unique_citations.append(citation)
                message_obj["citations"] = unique_citations
                
                # Add citations as markdown footnotes
                if unique_citations:
                    footnotes = "\n\n---\n\n**Sources:**\n\n"
                    for i, citation in enumerate(unique_citations, 1):
                        title = citation.get('title', 'Untitled')
                        url = citation.get('url', '')
                        footnotes += f"{i}. [{title}]({url})\n"
                    message_obj["content"] = response_text.strip() + footnotes
            
            # Image models already have markdown formatting from parsing
            # No additional conversion needed
            
            # Calculate token counts (including reasoning tokens)
            prompt_tokens = len(prompt)
            completion_tokens = len(response_text)
            reasoning_tokens = len(reasoning_text)
            total_tokens = prompt_tokens + completion_tokens + reasoning_tokens
            
            # Build usage object with reasoning tokens if present
            usage_obj = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens
            }
            if reasoning_tokens > 0:
                usage_obj["reasoning_tokens"] = reasoning_tokens
            
            final_response = {
                "id": f"chatcmpl-{uuid.uuid4()}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_public_name,
                "conversation_id": conversation_id,
                "choices": [{
                    "index": 0,
                    "message": message_obj,
                    "finish_reason": "stop"
                }],
                "usage": usage_obj
            }
            
            debug_print(f"\n✅ REQUEST COMPLETED SUCCESSFULLY")
            debug_print("="*80 + "\n")
            
            return final_response

        except httpx.HTTPStatusError as e:
            # Log error status
            log_http_status(e.response.status_code, "Error Response")
            
            # Try to parse JSON error response from LMArena
            lmarena_error = None
            try:
                error_body = e.response.json()
                if isinstance(error_body, dict) and "error" in error_body:
                    lmarena_error = error_body["error"]
                    debug_print(f"📛 LMArena error message: {lmarena_error}")
            except:
                pass
            
            # Provide user-friendly error messages
            if e.response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                error_detail = "Rate limit exceeded on LMArena. Please try again in a few moments."
                error_type = "rate_limit_error"
            elif e.response.status_code == HTTPStatus.UNAUTHORIZED:
                error_detail = "Unauthorized: Your LMArena auth token has expired or is invalid. Please get a new auth token from the dashboard."
                error_type = "authentication_error"
            elif e.response.status_code == HTTPStatus.FORBIDDEN:
                error_detail = f"Forbidden: Access to this resource is denied. {e.response.text}"
                error_type = "forbidden_error"
            elif e.response.status_code == HTTPStatus.NOT_FOUND:
                error_detail = "Not Found: The requested resource doesn't exist."
                error_type = "not_found_error"
            elif e.response.status_code == HTTPStatus.BAD_REQUEST:
                # Use LMArena's error message if available
                if lmarena_error:
                    error_detail = f"Bad Request: {lmarena_error}"
                else:
                    error_detail = f"Bad Request: Invalid request parameters. {e.response.text}"
                error_type = "bad_request_error"
            elif e.response.status_code >= 500:
                error_detail = f"Server Error: LMArena API returned {e.response.status_code}"
                error_type = "server_error"
            else:
                error_detail = f"LMArena API error {e.response.status_code}: {e.response.text}"
                error_type = "upstream_error"
            
            print(f"\n❌ HTTP STATUS ERROR")
            print(f"📛 Error detail: {error_detail}")
            print(f"📤 Request URL: {url}")
            debug_print(f"📤 Request payload (truncated): {json.dumps(payload, indent=2)[:500]}")
            debug_print(f"📥 Response text: {e.response.text[:500]}")
            print("="*80 + "\n")
            
            # Return OpenAI-compatible error response
            return {
                "error": {
                    "message": error_detail,
                    "type": error_type,
                    "code": f"http_{e.response.status_code}"
                }
            }
        
        except httpx.TimeoutException as e:
            print(f"\n⏱️  TIMEOUT ERROR")
            print(f"📛 Request timed out after 120 seconds")
            print(f"📤 Request URL: {url}")
            print("="*80 + "\n")
            # Return OpenAI-compatible error response
            return {
                "error": {
                    "message": "Request to LMArena API timed out after 120 seconds",
                    "type": "timeout_error",
                    "code": "request_timeout"
                }
            }
        
        except Exception as e:
            print(f"\n❌ UNEXPECTED ERROR IN HTTP CLIENT")
            print(f"📛 Error type: {type(e).__name__}")
            print(f"📛 Error message: {str(e)}")
            print(f"📤 Request URL: {url}")
            print("="*80 + "\n")
            # Return OpenAI-compatible error response
            return {
                "error": {
                    "message": f"Unexpected error: {str(e)}",
                    "type": "internal_error",
                    "code": type(e).__name__.lower()
                }
            }
                
    except HTTPException:
        raise
    except Exception as e:
        print(f"\n❌ TOP-LEVEL EXCEPTION")
        print(f"📛 Error type: {type(e).__name__}")
        print(f"📛 Error message: {str(e)}")
        print("="*80 + "\n")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


# Anthropic API Models
from pydantic import BaseModel
from typing import Any

class AnthropicMessageRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    max_tokens: int
    system: Optional[str] = None
    temperature: Optional[float] = None
    stream: Optional[bool] = False


@app.post("/api/v1/messages")
async def anthropic_messages(request: AnthropicMessageRequest, raw_request: Request, api_key: dict = Depends(rate_limit_api_key)):
    """
    Anthropic Messages API endpoint.
    Translates Anthropic-style requests to OpenAI-style and processes through LMArena.
    """
    debug_print("\n" + "="*80)
    debug_print("🟣 ANTHROPIC MESSAGES REQUEST RECEIVED")
    debug_print("="*80)
    debug_print(f"🤖 Model: {request.model}")
    debug_print(f"💬 Messages: {len(request.messages)}")
    debug_print(f"🌊 Stream: {request.stream}")

    # Convert Anthropic messages to OpenAI format
    openai_messages = []
    for msg in request.messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            # Handle content blocks
            text_parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            content = "\n".join(text_parts)
        openai_messages.append({"role": role, "content": content})

    # Add system message if present
    if request.system:
        openai_messages.insert(0, {"role": "system", "content": request.system})

    # Build OpenAI-style request body
    openai_body = {
        "model": request.model,
        "messages": openai_messages,
        "max_tokens": request.max_tokens,
        "stream": request.stream,
    }
    if request.temperature is not None:
        openai_body["temperature"] = request.temperature

    debug_print(f"📦 Converted to OpenAI format")

    # Create a mock request object for the chat completions handler
    class MockRequest:
        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

        async def is_disconnected(self):
            return await raw_request.is_disconnected()

    mock_request = MockRequest(openai_body)

    if request.stream:
        # Streaming response - convert OpenAI SSE to Anthropic format
        async def anthropic_stream_generator():
            message_id = f"msg_{uuid.uuid4()}"
            accumulated_text = ""
            buffer = ""
            
            # Send message_start
            yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': {'id': message_id, 'type': 'message', 'role': 'assistant', 'content': [], 'model': request.model, 'stop_reason': None, 'usage': {'input_tokens': sum(len(str(m.get('content', ''))) for m in openai_messages), 'output_tokens': 0}}})}\n\n"

            # Send content_block_start
            yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': ''}})}\n\n"

            try:
                result = await api_chat_completions(mock_request, api_key)

                # Return error for dict response (error case)
                if isinstance(result, dict) and result.get("error"):
                    yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'message': result['error'].get('message', 'Unknown error'), 'type': result['error'].get('type', 'invalid_request_error')}})}\n\n"
                    return
                
                if isinstance(result, StreamingResponse):
                    async for chunk in result.body_iterator:
                        chunk_str = chunk.decode('utf-8') if isinstance(chunk, bytes) else str(chunk)
                        buffer += chunk_str
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if not line.startswith('data: '):
                                continue
                            data = line[6:]
                            if data == '[DONE]':
                                break
                            try:
                                chunk_data = json.loads(data)
                                delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                                if "content" in delta:
                                    content = delta["content"]
                                    accumulated_text += content
                                    yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': content}})}\n\n"
                            except json.JSONDecodeError:
                                continue
                else:
                    yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'message': 'Unexpected non-streaming response from API', 'type': 'internal_error'}})}\n\n"
                    return

            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'type': 'error', 'error': {'message': str(e), 'type': 'internal_error'}})}\n\n"
                return

            # Send content_block_stop
            yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': 0})}\n\n"

            # Send message_delta
            yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': len(accumulated_text)}})}\n\n"

            # Send message_stop
            yield f"event: message_stop\ndata: {json.dumps({'type': 'message_stop'})}\n\n"

        return StreamingResponse(
            anthropic_stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    else:
        # Non-streaming response
        result = await api_chat_completions(mock_request, api_key)

        if isinstance(result, StreamingResponse):
            # Read streaming response
            full_text = ""
            async for chunk in result.body_iterator:
                chunk_str = chunk.decode('utf-8') if isinstance(chunk, bytes) else str(chunk)
                for line in chunk_str.strip().split('\n'):
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            chunk_data = json.loads(data)
                            delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                            if "content" in delta:
                                full_text += delta["content"]
                        except json.JSONDecodeError:
                            continue

            return {
                "id": f"msg_{uuid.uuid4()}",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": full_text}],
                "model": request.model,
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 0, "output_tokens": len(full_text.split())}
            }

        if isinstance(result, dict) and "error" in result:
            raise HTTPException(status_code=400, detail=result["error"].get("message", "Unknown error"))

        # Convert OpenAI response to Anthropic format
        choices = result.get("choices", [])
        content = ""
        if choices:
            content = choices[0].get("message", {}).get("content", "")

        return {
            "id": result.get("id", f"msg_{uuid.uuid4()}"),
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": content}],
            "model": request.model,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": result.get("usage", {}).get("prompt_tokens", 0), "output_tokens": result.get("usage", {}).get("completion_tokens", len(content))}
        }


@app.post("/api/v1/responses")
async def api_responses(request: Request, api_key: dict = Depends(rate_limit_api_key)):
    """OpenAI-compatible Responses API endpoint.

    Accepts OpenAI /v1/responses body (model, input, tools, stream) and returns
    an OpenAI Responses-format payload: output items (message / image_generation_call).

    The request is converted to the internal chat/completions format and
    processed by the same engine, then re-wrapped into Responses format.
    """
    import httpx as _httpx

    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in request body: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read request body: {str(e)}")

    model_public_name = body.get("model")
    input_data = body.get("input", "")
    stream = body.get("stream", False)

    if not model_public_name:
        raise HTTPException(status_code=400, detail="Missing 'model' in request body.")

    # Convert Responses-API input to chat messages
    # input can be a string or an array of items
    if isinstance(input_data, str):
        messages = [{"role": "user", "content": input_data}]
    elif isinstance(input_data, list):
        messages = []
        for item in input_data:
            if isinstance(item, str):
                messages.append({"role": "user", "content": item})
            elif isinstance(item, dict):
                role = item.get("role", "user")
                content = item.get("content", "")
                # content can be a list of parts (input_text / input_image)
                if isinstance(content, list):
                    parts = []
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        ptype = part.get("type", "")
                        if ptype in ("input_text", "text"):
                            parts.append({"type": "text", "text": part.get("text", "")})
                        elif ptype in ("input_image", "image_url"):
                            url = part.get("image_url", "")
                            parts.append({"type": "image_url", "image_url": {"url": url}})
                    messages.append({"role": role, "content": parts or ""})
                else:
                    messages.append({"role": role, "content": content})
    else:
        raise HTTPException(status_code=400, detail="'input' must be a string or an array.")

    # Build chat/completions request to the internal endpoint
    chat_body = {
        "model": model_public_name,
        "messages": messages,
        "stream": False,
    }

    try:
        async with _httpx.AsyncClient(timeout=180) as c:
            resp = await c.post(
                f"http://127.0.0.1:{PORT}/api/v1/chat/completions",
                json=chat_body,
                headers={"Authorization": f"Bearer {api_key['key']}"},
            )
    except _httpx.TimeoutException as e:
        raise HTTPException(status_code=504, detail=f"Bridge upstream timed out: {e}")
    except _httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Bridge upstream error: {e}")

    if resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error", {}).get("message", resp.text[:200]) if isinstance(err, dict) else resp.text[:200]
        except Exception:
            msg = resp.text[:200]
        raise HTTPException(status_code=resp.status_code, detail=msg)

    data = resp.json()

    # Check if the inner response is actually an error (chat/completions returns 200
    # with an error body when upstream fails)
    if "error" in data:
        err = data["error"]
        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
        raise HTTPException(status_code=502, detail=msg)

    # Convert chat.completion to Responses API format
    message = data.get("choices", [{}])[0].get("message", {})
    content = message.get("content", "")

    # Detect image generation (markdown image) → image_generation_call output
    output_items = []
    image_url = None
    if "![Generated Image](" in content:
        start = content.index("![Generated Image](") + len("![Generated Image](")
        end = content.index(")", start)
        image_url = content[start:end]
        output_items.append({
            "type": "image_generation_call",
            "id": f"gen_{uuid.uuid4().hex[:12]}",
            "call_id": f"call_{uuid.uuid4().hex[:12]}",
            "status": "completed",
            "result": image_url,
        })
    else:
        output_items.append({
            "type": "message",
            "id": f"msg_{uuid.uuid4().hex[:12]}",
            "role": "assistant",
            "content": [{"type": "output_text", "text": content}],
        })

    # WebDev detection: if the assistant message carries citations (sources with
    # URLs) or a deployed-site link, surface them as a web_app output item.
    deployed_urls = []
    if message.get("citations"):
        for cit in message["citations"]:
            if isinstance(cit, dict) and cit.get("url"):
                u = str(cit["url"])
                if u not in deployed_urls:
                    deployed_urls.append(u)
    # Fallback: scan content for bare https links to deployed sites
    if not deployed_urls:
        import re as _re
        for m_url in _re.finditer(r"https?://[^\s)\]]+", content):
            u = m_url.group(0).rstrip(".,;")
            if u not in deployed_urls:
                deployed_urls.append(u)
    if deployed_urls:
        output_items.append({
            "type": "web_app",
            "id": f"web_{uuid.uuid4().hex[:12]}",
            "call_id": f"call_{uuid.uuid4().hex[:12]}",
            "status": "completed",
            "url": deployed_urls[0],
            "urls": deployed_urls,
        })

    response_id = data.get("id", f"resp_{uuid.uuid4().hex[:12]}")
    responses_payload = {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "model": data.get("model", model_public_name),
        "output": output_items,
        "output_text": content if not image_url else "",
        "parallel_tool_calls": True,
        "temperature": None,
        "tool_choice": "auto",
        "tools": [],
        "top_p": None,
        "truncation": None,
        "usage": data.get("usage", {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        }),
        "user": None,
        "metadata": {},
    }
    return responses_payload


if __name__ == "__main__":
    # Handle Windows console encoding issues
    try:
        import sys

        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Resolve the configured backend port. Tests and embedded ASGI clients must
    # not launch browser/network startup work.
    from .configurator import resolve_port
    resolved = resolve_port(constants.PORT)
    PORT = resolved
    print("=" * 30)
    print("Arena Bridge Server Starting...")
    print("=" * 30)
    print(f"Dashboard: http://localhost:{PORT}/dashboard")
    print(f"API Base URL: http://localhost:{PORT}/api/v1")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=PORT)