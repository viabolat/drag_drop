import json
import logging
import os
import subprocess

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# reason: the Claude Agent SDK (subscription-token auth) is Node-only — see
# generate_slide_copy.mjs, ported from the claude_token_template.md / quoting-engine.ts
# reference pattern. Invoked as a one-shot subprocess, mirroring how compositor.py already
# shells out to ffmpeg per render rather than requiring a long-running Node process.
NODE_SCRIPT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_slide_copy.mjs")
SUBPROCESS_TIMEOUT_SECONDS = 60


def _build_mock_copy(slide_count: int) -> list[dict]:
    return [
        {
            "kicker": "[MOCK]",
            "headline": f"[MOCK] Slide {i + 1} Headline",
            "sub": "[MOCK] Set CLAUDE_CODE_OAUTH_TOKEN for real AI-generated copy.",
        }
        for i in range(slide_count)
    ]


def generate_slide_copy(context: str, slide_count: int) -> list[dict]:
    """Generate kicker/headline/sub copy for `slide_count` slides from a free-text `context`.

    Delegates to generate_slide_copy.mjs, which authenticates via CLAUDE_CODE_OAUTH_TOKEN
    (a Claude Code subscription token) through the Claude Agent SDK — never a metered
    ANTHROPIC_API_KEY, which that script explicitly rejects if set. Returns a list of
    {"kicker", "headline", "sub"} dicts, index-aligned to slide order. Falls back to a
    clearly [MOCK]-prefixed placeholder when no token is configured, Node/the script is
    unavailable, or the live call fails for any reason — this function never raises.
    """
    if slide_count < 1:
        return []

    try:
        result = subprocess.run(
            ["node", NODE_SCRIPT_PATH, context, str(slide_count)],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            logger.warning("generate_slide_copy.mjs failed (exit %s): %s", result.returncode, result.stderr.strip())
            return _build_mock_copy(slide_count)

        parsed = json.loads(result.stdout)
        if not isinstance(parsed, list) or len(parsed) != slide_count:
            raise ValueError(f"Expected a JSON array of {slide_count} items, got: {parsed!r}")
        for item in parsed:
            for key in ("kicker", "headline", "sub"):
                if key not in item:
                    raise ValueError(f"Slide copy item missing required field: {key}")
        return parsed
    except FileNotFoundError:
        logger.warning("node executable not found — returning mock slide copy.")
        return _build_mock_copy(slide_count)
    except Exception:
        # reason: subprocess timeouts, malformed stdout, and JSON/shape errors should all
        # degrade to the same mock fallback rather than crash the request — see STACK.md's
        # "never let a failed LLM call crash the workflow silently."
        logger.exception("Slide copy generation failed — falling back to mock copy.")
        return _build_mock_copy(slide_count)
