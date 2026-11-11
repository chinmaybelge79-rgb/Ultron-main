export const config = {
  runtime: 'edge',
};

export default async function handler(req: Request) {
  if (req.method === 'OPTIONS') {
    return new Response(null, {
      status: 200,
      headers: {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      },
    });
  }

  if (req.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405 });
  }

  try {
    const { text, apiKey, voiceId } = await req.json();
    const cleanText = (text || '')
      .replace(/```[\s\S]*?```/g, '')
      .replace(/[*_#`~•]/g, '')
      .replace(/https?:\/\/\S+/g, '')
      .trim();

    if (!cleanText) {
      return new Response(JSON.stringify({ error: 'Text required' }), { status: 400 });
    }

    const xiKey = (apiKey || process.env.ELEVENLABS_API_KEY || '').trim();
    const vId = (voiceId || 'gBUMIvE4QAMyPIru0aFd').trim();

    if (!xiKey) {
      return new Response(JSON.stringify({ error: 'API key required' }), { status: 400 });
    }

    // Call ElevenLabs with the specific voice ID provided by the user
    const ttsRes = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${vId}`, {
      method: 'POST',
      headers: {
        'xi-api-key': xiKey,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        text: cleanText.slice(0, 800),
        model_id: 'eleven_multilingual_v2',
        voice_settings: {
          stability: 0.45,
          similarity_boost: 0.85,
          style: 0.2,
          use_speaker_boost: true
        },
      }),
    });

    if (!ttsRes.ok) {
      const errText = await ttsRes.text();
      return new Response(errText, {
        status: ttsRes.status,
        headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
      });
    }

    const audioBuffer = await ttsRes.arrayBuffer();
    return new Response(audioBuffer, {
      status: 200,
      headers: {
        'Content-Type': 'audio/mpeg',
        'Access-Control-Allow-Origin': '*',
      },
    });
  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }
}
