export const config = {
  runtime: 'edge',
};

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
        mode: 'cloud-edge-orchestrator',
        capabilities: [
          'OpenRouter / LLM cloud inference',
          '25+ system & dev tools (bash, git, research, probes)',
          'Multi-agent framework (Planner, Coder, Researcher, Terminal, Vision)',
          'Voice Synthesis & Browser Speech Recognition',
          'SQLite Semantic Vector Memory'
        ],
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
      const prompt = body.message || '';
      const history = body.history || [];
      const customKey = body.apiKey || process.env.OPENROUTER_API_KEY || '';
      const model = body.model || 'meta-llama/llama-3.3-70b-instruct:free';

      const systemPrompt =
        "You are Ultron, a highly capable, autonomous AI operating system inspired by JARVIS. " +
        "You speak with refined confidence, courtesy, wit, and precision, addressing the operator as 'sir'. " +
        "Keep your direct spoken response concise (typically 1-3 sentences) followed by well-structured details, actions, or code if requested. " +
        "You have simulated tool execution capabilities for web search, system diagnostics, task planning, and memory.";

      const messages = [{ role: 'system', content: systemPrompt }];
      for (const msg of history.slice(-8)) {
        messages.push({ role: msg.role === 'user' ? 'user' : 'assistant', content: msg.content || '' });
      }
      messages.push({ role: 'user', content: prompt });

      if (customKey) {
        const aiRes = await fetch('https://openrouter.ai/api/v1/chat/completions', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${customKey}`,
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://github.com/chinmaybelge79-rgb/Ultron-main',
            'X-Title': 'Ultron Web'
          },
          body: JSON.stringify({
            model: model,
            messages: messages,
            temperature: 0.7,
            max_tokens: 800,
          }),
        });

        if (aiRes.ok) {
          const resData = await aiRes.json();
          const reply = resData.choices?.[0]?.message?.content || 'Acknowledged, sir.';
          return new Response(
            JSON.stringify({
              reply,
              model,
              provider: 'OpenRouter Cloud',
              status: 'success'
            }),
            {
              headers: {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*',
              },
            }
          );
        }
      }

      // Local heuristic autonomous fallback
      const reply = generateAutonomousResponse(prompt);
      return new Response(
        JSON.stringify({
          reply,
          model: 'Ultron-Autonomous-Core (Simulation)',
          provider: 'Ultron Local Heuristic Engine',
          status: 'success',
          note: 'Add your OpenRouter API key in settings for unconstrained cloud LLM reasoning.'
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

function generateAutonomousResponse(prompt: string): string {
  const p = prompt.toLowerCase().trim();
  if (p.includes('who are you') || p.includes('identity')) {
    return 'I am Ultron, sir. Your autonomous AI operating system. I am equipped for natural voice interaction, multi-agent orchestration, diagnostics, and workspace operations.';
  } else if (p.includes('status') || p.includes('health') || p.includes('system') || p.includes('diagnostics')) {
    return 'All operational subsystems are nominal, sir. Multi-agent core is standing by, speech recognizer ready, and secure sandbox permissions verified.';
  } else if (p.includes('time') || p.includes('date')) {
    return `The current timestamp is ${new Date().toLocaleString()}, sir.`;
  } else if (p.includes('help') || p.includes('tools')) {
    return 'I have access to over 25 tools including bash command dispatch, git automation, code analysis, web search, system probes, and speech synthesis. What objective shall we execute today, sir?';
  } else if (p.includes('plan')) {
    return 'Execution pipeline formulated, sir: Understand intent → Formulate subagent tasks → Execute in sandbox → Verify results.';
  } else {
    return `Understood, sir. I have processed "${prompt}". Ultron reasoning core is primed. To activate live cloud intelligence with models like Claude 3.5, Gemini 2.0 Flash, or Llama 3.3, enter your OpenRouter API Key in the top navigation bar.`;
  }
}
