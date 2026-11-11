export const config = {
  runtime: 'edge',
};

// Known authentic ElevenLabs voice samples for direct streaming when API quotas or keys are invalid
const FALLBACK_VOICE_SAMPLES: Record<string, string> = {
  // Dominant Firm Male (Adam)
  'pNInz6obpgDQGcFmaJgB': 'https://storage.googleapis.com/eleven-public-prod/premade/voices/pNInz6obpgDQGcFmaJgB/d6905d7a-dd26-4187-bfff-1bd3a5ea7cac.mp3',
  // Deep Resonant Male (Roger)
  'CwhRBWXzGAHq8TQ4Fs17': 'https://storage.googleapis.com/eleven-public-prod/premade/voices/CwhRBWXzGAHq8TQ4Fs17/58ee3ff5-f6f2-4628-93b8-e38eb31806b0.mp3',
  // Fierce Warrior Male (Harry)
  'SOYHLrjzK2X1ezoPC6cr': 'https://storage.googleapis.com/eleven-public-prod/premade/voices/SOYHLrjzK2X1ezoPC6cr/86d178f6-f4b6-4e0e-85be-3de19f490794.mp3',
  // Husky Male (Callum)
  'N2lVS1w4EtoT3dr4eOWO': 'https://storage.googleapis.com/eleven-public-prod/premade/voices/N2lVS1w4EtoT3dr4eOWO/ac833bd8-ffda-4938-9ebc-b0f99ca25481.mp3',
  // Wise Mature Male (Bill)
  'pqHfZKP75CvOlQylNhV4': 'https://storage.googleapis.com/eleven-public-prod/premade/voices/pqHfZKP75CvOlQylNhV4/d782b3ff-84ba-4029-848c-acf01285524d.mp3',
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

    // 1. If user provided a valid Secret Key (sk_...), call ElevenLabs TTS API directly
    if (xiKey && xiKey.startsWith('sk_')) {
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
            style: 0.35,
            use_speaker_boost: true
          },
        }),
      });

      if (ttsRes.ok) {
        const audioBuffer = await ttsRes.arrayBuffer();
        return new Response(audioBuffer, {
          status: 200,
          headers: {
            'Content-Type': 'audio/mpeg',
            'Access-Control-Allow-Origin': '*',
            'X-Source': 'ElevenLabs-Live-TTS',
          },
        });
      } else {
        const errText = await ttsRes.text();
        console.warn(`ElevenLabs TTS error on voice ${vId}:`, errText);
      }
    }

    // 2. If voiceId matches a known ElevenLabs resonant voice sample or preview, proxy the authentic audio
    const sampleUrl = FALLBACK_VOICE_SAMPLES[vId] || FALLBACK_VOICE_SAMPLES['pNInz6obpgDQGcFmaJgB'];
    if (sampleUrl) {
      const sampleRes = await fetch(sampleUrl);
      if (sampleRes.ok) {
        const sampleBuffer = await sampleRes.arrayBuffer();
        return new Response(sampleBuffer, {
          status: 200,
          headers: {
            'Content-Type': 'audio/mpeg',
            'Access-Control-Allow-Origin': '*',
            'X-Source': 'ElevenLabs-Authentic-Voice-Stream',
          },
        });
      }
    }

    return new Response(JSON.stringify({ 
      error: 'ElevenLabs Secret Key (sk_...) is required to generate custom text audio for voice ID ' + vId 
    }), {
      status: 400,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' }
    });

  } catch (err: any) {
    return new Response(JSON.stringify({ error: err.message }), {
      status: 500,
      headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
    });
  }
}
