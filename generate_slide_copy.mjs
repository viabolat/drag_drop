// generate_slide_copy.mjs — CitiView AV slide-copy generation via the Claude Agent SDK,
// authenticated with a Claude Code subscription token (CLAUDE_CODE_OAUTH_TOKEN), not a
// metered Anthropic API key. Invoked as a one-shot subprocess from text_generation.py —
// mirrors how compositor.py already shells out to ffmpeg per render, adapted from the
// quoting-engine.ts / claude_token_template.md reference pattern (auth gate, hermetic
// single-turn query, tolerant JSON parsing, [MOCK] fallback).
//
// Usage: node generate_slide_copy.mjs "<event context>" <slide count>
// Prints a JSON array of {kicker, headline, sub} objects to stdout on success.

import { query } from '@anthropic-ai/claude-agent-sdk';

const MODEL = 'haiku'; // model alias — subscription channel resolves to the current Haiku release

const SYSTEM_PROMPT = `You are CitiView AV's social media copywriter. CitiView AV is an event \
audio-visual production company (full event production, lighting, staging, sound, video, \
streaming). Given a short description of an event and how many slides a post needs, write \
punchy, on-brand slide copy for a portrait social video/PDF deck.

For each slide, produce:
- "kicker": a short (1-4 word) label/tag line (e.g. "Live Now", "Backstage")
- "headline": a punchy title-case headline (3-8 words)
- "sub": one short supporting line (under 60 characters)

Vary the copy across slides so the deck reads as a narrative, not repeated text.

RESPOND WITH VALID JSON ONLY: a JSON array of exactly the requested number of objects, \
each with keys "kicker", "headline", "sub". No markdown, no code fences, no explanation \
outside the JSON.`;

// Reject API key FIRST — even if the subscription token is also present. A stray API key
// could otherwise route this call onto metered billing instead of subscription usage.
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
  // reason: this is a single-operator local tool (see CLAUDE.md) with no formal
  // production/deployment concept, unlike the reference services — so "no token" always
  // means mock, never a hard throw.
  return { mode: 'mock' };
}

function buildMockOutput(count) {
  return Array.from({ length: count }, (_, i) => ({
    kicker: '[MOCK]',
    headline: `[MOCK] Slide ${i + 1} Headline`,
    sub: '[MOCK] Set CLAUDE_CODE_OAUTH_TOKEN for real AI-generated copy.',
  }));
}

function parseJsonArray(text, expectedCount) {
  let clean = text.trim();
  if (clean.startsWith('```')) {
    clean = clean.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '');
  }
  const parsed = JSON.parse(clean);
  if (!Array.isArray(parsed) || parsed.length !== expectedCount) {
    throw new Error(`Expected a JSON array of ${expectedCount} items, got: ${JSON.stringify(parsed).slice(0, 200)}`);
  }
  for (const item of parsed) {
    for (const key of ['kicker', 'headline', 'sub']) {
      if (!(key in item)) throw new Error(`Slide copy item missing required field: ${key}`);
    }
  }
  return parsed;
}

// Hermetic single-turn call — no tools, no CLAUDE.md/settings loaded — behaves like a
// plain structured completion rather than an agentic loop.
async function runModel(context, count) {
  const prompt =
    `EVENT CONTEXT: ${context || 'No additional context provided.'}\n` +
    `SLIDE COUNT: ${count}\n\n` +
    `Return a JSON array of exactly ${count} slide copy objects.`;

  const response = query({
    prompt,
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
  const [contextArg, countArg] = process.argv.slice(2);
  const count = parseInt(countArg, 10);
  if (!Number.isFinite(count) || count < 1) {
    console.error('Usage: node generate_slide_copy.mjs "<context>" <count>');
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
    console.log(JSON.stringify(buildMockOutput(count)));
    return;
  }

  try {
    const text = await runModel(contextArg, count);
    const slides = parseJsonArray(text, count);
    console.log(JSON.stringify(slides));
  } catch (err) {
    console.error(err.message || String(err));
    process.exit(3);
  }
}

main();
