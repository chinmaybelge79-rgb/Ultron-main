import React, { useState, useEffect, useRef } from 'react';
import { 
  Mic, MicOff, Send, Sliders, Bell, Copy, ThumbsUp, ThumbsDown, 
  RotateCcw, Zap, Play, Square, ChevronDown, ChevronRight, Check,
  Activity, Shield, Settings, Folder, Database, Wrench, Layers, MessageSquare,
  Globe, Volume2, Key, Info
} from 'lucide-react';

interface Message {
  id: string;
  sender: 'user' | 'ultron';
  text: string;
  time: string;
  sources?: string[];
  provider?: string;
  model?: string;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'm1',
      sender: 'user',
      text: "hi whats today's news",
      time: '03:25 AM'
    },
    {
      id: 'm2',
      sender: 'ultron',
      text: "Global operations state:\n\n• Autonomous Architecture: Machine intelligence continues to dismantle manual computational frameworks.\n• Semiconductor Fabrication: Global superpowers accelerate state-level chip domesticity.\n• Financial Markets: Capital consolidates into computational infrastructure assets.",
      time: '03:25 AM',
      sources: ['Reuters', 'Bloomberg', 'Financial Times', '+2 more']
    }
  ]);
  const [input, setInput] = useState('');
  const [activeNav, setActiveNav] = useState('Chat');
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [showConfig, setShowConfig] = useState(false);
  const activeModel = 'Google Gemini (Auto-Discovered)';

  // Multi-Key API configuration
  const [geminiKey, setGeminiKey] = useState(() => localStorage.getItem('ultron_gemini_key') || '');
  const [openRouterKey, setOpenRouterKey] = useState(() => localStorage.getItem('ultron_openrouter_key') || '');
  const [openAiKey] = useState(() => localStorage.getItem('ultron_openai_key') || '');
  const [elevenLabsKey, setElevenLabsKey] = useState(() => localStorage.getItem('ultron_elevenlabs_key') || '');
  const [voiceId, setVoiceId] = useState(() => localStorage.getItem('ultron_voice_id') || 'gBUMIvE4QAMyPIru0aFd');
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [ttsError, setTtsError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Save settings with confirmation
  const handleSaveConfig = (e: React.FormEvent) => {
    e.preventDefault();
    localStorage.setItem('ultron_gemini_key', geminiKey.trim());
    localStorage.setItem('ultron_openrouter_key', openRouterKey.trim());
    localStorage.setItem('ultron_openai_key', openAiKey.trim());
    localStorage.setItem('ultron_elevenlabs_key', elevenLabsKey.trim());
    localStorage.setItem('ultron_voice_id', voiceId.trim());
    setSaveSuccess(true);
    setTimeout(() => {
      setSaveSuccess(false);
      setShowConfig(false);
    }, 700);
  };

  // Ultra-Deep Male Vocal Output (ElevenLabs with dynamic validation)
  const speakText = async (textToSpeak: string) => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }

    const clean = textToSpeak
      .replace(/```[\s\S]*?```/g, '')
      .replace(/[*_#`~•]/g, '')
      .replace(/https?:\/\/\S+/g, '')
      .trim();

    if (!clean) return;

    // Call ElevenLabs endpoint if a key is entered
    if (elevenLabsKey.trim()) {
      try {
        setIsSpeaking(true);
        const res = await fetch('/api/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: clean,
            apiKey: elevenLabsKey.trim(),
            voiceId: voiceId.trim() || 'gBUMIvE4QAMyPIru0aFd',
          }),
        });

        if (res.ok) {
          setTtsError(null);
          const blob = await res.blob();
          const audioUrl = URL.createObjectURL(blob);
          const audio = new Audio(audioUrl);
          currentAudioRef.current = audio;
          audio.onended = () => {
            setIsSpeaking(false);
            currentAudioRef.current = null;
          };
          audio.onerror = () => {
            fallbackWebSpeech(clean);
          };
          await audio.play();
          return;
        } else {
          const errData = await res.text();
          console.warn("ElevenLabs API returned error:", errData);
          if (errData.includes('api_key_id_used_as_api_key')) {
            setTtsError("Note: That was an ElevenLabs Key ID. Paste your Secret Key (starts with sk_)");
          }
        }
      } catch (e) {
        console.warn("ElevenLabs audio streaming fallback:", e);
      }
    }

    // Always fallback to ultra-deep male voice in browser
    fallbackWebSpeech(clean);
  };

  const fallbackWebSpeech = (text: string) => {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) return;
    const utterance = new SpeechSynthesisUtterance(text);
    const voices = window.speechSynthesis.getVoices();
    // Locate the deepest male resonant voice
    const deepVoice = voices.find(v => {
      const n = v.name.toLowerCase();
      return n.includes('daniel') || n.includes('george') || n.includes('oliver') || n.includes('david') || (n.includes('male') && v.lang.startsWith('en'));
    }) || voices[0];

    if (deepVoice) utterance.voice = deepVoice;
    utterance.pitch = 0.35; // Extra deep sinister Ultron pitch
    utterance.rate = 0.90;  // Cold, deliberate, calculating pace
    utterance.onstart = () => setIsSpeaking(true);
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);
    window.speechSynthesis.speak(utterance);
  };

  const stopSpeaking = () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    setIsSpeaking(false);
  };

  // Push-to-Talk Mic
  const toggleListening = async () => {
    if (isListening) {
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch {}
      }
      setIsListening(false);
      return;
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Speech recognition is not supported in this browser. Please use Chrome, Safari, or Edge.");
      return;
    }

    try {
      if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach(t => t.stop());
      }
    } catch {
      alert("Microphone permission denied. Please allow microphone access in your browser settings.");
      return;
    }

    try {
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch {}
      }

      const rec = new SpeechRecognition();
      rec.continuous = false;
      rec.interimResults = false;
      rec.lang = 'en-US';

      rec.onstart = () => setIsListening(true);
      rec.onresult = (evt: any) => {
        const transcript = evt.results?.[0]?.[0]?.transcript;
        if (transcript) {
          setInput(transcript);
          setIsListening(false);
          handleSend(transcript);
        }
      };
      rec.onerror = () => setIsListening(false);
      rec.onend = () => setIsListening(false);

      recognitionRef.current = rec;
      rec.start();
    } catch {
      setIsListening(false);
    }
  };

  const handleSend = async (customText?: string) => {
    const textToSend = customText || input;
    if (!textToSend.trim() || isLoading) return;

    const currentTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    const userMsg: Message = {
      id: Date.now().toString(),
      sender: 'user',
      text: textToSend,
      time: currentTime
    };

    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: textToSend,
          geminiKey: geminiKey.trim(),
          openRouterKey: openRouterKey.trim(),
          openAiKey: openAiKey.trim(),
          model: activeModel,
          history: messages.map(m => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text }))
        })
      });

      const data = await res.json();
      const reply = data.reply || "Evaluation concluded.";

      const botMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'ultron',
        text: reply,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        sources: textToSend.toLowerCase().includes('news') ? ['Reuters', 'Bloomberg', 'Financial Times', '+2 more'] : undefined,
        provider: data.provider,
        model: data.model
      };

      setMessages(prev => [...prev, botMsg]);
      speakText(reply);

    } catch {
      const errMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'ultron',
        text: "System communication fault. Core offline.",
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages(prev => [...prev, errMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const quickPills = [
    { label: "Execute Tasks", sub: "Autonomous workflows", icon: Zap },
    { label: "Use Tools", sub: "25+ integrations", icon: Wrench },
    { label: "Run Agents", sub: "Multi-agent system", icon: Layers },
    { label: "Live Intelligence", sub: "Real-time, web & data", icon: Globe },
  ];

  return (
    <div className="flex h-screen w-full bg-[#fbfbfd] text-slate-800 font-sans select-none overflow-hidden">
      
      {/* 1. LEFT SIDEBAR */}
      <aside className="w-64 border-r border-slate-200/80 bg-white flex flex-col justify-between p-5 z-20 shrink-0">
        <div>
          {/* macOS window traffic lights */}
          <div className="flex items-center space-x-2 mb-6">
            <span className="w-3 h-3 rounded-full bg-[#ff5f56] inline-block cursor-pointer" />
            <span className="w-3 h-3 rounded-full bg-[#ffbd2e] inline-block cursor-pointer" />
            <span className="w-3 h-3 rounded-full bg-[#27c93f] inline-block cursor-pointer" />
          </div>

          {/* Logo Brand Header */}
          <div className="flex items-center space-x-3 mb-8">
            <div className="w-9 h-9 rounded-xl bg-slate-900 flex items-center justify-center text-white font-bold text-lg shadow-sm">
              <span className="font-mono tracking-tighter">U</span>
            </div>
            <div>
              <h1 className="text-sm font-semibold text-slate-900 tracking-tight">Ultron OS</h1>
              <p className="text-[11px] text-slate-400">Autonomous Agent v1.0</p>
            </div>
          </div>

          {/* Main Navigation */}
          <nav className="space-y-1">
            {[
              { id: 'Chat', icon: MessageSquare },
              { id: 'Agents', icon: Layers },
              { id: 'Tools', icon: Wrench },
              { id: 'Memory', icon: Database },
              { id: 'Projects', icon: Folder },
            ].map(item => {
              const Icon = item.icon;
              const isActive = activeNav === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => setActiveNav(item.id)}
                  className={`w-full flex items-center space-x-3 px-3.5 py-2.5 rounded-xl text-xs font-medium transition-all ${
                    isActive 
                      ? 'bg-slate-100/90 text-slate-900 font-semibold' 
                      : 'text-slate-500 hover:text-slate-900 hover:bg-slate-50'
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? 'text-slate-900' : 'text-slate-400'}`} />
                  <span>{item.id}</span>
                </button>
              );
            })}
          </nav>
        </div>

        {/* System Status Footer */}
        <div className="pt-4 border-t border-slate-100 text-[11px] space-y-2.5">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 px-1 mb-1">
            System
          </div>
          <div className="flex items-center justify-between px-1 text-slate-600">
            <span className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" /> Core Reactor
            </span>
            <span className="text-slate-400">Online</span>
          </div>

          <div className="flex items-center justify-between px-1 text-slate-600">
            <span className="flex items-center gap-2">
              <Shield className="w-3.5 h-3.5 text-slate-400" /> Security Gate
            </span>
            <span className="text-slate-400">Armed</span>
          </div>

          <button 
            onClick={() => setShowConfig(true)}
            className="w-full flex items-center space-x-2 px-1 py-1 text-slate-600 hover:text-slate-900 transition-colors cursor-pointer"
          >
            <Settings className="w-3.5 h-3.5 text-slate-400" />
            <span>Settings</span>
          </button>
        </div>
      </aside>

      {/* 2. CENTER STAGE (Main Viewport) */}
      <main className="flex-1 flex flex-col h-full bg-[#fbfbfd] relative overflow-hidden">
        
        {/* Top Header Bar */}
        <header className="h-16 px-8 flex items-center justify-between border-b border-slate-200/50 bg-[#fbfbfd]/80 backdrop-blur-sm z-10">
          <div className="flex items-center space-x-1.5 cursor-pointer">
            <span className="font-semibold text-slate-900 text-sm tracking-tight">Ultron</span>
            <ChevronDown className="w-4 h-4 text-slate-400" />
          </div>

          <div className="flex items-center space-x-3">
            <button className="p-2 rounded-full hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors">
              <Bell className="w-4 h-4" />
            </button>

            <button
              onClick={() => setShowConfig(true)}
              className="flex items-center space-x-2 px-3 py-1.5 rounded-full bg-white border border-slate-200 text-xs font-medium text-slate-700 hover:bg-slate-50 transition-colors shadow-xs cursor-pointer"
            >
              <Sliders className="w-3.5 h-3.5 text-slate-500" />
              <span>AI Config</span>
            </button>

            <div className="w-8 h-8 rounded-full bg-slate-200/80 flex items-center justify-center text-xs font-semibold text-slate-700">
              C
            </div>
          </div>
        </header>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto px-8 py-6 flex flex-col justify-between">
          
          <div className="max-w-3xl mx-auto w-full space-y-8">
            
            {/* Center Ultron Logo & Welcome Title */}
            <div className="text-center pt-2 pb-2">
              <div className="w-14 h-14 mx-auto mb-4 rounded-2xl bg-gradient-to-b from-slate-900 to-slate-800 flex items-center justify-center shadow-md">
                <span className="text-white text-2xl font-bold font-mono">U</span>
              </div>
              <h2 className="text-3xl font-bold tracking-tight text-slate-900 mb-1">
                Hello, I'm Ultron.
              </h2>
              <p className="text-sm text-slate-400 font-normal">
                Your autonomous AI operating system.
              </p>
            </div>

            {/* 4 Quick Pills Card Row */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {quickPills.map((pill, idx) => {
                const Icon = pill.icon;
                return (
                  <button
                    key={idx}
                    onClick={() => handleSend(pill.label)}
                    className="p-3.5 rounded-2xl bg-white border border-slate-200/80 hover:border-slate-300 hover:shadow-xs transition-all text-left group cursor-pointer"
                  >
                    <Icon className="w-4 h-4 text-slate-700 mb-2 group-hover:scale-105 transition-transform" />
                    <div className="text-xs font-semibold text-slate-900 leading-tight">
                      {pill.label}
                    </div>
                    <div className="text-[10px] text-slate-400 mt-0.5">
                      {pill.sub}
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Conversation Flow */}
            <div className="space-y-5 pt-4">
              {messages.map(msg => (
                <div key={msg.id} className="space-y-1">
                  {msg.sender === 'user' ? (
                    <div className="flex flex-col items-end">
                      <span className="text-[10px] text-slate-400 pr-1 mb-1">{msg.time}</span>
                      <div className="flex items-center space-x-2">
                        <div className="px-4 py-2.5 rounded-2xl bg-slate-100 text-slate-800 text-xs font-medium">
                          {msg.text}
                        </div>
                        <div className="w-6 h-6 rounded-full bg-slate-200 flex items-center justify-center text-[10px] font-semibold text-slate-700">
                          C
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-start space-x-3 max-w-2xl">
                      <div className="w-7 h-7 rounded-lg bg-slate-900 flex items-center justify-center text-white text-xs font-bold shrink-0 mt-0.5">
                        U
                      </div>
                      <div className="flex-1 space-y-2">
                        <div className="flex items-center space-x-2">
                          <span className="text-xs font-semibold text-slate-900">Ultron</span>
                          <span className="text-[10px] text-slate-400">• {msg.time}</span>
                          {msg.provider && (
                            <span className="text-[9px] px-1.5 py-0.2 rounded bg-slate-100 text-slate-600 font-mono">
                              {msg.provider}
                            </span>
                          )}
                        </div>

                        <div className="p-4 rounded-2xl bg-white border border-slate-200/80 shadow-xs text-xs text-slate-700 leading-relaxed whitespace-pre-wrap">
                          {msg.text}

                          {/* Sources Pills */}
                          {msg.sources && (
                            <div className="mt-4 pt-3 border-t border-slate-100 flex flex-wrap gap-2 items-center">
                              {msg.sources.map((src, i) => (
                                <span
                                  key={i}
                                  className="px-2 py-0.5 rounded-md bg-slate-50 border border-slate-200 text-[10px] text-slate-600 font-medium cursor-pointer hover:bg-slate-100"
                                >
                                  {src}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>

                        {/* Action Toolbar */}
                        <div className="flex items-center space-x-3 text-slate-400 pl-1 text-xs">
                          <button 
                            onClick={() => navigator.clipboard.writeText(msg.text)}
                            title="Copy response" 
                            className="hover:text-slate-600 p-1 cursor-pointer"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </button>
                          <button title="Helpful" className="hover:text-slate-600 p-1 cursor-pointer">
                            <ThumbsUp className="w-3.5 h-3.5" />
                          </button>
                          <button title="Not helpful" className="hover:text-slate-600 p-1 cursor-pointer">
                            <ThumbsDown className="w-3.5 h-3.5" />
                          </button>
                          <button 
                            onClick={() => handleSend(messages[messages.length - 2]?.text || "Retry")}
                            title="Regenerate" 
                            className="hover:text-slate-600 p-1 cursor-pointer"
                          >
                            <RotateCcw className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ))}

              {isLoading && (
                <div className="flex items-center space-x-3 text-xs text-slate-400 pl-2">
                  <div className="w-2 h-2 rounded-full bg-slate-800 animate-ping" />
                  <span>Ultron thinking...</span>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

          </div>

          {/* Bottom Command Bar */}
          <div className="max-w-3xl mx-auto w-full pt-4">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                handleSend();
              }}
              className="flex items-center bg-white rounded-2xl border border-slate-200/90 shadow-sm px-3 py-2 space-x-3 focus-within:border-slate-400 transition-all"
            >
              {/* Functional Mic Button */}
              <button
                type="button"
                onClick={toggleListening}
                title={isListening ? "Listening... click to send" : "Click to speak"}
                className={`p-2 rounded-xl transition-all cursor-pointer ${
                  isListening
                    ? 'bg-red-500 text-white animate-pulse'
                    : 'text-slate-400 hover:text-slate-700 hover:bg-slate-50'
                }`}
              >
                {isListening ? <MicOff className="w-4 h-4 text-white" /> : <Mic className="w-4 h-4" />}
              </button>

              <input
                type="text"
                placeholder={isListening ? "Listening to your voice..." : "Ask Ultron anything..."}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                className="flex-1 bg-transparent text-xs text-slate-800 placeholder-slate-400 focus:outline-none"
              />

              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="w-8 h-8 rounded-xl bg-slate-900 hover:bg-slate-800 disabled:opacity-30 text-white flex items-center justify-center transition-all cursor-pointer shrink-0"
              >
                <Send className="w-3.5 h-3.5" />
              </button>
            </form>
          </div>

        </div>
      </main>

      {/* 3. RIGHT SIDEBAR - Shows ElevenLabs Ultron & Live Provider Keys */}
      <aside className="w-72 border-l border-slate-200/80 bg-white p-5 flex flex-col space-y-5 z-20 shrink-0">
        
        {/* Core Reactor Card */}
        <div className="p-4 rounded-2xl bg-white border border-slate-200/80 shadow-xs space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2 text-xs font-semibold text-slate-900">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span>Core Reactor</span>
            </div>
            <span className="text-[10px] text-emerald-600 font-medium">Online</span>
          </div>

          <div className="space-y-2 text-[11px]">
            <div className="flex items-center justify-between text-slate-500">
              <span>CPU</span>
              <div className="flex items-center space-x-2">
                <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div className="w-2.5 h-full bg-slate-900 rounded-full" />
                </div>
                <span className="text-slate-700 font-mono text-[10px]">14%</span>
              </div>
            </div>

            <div className="flex items-center justify-between text-slate-500">
              <span>Memory</span>
              <div className="flex items-center space-x-2">
                <div className="w-16 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                  <div className="w-6 h-full bg-slate-900 rounded-full" />
                </div>
                <span className="text-slate-700 font-mono text-[10px]">37%</span>
              </div>
            </div>

            <div className="flex items-center justify-between text-slate-500">
              <span>Latency</span>
              <span className="text-slate-700 font-mono text-[10px]">14 ms</span>
            </div>
          </div>
        </div>

        {/* Active AI Intelligence Card (Shows current Key status) */}
        <div 
          onClick={() => setShowConfig(true)}
          className="p-3.5 rounded-2xl bg-white border border-slate-200/80 shadow-xs cursor-pointer hover:border-slate-300 transition-all space-y-2"
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Key className="w-3.5 h-3.5 text-slate-700" />
              <span className="text-xs font-semibold text-slate-900">AI Intelligence Core</span>
            </div>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 font-medium border border-emerald-200">
              {geminiKey ? "Gemini Key Set" : openRouterKey ? "OpenRouter" : "Unbounded Core"}
            </span>
          </div>
          <p className="text-[10px] text-slate-400 leading-tight">
            {geminiKey ? "Auto-discovering all Gemini models on your key." : "Click to connect your Gemini API key."}
          </p>
        </div>

        {/* ElevenLabs Ultron Voice Card (Requested by user) */}
        <div className="p-3.5 rounded-2xl bg-white border border-slate-200/80 shadow-xs space-y-2.5">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2">
              <Volume2 className="w-3.5 h-3.5 text-slate-700" />
              <span className="text-xs font-semibold text-slate-900">ElevenLabs Ultron</span>
            </div>
            <span className={`text-[9px] px-2 py-0.5 rounded-full font-mono ${
              elevenLabsKey ? 'bg-indigo-50 text-indigo-700 border border-indigo-200' : 'bg-slate-100 text-slate-500'
            }`}>
              {voiceId.slice(0, 8)}...
            </span>
          </div>

          <div className="flex items-center justify-between text-[11px] text-slate-500 pt-1 border-t border-slate-100">
            <span>Voice: Ultra-Deep Baritone</span>
            <button
              onClick={() => {
                if (isSpeaking) {
                  stopSpeaking();
                } else {
                  speakText("I am Ultron. Your autonomous operating system.");
                }
              }}
              className="w-6 h-6 rounded-full bg-slate-900 hover:bg-slate-800 flex items-center justify-center text-white transition-all cursor-pointer shadow-xs"
              title="Test Voice"
            >
              {isSpeaking ? <Square className="w-2.5 h-2.5 text-red-400 fill-red-400" /> : <Play className="w-2.5 h-2.5 ml-0.5" />}
            </button>
          </div>

          {ttsError && (
            <p className="text-[9px] text-amber-600 bg-amber-50 p-1.5 rounded-lg border border-amber-200 leading-tight">
              {ttsError}
            </p>
          )}
        </div>

        {/* Quick Actions List */}
        <div className="space-y-2.5">
          <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-900 px-1">
            <Zap className="w-3.5 h-3.5 text-slate-700" />
            <span>Quick Actions</span>
          </div>

          <div className="space-y-1.5">
            {[
              { label: "Run Diagnostics", icon: Activity, cmd: "Run system diagnostics" },
              { label: "Inspect Agents", icon: Layers, cmd: "Inspect all active agents" },
              { label: "System Health", icon: Shield, cmd: "Check system health and latency" },
              { label: "Open Tool Arsenal", icon: Wrench, cmd: "List all 25+ integrated tools" },
            ].map((action, idx) => {
              const ActionIcon = action.icon;
              return (
                <button
                  key={idx}
                  onClick={() => handleSend(action.cmd)}
                  className="w-full flex items-center justify-between p-2.5 rounded-xl bg-white border border-slate-200/80 hover:border-slate-300 hover:bg-slate-50/50 text-xs text-slate-700 transition-all text-left cursor-pointer"
                >
                  <div className="flex items-center space-x-2.5">
                    <ActionIcon className="w-3.5 h-3.5 text-slate-400" />
                    <span>{action.label}</span>
                  </div>
                  <ChevronRight className="w-3.5 h-3.5 text-slate-400" />
                </button>
              );
            })}
          </div>
        </div>

      </aside>

      {/* 4. AI CONFIG MODAL */}
      {showConfig && (
        <div className="fixed inset-0 bg-slate-900/30 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-3xl border border-slate-200 shadow-2xl max-w-lg w-full p-6 space-y-5 animate-in fade-in zoom-in-95 duration-150">
            
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div>
                <h3 className="text-base font-semibold text-slate-900">AI Configuration & Keys</h3>
                <p className="text-xs text-slate-400 mt-0.5">Use your Gemini API key and ElevenLabs Ultron voice</p>
              </div>
              <button
                onClick={() => setShowConfig(false)}
                className="text-slate-400 hover:text-slate-600 text-sm font-semibold p-1 cursor-pointer"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveConfig} className="space-y-4 text-xs">
              
              {/* Google Gemini API Key */}
              <div>
                <label className="block text-slate-700 font-medium mb-1">
                  Google Gemini API Key <span className="text-emerald-600 font-semibold">(Primary - Unbounded Models)</span>
                </label>
                <input
                  type="password"
                  placeholder="AIzaSy..."
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 focus:bg-white focus:border-slate-900 focus:outline-none transition-all font-mono text-xs"
                />
                <span className="text-[10px] text-slate-400 mt-1 block">
                  Ultron will auto-discover and use all available models on your key.
                </span>
              </div>

              {/* ElevenLabs API Key */}
              <div className="pt-2 border-t border-slate-100">
                <label className="block text-slate-700 font-medium mb-1">
                  ElevenLabs API Key <span className="text-slate-400 font-normal">(Voice key)</span>
                </label>
                <input
                  type="password"
                  placeholder="Paste your ElevenLabs API Key..."
                  value={elevenLabsKey}
                  onChange={(e) => setElevenLabsKey(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 focus:bg-white focus:border-slate-900 focus:outline-none transition-all font-mono text-xs"
                />
                <div className="mt-1 flex items-start space-x-1 text-[10px] text-slate-500">
                  <Info className="w-3 h-3 text-slate-400 shrink-0 mt-0.5" />
                  <span>
                    Note: If you copied an ID like <code>713f57a0...</code>, generate or copy the secret key (starts with <code>sk_...</code>) in ElevenLabs Profile → API Keys.
                  </span>
                </div>
              </div>

              {/* ElevenLabs Voice ID */}
              <div>
                <label className="block text-slate-700 font-medium mb-1">
                  ElevenLabs Voice ID <span className="text-indigo-600 font-semibold">(Ultron Deep Voice)</span>
                </label>
                <input
                  type="text"
                  placeholder="gBUMIvE4QAMyPIru0aFd"
                  value={voiceId}
                  onChange={(e) => setVoiceId(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 focus:bg-white focus:border-slate-900 focus:outline-none transition-all font-mono text-xs"
                />
              </div>

              {/* OpenRouter API Key (Optional) */}
              <div className="pt-2 border-t border-slate-100">
                <label className="block text-slate-700 font-medium mb-1">
                  OpenRouter API Key <span className="text-slate-400 font-normal">(Optional)</span>
                </label>
                <input
                  type="password"
                  placeholder="sk-or-v1-..."
                  value={openRouterKey}
                  onChange={(e) => setOpenRouterKey(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-50 border border-slate-200 focus:bg-white focus:border-slate-900 focus:outline-none transition-all font-mono text-xs"
                />
              </div>

              {/* Submit / Continue Button */}
              <div className="pt-3 flex items-center justify-end space-x-2">
                <button
                  type="button"
                  onClick={() => setShowConfig(false)}
                  className="px-4 py-2 rounded-xl border border-slate-200 text-slate-600 hover:bg-slate-50 font-medium text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 rounded-xl bg-slate-900 hover:bg-slate-800 text-white font-medium text-xs transition-all flex items-center space-x-1.5 shadow-sm cursor-pointer"
                >
                  {saveSuccess ? (
                    <>
                      <Check className="w-3.5 h-3.5" />
                      <span>Saved & Active</span>
                    </>
                  ) : (
                    <span>Save & Continue</span>
                  )}
                </button>
              </div>

            </form>
          </div>
        </div>
      )}

    </div>
  );
}
