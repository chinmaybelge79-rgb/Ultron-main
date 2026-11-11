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

  try {
    let apiKey = '';
    const authHeader = req.headers.get('Authorization') || req.headers.get('xi-api-key');
    if (authHeader) {
      apiKey = authHeader.replace(/^Bearer\s+/i, '').trim();
    }

    if (!apiKey) {
      const url = new URL(req.url);
      apiKey = url.searchParams.get('apiKey') || '';
    }

    if (!apiKey && req.method === 'POST') {
      try {
        const body = await req.json();
        apiKey = body.apiKey || '';
      } catch {}
    }

    if (!apiKey) {
      apiKey = process.env.ELEVENLABS_API_KEY || '';
    }

    // Always fetch the live public/account ElevenLabs voices library
    const headers: Record<string, string> = {};
    if (apiKey.trim() && apiKey.trim().startsWith('sk_')) {
      headers['xi-api-key'] = apiKey.trim();
    }

    const res = await fetch('https://api.elevenlabs.io/v1/voices', { headers });

    if (res.ok) {
      const data = await res.json();
      const rawVoices = data.voices || [];
      
      const voices = rawVoices.map((v: any) => ({
        voice_id: v.voice_id,
        name: v.name,
        category: v.category || 'general',
        gender: v.labels?.gender || 'unknown',
        description: v.labels?.description || v.labels?.descriptive || v.description || '',
        preview_url: v.preview_url || '',
      }));

      return new Response(JSON.stringify({ 
        status: 'success',
        source: apiKey.trim().startsWith('sk_') ? 'ElevenLabs Account Library' : 'ElevenLabs Global Library',
        voices 
      }), {
        status: 200,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }

    // Return structured error if ElevenLabs rejected
    const errText = await res.text();
    return new Response(errText, {
      status: res.status,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
    });

  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message || 'Internal server error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
    });
  }
}
