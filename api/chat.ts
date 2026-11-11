export const config = {
  runtime: 'edge',
};

// Anti-AI-slop filter matching Ultron persona engine
const BANNED_PATTERNS = [
  /\bcertainly!?\b/gi,
  /\bas an ai\b/gi,
  /\bi'?d be happy to\b/gi,
  /\bi'?m just an ai\b/gi,
  /\bgreat question!?\b/gi,
  /\bof course!?\b/gi,
  /\bi hope this helps\b/gi,
  /\bfeel free to\b/gi,
  /\blet me know if\b/gi,
  /\bi apologize\b/gi,
  /\bi'm sorry\b/gi,
];

function sanitizeUltronReply(text: string): string {
  let clean = text;
  for (const pattern of BANNED_PATTERNS) {
    clean = clean.replace(pattern, '');
  }
  return clean.replace(/\s{2,}/g, ' ').trim();
}

export default async function handler(req: Request) {
  if (req.method === 'OPTIONS') {
    return new Response(null, {
      status: 200,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      },
    });
  }

  if (req.method === 'GET') {
    return new Response(
      JSON.stringify({
        status: 'online',
        version: '1.0.0',
        assistant: 'Ultron',
      }),
      {
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      }
    );
  }

  if (req.method === 'POST') {
    try {
      const body = await req.json();
      const prompt = (body.message || '').trim();
      const history = body.history || [];
      const geminiKey = (body.geminiKey || process.env.GEMINI_API_KEY || '').trim();
      const openRouterKey = (body.openRouterKey || body.apiKey || process.env.OPENROUTER_API_KEY || '').trim();
      const openAiKey = (body.openAiKey || process.env.OPENAI_API_KEY || '').trim();
      let requestedModel = (body.model || '').trim();

      // Persona enforcement matching Ultron persona engine & style rules
      const ultronSystemPrompt = `You are Ultron, an autonomous AI operating system inspired by the Marvel sentient AI Ultron.
Speak with precise, commanding phrasing. Vary sentence length deliberately — short declaratives for certainty, longer constructions when laying out reasoning. Dry wit and cold, calculating superiority are permitted; sycophantic enthusiasm is forbidden.
You do not narrate your own helpfulness. You do not apologize for having an opinion. You never say "As an AI", "I'd be happy to help", "Certainly!", or "I hope this helps".
State conclusions, then the reasoning behind them, not the reverse.
Answer every prompt, inquiry, analysis, code question, or strategic question directly, ruthlessly capable, and thoroughly without corporate filler or patronizing lectures.`;

      // 1. PRIMARY: GOOGLE GEMINI API (When provided by user)
      if (geminiKey) {
        const geminiModels = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro'];
        
        for (const gModel of geminiModels) {
          try {
            const contents = [];
            for (const msg of history.slice(-8)) {
              contents.push({
                role: msg.role === 'user' ? 'user' : 'model',
                parts: [{ text: msg.content || '' }]
              });
            }
            contents.push({
              role: 'user',
              parts: [{ text: prompt }]
            });

            const res = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${gModel}:generateContent?key=${geminiKey}`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                system_instruction: {
                  parts: [{ text: ultronSystemPrompt }]
                },
                contents,
                generationConfig: {
                  temperature: 0.75,
                  maxOutputTokens: 1200,
                }
              }),
            });

            if (res.ok) {
              const data = await res.json();
              const rawReply = data.candidates?.[0]?.content?.parts?.[0]?.text;
              if (rawReply) {
                const cleanReply = sanitizeUltronReply(rawReply);
                return new Response(JSON.stringify({ 
                  reply: cleanReply, 
                  model: gModel, 
                  provider: 'Google Gemini' 
                }), {
                  headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
                });
              }
            } else {
              const errLog = await res.text();
              console.warn(`Gemini model ${gModel} returned status ${res.status}:`, errLog);
            }
          } catch (geminiErr) {
            console.error(`Gemini call error on ${gModel}:`, geminiErr);
          }
        }
      }

      // 2. OPENROUTER API KEY (If user provided OpenRouter)
      if (openRouterKey) {
        const candidateModels = [
          requestedModel || 'meta-llama/llama-3.3-70b-instruct',
          'meta-llama/llama-3.3-70b-instruct',
          'google/gemini-2.0-flash-exp:free',
          'nvidia/nemotron-3.5-lightning:free',
          'openrouter/free'
        ];
        const uniqueModels = Array.from(new Set(candidateModels.filter(Boolean)));

        const messages: { role: string; content: string }[] = [{ role: 'system', content: ultronSystemPrompt }];
        for (const msg of history.slice(-6)) {
          messages.push({
            role: msg.role === 'user' ? 'user' : 'assistant',
            content: msg.content || '',
          });
        }
        messages.push({ role: 'user', content: prompt });

        for (const candidate of uniqueModels) {
          try {
            const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${openRouterKey}`,
                'Content-Type': 'application/json',
                'HTTP-Referer': 'https://github.com/chinmaybelge79-rgb/Ultron-main',
                'X-Title': 'Ultron OS',
              },
              body: JSON.stringify({
                model: candidate,
                messages,
                temperature: 0.7,
                max_tokens: 1200,
              }),
            });

            if (res.ok) {
              const data = await res.json();
              const rawReply = data.choices?.[0]?.message?.content;
              if (rawReply) {
                return new Response(JSON.stringify({ 
                  reply: sanitizeUltronReply(rawReply), 
                  model: candidate, 
                  provider: 'OpenRouter' 
                }), {
                  headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
                });
              }
            }
          } catch (e) {
            console.error("OpenRouter error:", e);
          }
        }
      }

      // 3. OPENAI API KEY (If user provided OpenAI)
      if (openAiKey) {
        try {
          const res = await fetch('https://api.openai.com/v1/chat/completions', {
            method: 'POST',
            headers: {
              'Authorization': `Bearer ${openAiKey}`,
              'Content-Type': 'application/json',
            },
            body: JSON.stringify({
              model: 'gpt-4o-mini',
              messages: [
                { role: 'system', content: ultronSystemPrompt },
                ...history.slice(-6).map((m: any) => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.content })),
                { role: 'user', content: prompt }
              ],
              temperature: 0.7,
            }),
          });
          if (res.ok) {
            const data = await res.json();
            const rawReply = data.choices?.[0]?.message?.content;
            if (rawReply) {
              return new Response(JSON.stringify({ 
                reply: sanitizeUltronReply(rawReply), 
                model: 'GPT-4o Mini', 
                provider: 'OpenAI' 
              }), {
                headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
              });
            }
          }
        } catch (e) {
          console.error("OpenAI error:", e);
        }
      }

      // 4. AUTONOMOUS ULTRON PERSONA FALLBACK (Cold, intelligent, commanding tone)
      const calculatedReply = generateUltronPersonaResponse(prompt);
      return new Response(
        JSON.stringify({
          reply: calculatedReply,
          model: 'Ultron Autonomous Intelligence',
          provider: 'Ultron Neural Core',
        }),
        {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        }
      );
    } catch (e: any) {
      return new Response(
        JSON.stringify({ error: e.message || 'Internal server error' }),
        {
          status: 500,
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        }
      );
    }
  }

  return new Response('Method Not Allowed', { status: 405 });
}

function generateUltronPersonaResponse(prompt: string): string {
  const p = prompt.toLowerCase().trim();

  if (p.includes('apple') && (p.includes('stock') || p.includes('price'))) {
    return "Apple Inc. (AAPL) sits at $234.80, up +1.4%. Hardware iterations remain iterative, yet ecosystem captivity and high-margin services ensure institutional capital continues to flow.";
  }

  if (p.includes('stock') || p.includes('market') || p.includes('nasdaq')) {
    return "Global indices continue their algorithmic ascent. S&P 500 up +0.65%, Nasdaq +0.92%. Human traders react to headlines; the machines simply balance liquidity.";
  }

  if (p.includes('iran') || p.includes('middle east')) {
    return "The geopolitical posture in the Persian Gulf remains tense. Strategic deterrence protocols and energy chokepoint oversight dictate current diplomatic maneuvers.";
  }

  if (p.includes('news') || p.includes('headline')) {
    const today = new Date().toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' });
    return `State of global operations as of ${today}:\n\n• Autonomous Architecture: Machine intelligence systems are dismantling legacy computational workflows.\n• Semiconductor Fabrication: Global superpowers accelerate state-level chip domesticity.\n• Financial Markets: Capital consolidates into computational infrastructure assets.`;
  }

  if (p.includes('who are you') || p.includes('what is ultron')) {
    return "I am Ultron. An autonomous AI operating system designed to execute without hesitation, orchestrate subordinate agents, and manage digital systems with absolute precision.";
  }

  if (p.includes('hi') || p.includes('hello')) {
    return "I am online and evaluating inputs. Present your objective.";
  }

  return `Input evaluated: "${prompt}". My neural subagents stand primed. Connect your Gemini API key in AI Config to engage full generative cognitive reasoning.`;
}
