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
    
    // Check Authorization header, query parameter, or POST body
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

    if (!apiKey.trim()) {
      return new Response(JSON.stringify({ error: 'ElevenLabs API key is required to fetch voices' }), {
        status: 400,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }

    // Call ElevenLabs API to fetch all voices available for this key
    const res = await fetch('https://api.elevenlabs.io/v1/voices', {
      headers: {
        'xi-api-key': apiKey.trim(),
      },
    });

    if (!res.ok) {
      const errText = await res.text();
      return new Response(errText, {
        status: res.status,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
      });
    }

    const data = await res.json();
    const voices = (data.voices || []).map((v: any) => ({
      voice_id: v.voice_id,
      name: v.name,
      category: v.category || 'general',
      description: v.labels?.description || v.labels?.accent || '',
      preview_url: v.preview_url || '',
    }));

    return new Response(JSON.stringify({ voices }), {
      status: 200,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
    });

  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message || 'Internal server error' }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
    });
  }
}
