// analyze_image.mjs — CitiView AV single-image lifecycle-signal extraction via the Claude
// Agent SDK, authenticated with a Claude Code subscription token (CLAUDE_CODE_OAUTH_TOKEN),
// NOT a metered Anthropic API key. Mirrors generate_slide_copy.mjs exactly: same auth gate,
// hermetic single-turn query(), tolerant JSON parsing, [MOCK] fallback. Invoked one-shot per
// image from Python (image_analysis.py). Prints ONE JSON object of visual signals to stdout.
//
// Contract with the caller (image_analysis.py):
//   - The image at <path> is assumed ALREADY bounded/normalized (Python downscales large
//     photos to a size Claude vision accepts). This script does NO image processing — it only
//     base64-encodes the bytes and asks Claude for signals.
//   - Output is SIGNALS ONLY. There is deliberately NO order/sequence/index field: ordering is
//     owned by the deterministic Python engine, never the LLM.
//
// Usage: node analyze_image.mjs "<event context>" <image_path>

import { query } from '@anthropic-ai/claude-agent-sdk';
import { readFileSync } from 'node:fs';
import { extname } from 'node:path';

const MODEL = 'haiku'; // subscription channel resolves to the current Haiku release (Haiku 4.5)

// The six 0..1 signals + the categorical activity signal the deterministic engine consumes.
const NUMERIC_SIGNALS = [
  'venue_readiness',
  'av_staging_completeness',
  'decor_completeness',
  'polish_vs_clutter',
  'live_event_cue',
  'teardown_cue',
];
const ACTIVITY_VALUES = ['none', 'crew', 'guests', 'audience', 'teardown'];

const SYSTEM_PROMPT = `You are a visual analyst for CitiView AV, an event audio-visual production \
company. You are shown ONE photograph from somewhere in an event's lifecycle (an empty venue, \
gear being loaded in, AV/staging being built, a finished guest-ready room, a live event in \
progress, or a teardown/strike). Assess ONLY what is visible in THIS image. Do not guess at a \
sequence, do not compare to other images, do not output any order or index — another system \
handles ordering.

Return a SINGLE JSON object (no markdown, no code fences, no prose) with EXACTLY these keys:
- "venue_readiness":        {"value": 0..1, "confidence": 0..1}  // 0 bare empty room, 1 fully dressed & ready
- "av_staging_completeness":{"value": 0..1, "confidence": 0..1}  // 0 no AV, 1 finished rig (screens/truss/lighting/audio installed & dressed)
- "decor_completeness":     {"value": 0..1, "confidence": 0..1}  // 0 none, 1 tables/florals/branding fully placed
- "polish_vs_clutter":      {"value": 0..1, "confidence": 0..1}  // 0 cluttered (cases, coiled cable, ladders, tools, packaging), 1 clean & show-ready
- "live_event_cue":         {"value": 0..1, "confidence": 0..1}  // 0 none, 1 clearly live (audience present, house lights down, stage/show active)
- "teardown_cue":           {"value": 0..1, "confidence": 0..1}  // 0 none, 1 clearly striking (partial rig coming down, stacked cases, debris, empty post-event)
- "human_activity_type":    {"value": "none|crew|guests|audience|teardown", "confidence": 0..1}
- "alt_description":        a short factual one-sentence description of the image (accessibility alt text)
- "raw_labels":             array of 3-8 short visible-object/scene labels (e.g. "coiled cable", "LED wall", "empty chairs")

value and confidence are numbers between 0 and 1. Base every judgement strictly on visible \
evidence. Distinguish a teardown (gear coming DOWN, stacked/packed cases, debris) from a setup \
(gear going UP) — they look similar, so weigh direction cues carefully. RESPOND WITH VALID JSON ONLY.`;

// Reject API key FIRST — even if the subscription token is also present. A stray API key could
// otherwise route this call onto metered billing instead of subscription usage.
function resolveAuth() {
  if (process.env.ANTHROPIC_API_KEY) {
    throw new Error(
      'ANTHROPIC_API_KEY is set, but this path authenticates Claude only via ' +
      'CLAUDE_CODE_OAUTH_TOKEN (Claude Code subscription). Unset ANTHROPIC_API_KEY ' +
      'so usage is not routed onto metered API billing.'
    );
  }
  if (process.env.CLAUDE_CODE_OAUTH_TOKEN) {
    return { mode: 'oauth' };
  }
  // reason: single-operator local tool (see CLAUDE.md) — "no token" always means mock,
  // never a hard throw, matching generate_slide_copy.mjs.
  return { mode: 'mock' };
}

function mediaTypeFor(path) {
  const ext = extname(path).toLowerCase();
  switch (ext) {
    case '.png': return 'image/png';
    case '.jpg':
    case '.jpeg': return 'image/jpeg';
    case '.webp': return 'image/webp';
    case '.gif': return 'image/gif';
    default: return 'image/jpeg';
  }
}

function buildMockOutput() {
  // MOCK_SEMANTIC: all confidence 0.0 so the deterministic engine collapses state_confidence
  // to ~0 and routes the item to human review, rather than trusting a fabricated signal.
  const mock = {};
  for (const s of NUMERIC_SIGNALS) mock[s] = { value: 0.0, confidence: 0.0 };
  mock.human_activity_type = { value: 'none', confidence: 0.0 };
  mock.alt_description = '[MOCK] Set CLAUDE_CODE_OAUTH_TOKEN for real image analysis.';
  mock.raw_labels = ['[MOCK]'];
  return mock;
}

function clamp01(n) {
  const x = Number(n);
  if (!Number.isFinite(x)) throw new Error('signal value is not a finite number');
  return Math.min(1, Math.max(0, x));
}

// Tolerant parse + strict shape validation, mirroring generate_slide_copy.mjs::parseJsonArray.
function parseSignals(text) {
  let clean = text.trim();
  if (clean.startsWith('```')) {
    clean = clean.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '');
  }
  const parsed = JSON.parse(clean);
  if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`Expected a JSON object, got: ${JSON.stringify(parsed).slice(0, 200)}`);
  }
  const out = {};
  for (const s of NUMERIC_SIGNALS) {
    const r = parsed[s];
    if (!r || typeof r !== 'object') throw new Error(`Missing/invalid signal: ${s}`);
    out[s] = { value: clamp01(r.value), confidence: clamp01(r.confidence) };
  }
  const act = parsed.human_activity_type;
  if (!act || typeof act !== 'object') throw new Error('Missing human_activity_type');
  const av = String(act.value);
  if (!ACTIVITY_VALUES.includes(av)) throw new Error(`human_activity_type.value not in ${ACTIVITY_VALUES.join('|')}: ${av}`);
  out.human_activity_type = { value: av, confidence: clamp01(act.confidence) };
  out.alt_description = typeof parsed.alt_description === 'string' ? parsed.alt_description : '';
  out.raw_labels = Array.isArray(parsed.raw_labels) ? parsed.raw_labels.map(String).slice(0, 12) : [];
  return out;
}

// Hermetic single-turn call — no tools, no CLAUDE.md/settings loaded — behaves like a plain
// structured completion. The image + instruction are delivered as ONE streamed user message,
// which is how the Agent SDK carries multimodal input (prompt: AsyncIterable<SDKUserMessage>).
async function runModel(context, imagePath) {
  const data = readFileSync(imagePath).toString('base64');
  const media_type = mediaTypeFor(imagePath);
  const instruction =
    `EVENT CONTEXT: ${context || 'No additional context provided.'}\n` +
    `Analyze this single image and return the JSON signal object.`;

  async function* promptStream() {
    yield {
      type: 'user',
      parent_tool_use_id: null,
      message: {
        role: 'user',
        content: [
          { type: 'image', source: { type: 'base64', media_type, data } },
          { type: 'text', text: instruction },
        ],
      },
    };
  }

  const response = query({
    prompt: promptStream(),
    options: {
      systemPrompt: SYSTEM_PROMPT,
      model: MODEL,
      maxTurns: 1,
      allowedTools: [],
      settingSources: [],
    },
  });

  let finalText = null;
  for await (const message of response) {
    if (message.type === 'result') {
      if (message.subtype !== 'success') {
        throw new Error(`Model call did not complete successfully (${message.subtype}).`);
      }
      finalText = message.result;
    }
  }
  if (!finalText) throw new Error('Model call returned no text content');
  return finalText;
}

async function main() {
  const [contextArg, imagePath] = process.argv.slice(2);
  if (!imagePath) {
    console.error('Usage: node analyze_image.mjs "<context>" <image_path>');
    process.exit(1);
  }

  let auth;
  try {
    auth = resolveAuth();
  } catch (err) {
    console.error(err.message);
    process.exit(2);
  }

  if (auth.mode === 'mock') {
    console.log(JSON.stringify(buildMockOutput()));
    return;
  }

  try {
    const text = await runModel(contextArg, imagePath);
    const signals = parseSignals(text);
    console.log(JSON.stringify(signals));
  } catch (err) {
    console.error(err.message || String(err));
    process.exit(3);
  }
}

main();
