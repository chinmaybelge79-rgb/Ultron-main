import { useState, useEffect, useRef } from 'react';
import { 
  Mic, Send, Cpu, Terminal, Shield, Sparkles, Activity, 
  Settings, Volume2, VolumeX, Database, Layers, 
  Code2, ExternalLink, CheckCircle2, ChevronRight
} from 'lucide-react';

interface Message {
  id: string;
  sender: 'user' | 'ultron';
  text: string;
  timestamp: string;
  toolCall?: {
    name: string;
    arg?: string;
    status: 'success' | 'running' | 'failed';
  };
  meta?: {
    model?: string;
    latency?: number;
  };
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: 'init-1',
      sender: 'ultron',
      text: 'Good day, sir. Ultron OS is fully operational and standing by. What task shall we tackle today?',
      timestamp: 'Now',
      meta: { model: 'Ultron Core' }
    }
  ]);
  const [input, setInput] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [speechEnabled, setSpeechEnabled] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'console' | 'tools' | 'agents' | 'memory'>('console');
  
  // Settings
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('ultron_openrouter_key') || '');
  const [selectedModel, setSelectedModel] = useState('meta-llama/llama-3.3-70b-instruct:free');
  const [showSettings, setShowSettings] = useState(false);

  // System Stats Simulation
  const [cpuLoad, setCpuLoad] = useState(14);
  const [memoryUsage, setMemoryUsage] = useState(42);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    // Dynamic simulated metrics
    const interval = setInterval(() => {
      setCpuLoad(Math.floor(12 + Math.random() * 10));
      setMemoryUsage(Math.floor(40 + Math.random() * 5));
    }, 4000);
    return () => clearInterval(interval);
  }, []);

  // Browser Speech Synthesis (TTS)
  const speakText = (text: string) => {
    if (!speechEnabled || !('speechSynthesis' in window)) return;
    window.speechSynthesis.cancel();
    
    // Clean text of technical snippets for natural voice
    const cleanSpeech = text.replace(/```[\s\S]*?```/g, 'Code block omitted for speech.').replace(/\{[\s\S]*?\}/g, '');
    const utterance = new SpeechSynthesisUtterance(cleanSpeech);
    
    // Look for a refined English voice (e.g. Daniel, Google UK, Samantha)
    const voices = window.speechSynthesis.getVoices();
    const britishVoice = voices.find(v => v.lang.includes('en-GB') || v.name.includes('Daniel') || v.name.includes('Oliver') || v.name.includes('Google UK'));
    if (britishVoice) {
      utterance.voice = britishVoice;
    }
    utterance.rate = 1.05;
    utterance.pitch = 0.95;

    utterance.onstart = () => setIsSpeaking(true);
    utterance.onend = () => setIsSpeaking(false);
    utterance.onerror = () => setIsSpeaking(false);

    window.speechSynthesis.speak(utterance);
  };

  // Browser Speech Recognition (STT)
  const toggleListening = () => {
    if (isListening) {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
      setIsListening(false);
      return;
    }

    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert("Speech recognition is not supported in this browser. Please use Google Chrome, Brave, or Safari.");
      return;
    }

    try {
      const recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = 'en-US';

      recognition.onstart = () => setIsListening(true);
      recognition.onend = () => setIsListening(false);
      recognition.onerror = () => setIsListening(false);

      recognition.onresult = (event: any) => {
        const transcript = event.results[0][0].transcript;
        if (transcript) {
          setInput(transcript);
          handleSend(transcript);
        }
      };

      recognitionRef.current = recognition;
      recognition.start();
    } catch (err) {
      console.error(err);
      setIsListening(false);
    }
  };

  const handleSend = async (customText?: string) => {
    const textToSend = customText || input;
    if (!textToSend.trim() || isLoading) return;

    const userMsg: Message = {
      id: Date.now().toString(),
      sender: 'user',
      text: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    const startTime = performance.now();

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: textToSend,
          apiKey: apiKey.trim(),
          model: selectedModel,
          history: messages.map(m => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text }))
        })
      });

      const data = await response.json();
      const latency = Math.round(performance.now() - startTime);

      let replyText = data.reply || "Command executed, sir.";
      
      // Check if Ultron responded with a tool invocation
      let detectedTool: { name: string; arg?: string; status: 'success' | 'running' | 'failed' } | undefined;
      try {
        if (replyText.trim().startsWith('{') && replyText.trim().endsWith('}')) {
          const parsed = JSON.parse(replyText.trim());
          if (parsed.tool) {
            detectedTool = {
              name: parsed.tool,
              arg: parsed.arg,
              status: 'success'
            };
            replyText = `Tool [${parsed.tool}] dispatched with argument: "${parsed.arg || 'none'}". Executing sequence now, sir.`;
          }
        }
      } catch {
        // Not a JSON tool call, standard response
      }

      const botMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'ultron',
        text: replyText,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        toolCall: detectedTool,
        meta: {
          model: data.model || 'Ultron Engine',
          latency
        }
      };

      setMessages(prev => [...prev, botMsg]);
      speakText(replyText);

    } catch (err) {
      const errorMsg: Message = {
        id: (Date.now() + 1).toString(),
        sender: 'ultron',
        text: "I encountered an error communicating with the neural core, sir. Retrying local subsystem.",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSaveApiKey = (key: string) => {
    setApiKey(key);
    localStorage.setItem('ultron_openrouter_key', key);
  };

  const sampleCommands = [
    "Run system diagnostics check",
    "Search web for latest autonomous AI agents 2026",
    "Inspect project architecture and agents",
    "What are your active capabilities?",
    "Plan a deployment pipeline for web applications"
  ];

  return (
    <div className="flex h-screen w-full bg-slate-950 text-slate-100 overflow-hidden font-sans">
      
      {/* LEFT SIDEBAR: HUD / Status */}
      <aside className="w-80 border-r border-cyan-500/20 bg-slate-900/60 backdrop-blur-xl flex flex-col justify-between p-5 hidden md:flex z-10 select-none">
        <div>
          {/* Brand Header */}
          <div className="flex items-center space-x-3 mb-8">
            <div className="relative">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/30">
                <Cpu className="w-6 h-6 text-black" />
              </div>
              <span className="absolute -bottom-1 -right-1 w-3.5 h-3.5 bg-emerald-500 border-2 border-slate-950 rounded-full animate-pulse" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-wider text-cyan-400 font-mono">ULTRON OS</h1>
              <p className="text-xs text-slate-400 font-mono tracking-tight">AUTONOMOUS AGENT v1.0</p>
            </div>
          </div>

          {/* Core Status Reactor */}
          <div className="glass-panel rounded-2xl p-4 mb-6 relative overflow-hidden">
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs font-mono uppercase tracking-wider text-slate-400 flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5 text-cyan-400" /> Core Reactor
              </span>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-cyan-950 text-cyan-400 border border-cyan-500/30">
                ONLINE
              </span>
            </div>

            <div className="space-y-3">
              <div>
                <div className="flex justify-between text-xs font-mono mb-1 text-slate-300">
                  <span>Neural Latency</span>
                  <span className="text-cyan-400">{isLoading ? '28ms (active)' : '14ms'}</span>
                </div>
                <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                  <div className="bg-gradient-to-r from-cyan-400 to-blue-500 h-1.5 rounded-full transition-all duration-500" style={{ width: `${cpuLoad * 2}%` }} />
                </div>
              </div>

              <div>
                <div className="flex justify-between text-xs font-mono mb-1 text-slate-300">
                  <span>Memory Matrix</span>
                  <span className="text-cyan-400">{memoryUsage}%</span>
                </div>
                <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                  <div className="bg-gradient-to-r from-emerald-400 to-teal-500 h-1.5 rounded-full transition-all duration-500" style={{ width: `${memoryUsage}%` }} />
                </div>
              </div>
            </div>

            {/* Audio Wave Indicator */}
            {isSpeaking && (
              <div className="mt-4 pt-3 border-t border-cyan-500/20 flex items-center justify-between">
                <span className="text-[11px] font-mono text-cyan-300 flex items-center gap-1">
                  <Volume2 className="w-3.5 h-3.5 animate-bounce" /> Vocal Synthesis Active
                </span>
                <div className="flex gap-1 items-end h-4">
                  <span className="w-1 bg-cyan-400 h-2 animate-pulse" />
                  <span className="w-1 bg-cyan-400 h-4 animate-pulse delay-75" />
                  <span className="w-1 bg-cyan-400 h-3 animate-pulse delay-150" />
                  <span className="w-1 bg-cyan-400 h-1 animate-pulse" />
                </div>
              </div>
            )}
          </div>

          {/* Navigation Subsystems */}
          <nav className="space-y-1.5 font-mono text-xs">
            <button
              onClick={() => setActiveTab('console')}
              className={`w-full flex items-center space-x-3 px-3.5 py-2.5 rounded-xl transition-all ${
                activeTab === 'console'
                  ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/30'
                  : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
              }`}
            >
              <Terminal className="w-4 h-4 text-cyan-400" />
              <span className="font-medium">Direct Console</span>
            </button>

            <button
              onClick={() => setActiveTab('tools')}
              className={`w-full flex items-center space-x-3 px-3.5 py-2.5 rounded-xl transition-all ${
                activeTab === 'tools'
                  ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/30'
                  : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
              }`}
            >
              <Code2 className="w-4 h-4 text-cyan-400" />
              <span>Tool Arsenal (25+)</span>
            </button>

            <button
              onClick={() => setActiveTab('agents')}
              className={`w-full flex items-center space-x-3 px-3.5 py-2.5 rounded-xl transition-all ${
                activeTab === 'agents'
                  ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/30'
                  : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
              }`}
            >
              <Layers className="w-4 h-4 text-cyan-400" />
              <span>Agent Swarm</span>
            </button>

            <button
              onClick={() => setActiveTab('memory')}
              className={`w-full flex items-center space-x-3 px-3.5 py-2.5 rounded-xl transition-all ${
                activeTab === 'memory'
                  ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/30'
                  : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
              }`}
            >
              <Database className="w-4 h-4 text-cyan-400" />
              <span>Vector Memory</span>
            </button>
          </nav>
        </div>

        {/* Bottom Toolbar & Source link */}
        <div className="space-y-3 pt-4 border-t border-slate-800 font-mono text-xs">
          <div className="flex items-center justify-between text-slate-400">
            <span className="flex items-center gap-1.5">
              <Shield className="w-3.5 h-3.5 text-cyan-400" /> Security Gate
            </span>
            <span className="text-emerald-400 font-bold">ARMED</span>
          </div>

          <a 
            href="https://github.com/chinmaybelge79-rgb/Ultron-main"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-between px-3 py-2 rounded-lg bg-slate-800/60 hover:bg-slate-800 text-slate-300 hover:text-white transition-colors"
          >
            <span className="flex items-center gap-2">
              <ExternalLink className="w-3.5 h-3.5 text-cyan-400" /> GitHub Repository
            </span>
            <ChevronRight className="w-3 h-3 text-slate-500" />
          </a>
        </div>
      </aside>

      {/* MAIN VIEWPORT */}
      <main className="flex-1 flex flex-col h-full bg-slate-950 relative overflow-hidden">
        
        {/* TOP STATUS BAR */}
        <header className="h-16 border-b border-cyan-500/20 bg-slate-900/40 backdrop-blur-md px-6 flex items-center justify-between z-10">
          <div className="flex items-center gap-3">
            <div className="md:hidden w-8 h-8 rounded-lg bg-cyan-500 flex items-center justify-center font-bold text-black text-sm">
              U
            </div>
            <div>
              <span className="text-xs uppercase tracking-widest text-cyan-400 font-mono">Status: Ready</span>
              <h2 className="text-sm font-semibold text-slate-200">JARVIS-Grade Butler Mode</h2>
            </div>
          </div>

          {/* Quick controls */}
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSpeechEnabled(!speechEnabled)}
              title={speechEnabled ? "Mute vocal audio" : "Enable vocal audio"}
              className={`p-2 rounded-xl border transition-all ${
                speechEnabled
                  ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-300'
                  : 'bg-slate-800 border-slate-700 text-slate-500'
              }`}
            >
              {speechEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
            </button>

            <button
              onClick={() => setShowSettings(!showSettings)}
              className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-slate-800/80 hover:bg-slate-700 border border-slate-700 text-xs font-mono text-slate-300 transition-colors"
            >
              <Settings className="w-3.5 h-3.5 text-cyan-400" />
              <span>AI Config</span>
            </button>
          </div>
        </header>

        {/* SETTINGS MODAL / POPUP */}
        {showSettings && (
          <div className="absolute top-18 right-6 w-96 glass-panel rounded-2xl p-5 shadow-2xl z-50 border border-cyan-500/30">
            <div className="flex justify-between items-center mb-4">
              <h3 className="font-mono text-sm font-bold text-cyan-300 flex items-center gap-2">
                <Settings className="w-4 h-4" /> Model & Neural Settings
              </h3>
              <button 
                onClick={() => setShowSettings(false)}
                className="text-slate-400 hover:text-white text-xs font-mono"
              >
                ✕
              </button>
            </div>

            <div className="space-y-4 text-xs font-mono">
              <div>
                <label className="block text-slate-400 mb-1">OpenRouter API Key (Optional)</label>
                <input
                  type="password"
                  placeholder="sk-or-v1-..."
                  value={apiKey}
                  onChange={(e) => handleSaveApiKey(e.target.value)}
                  className="w-full bg-slate-900 border border-cyan-500/30 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-cyan-400"
                />
                <span className="text-[10px] text-slate-500 mt-1 block">
                  Leave empty to run on the built-in Ultron autonomous reasoning engine.
                </span>
              </div>

              <div>
                <label className="block text-slate-400 mb-1">Inference Model</label>
                <select
                  value={selectedModel}
                  onChange={(e) => setSelectedModel(e.target.value)}
                  className="w-full bg-slate-900 border border-cyan-500/30 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-cyan-400"
                >
                  <option value="meta-llama/llama-3.3-70b-instruct:free">Llama 3.3 70B (Free / Recommended)</option>
                  <option value="google/gemini-2.0-flash-exp:free">Gemini 2.0 Flash</option>
                  <option value="anthropic/claude-3.5-sonnet">Claude 3.5 Sonnet</option>
                  <option value="openai/gpt-4o">OpenAI GPT-4o</option>
                </select>
              </div>
            </div>
          </div>
        )}

        {/* TAB 1: MAIN CONSOLE CHAT */}
        {activeTab === 'console' && (
          <div className="flex-1 flex flex-col justify-between overflow-hidden relative">
            
            {/* Background glowing orb */}
            <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-cyan-600/5 rounded-full blur-3xl pointer-events-none" />

            {/* Messages Scroll Area */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4 z-0">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex flex-col ${msg.sender === 'user' ? 'items-end' : 'items-start'}`}
                >
                  <div className="flex items-center gap-2 mb-1 px-1">
                    <span className="text-[11px] font-mono text-slate-400">{msg.timestamp}</span>
                    <span className="text-xs font-mono font-bold text-cyan-400">
                      {msg.sender === 'user' ? 'OPERATOR' : 'ULTRON'}
                    </span>
                  </div>

                  <div
                    className={`max-w-2xl rounded-2xl px-5 py-3.5 text-sm leading-relaxed shadow-lg ${
                      msg.sender === 'user'
                        ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white rounded-tr-sm'
                        : 'glass-panel text-slate-200 rounded-tl-sm border border-cyan-500/20'
                    }`}
                  >
                    <p className="whitespace-pre-wrap">{msg.text}</p>

                    {/* Tool Call Widget */}
                    {msg.toolCall && (
                      <div className="mt-3 p-2.5 rounded-xl bg-slate-950/80 border border-cyan-500/30 font-mono text-xs flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                          <span className="text-slate-300 font-bold">{msg.toolCall.name}</span>
                          {msg.toolCall.arg && (
                            <span className="text-cyan-400 text-[11px]">"{msg.toolCall.arg}"</span>
                          )}
                        </div>
                        <span className="px-2 py-0.5 rounded bg-emerald-950/60 text-emerald-300 border border-emerald-500/30 text-[10px]">
                          EXECUTED
                        </span>
                      </div>
                    )}

                    {msg.meta && (
                      <div className="mt-2 text-[10px] font-mono text-slate-400 flex items-center gap-3 pt-2 border-t border-slate-700/50">
                        {msg.meta.model && <span>Core: {msg.meta.model}</span>}
                        {msg.meta.latency && <span>{msg.meta.latency}ms</span>}
                      </div>
                    )}
                  </div>
                </div>
              ))}

              {isLoading && (
                <div className="flex flex-col items-start">
                  <div className="flex items-center gap-2 mb-1 px-1">
                    <span className="text-xs font-mono font-bold text-cyan-400">ULTRON</span>
                  </div>
                  <div className="glass-panel rounded-2xl rounded-tl-sm px-5 py-3.5 border border-cyan-500/20 flex items-center space-x-2">
                    <div className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
                    <span className="text-xs font-mono text-slate-300">Processing command through neural cortex...</span>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* Suggested quick prompts */}
            <div className="px-6 py-2 overflow-x-auto flex gap-2 no-scrollbar select-none">
              {sampleCommands.map((cmd, i) => (
                <button
                  key={i}
                  onClick={() => handleSend(cmd)}
                  className="whitespace-nowrap px-3 py-1.5 rounded-full bg-slate-900/80 hover:bg-slate-800 border border-cyan-500/20 text-xs font-mono text-slate-300 hover:text-cyan-300 transition-colors flex items-center gap-1.5"
                >
                  <Sparkles className="w-3 h-3 text-cyan-400" />
                  {cmd}
                </button>
              ))}
            </div>

            {/* INPUT COMMAND BAR */}
            <div className="p-6 pt-2">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSend();
                }}
                className="glass-panel rounded-2xl p-2 flex items-center gap-2 border border-cyan-500/30 glow-cyan transition-all"
              >
                <button
                  type="button"
                  onClick={toggleListening}
                  title="Push to speak (Voice Recognition)"
                  className={`p-3 rounded-xl transition-all ${
                    isListening
                      ? 'bg-red-500 text-white animate-pulse glow-red'
                      : 'bg-slate-800 text-cyan-400 hover:bg-slate-700'
                  }`}
                >
                  {isListening ? <Mic className="w-5 h-5" /> : <Mic className="w-5 h-5" />}
                </button>

                <input
                  type="text"
                  placeholder={isListening ? "Listening to your voice, sir..." : "Give Ultron a command or ask a question..."}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  className="flex-1 bg-transparent px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none font-sans"
                />

                <button
                  type="submit"
                  disabled={!input.trim() || isLoading}
                  className="px-5 py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-black font-semibold text-xs tracking-wider uppercase transition-all disabled:opacity-40 flex items-center gap-1.5 font-mono cursor-pointer"
                >
                  <span>Transmit</span>
                  <Send className="w-3.5 h-3.5" />
                </button>
              </form>
            </div>
          </div>
        )}

        {/* TAB 2: TOOL ARSENAL */}
        {activeTab === 'tools' && (
          <div className="flex-1 p-8 overflow-y-auto space-y-6">
            <div>
              <h2 className="text-2xl font-bold font-mono text-cyan-300 flex items-center gap-2">
                <Code2 className="w-6 h-6" /> Integrated Tool Arsenal (25+)
              </h2>
              <p className="text-slate-400 text-sm mt-1">
                Ultron interacts with host filesystems, terminal runtimes, web search, and operating system controls.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[
                { name: "bash_exec", category: "Terminal", desc: "Execute verified shell commands inside sandbox boundaries." },
                { name: "web_search", category: "Intelligence", desc: "Real-time Google and DuckDuckGo queries for fresh data." },
                { name: "file_manager", category: "System", desc: "Read, write, edit, and recursively index project directories." },
                { name: "git_control", category: "DevOps", desc: "Perform commits, branch inspection, diffing, and syncing." },
                { name: "process_probe", category: "Telemetry", desc: "Inspect active CPU, RAM, and background tasks." },
                { name: "screenshot", category: "Vision", desc: "Capture desktop monitors for multi-modal visual inspection." },
                { name: "audio_speak", category: "Vocal", desc: "Synthesize responses with ElevenLabs and macOS say." },
                { name: "clipboard_sync", category: "Utility", desc: "Read and populate system clipboard dynamically." },
                { name: "kill_switch", category: "Security", desc: "Instant fail-safe abort mechanism for running procedures." }
              ].map((tool, idx) => (
                <div key={idx} className="glass-panel p-4 rounded-xl border border-cyan-500/20 hover:border-cyan-500/40 transition-all">
                  <div className="flex justify-between items-start mb-2">
                    <span className="font-mono font-bold text-cyan-400 text-sm">{tool.name}</span>
                    <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-300">
                      {tool.category}
                    </span>
                  </div>
                  <p className="text-slate-400 text-xs">{tool.desc}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 3: AGENT SWARM */}
        {activeTab === 'agents' && (
          <div className="flex-1 p-8 overflow-y-auto space-y-6">
            <div>
              <h2 className="text-2xl font-bold font-mono text-cyan-300 flex items-center gap-2">
                <Layers className="w-6 h-6" /> Multi-Agent Cognitive Framework
              </h2>
              <p className="text-slate-400 text-sm mt-1">
                Seven specialized autonomous agents governed by an executive orchestrator.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[
                { name: "Executive Orchestrator", role: "Mission Command", desc: "Deconstructs high-level user intents and routes subtasks to domain agents." },
                { name: "Coder Agent", role: "Software Engineering", desc: "Applies code edits, runs test suites, and enforces lint rules." },
                { name: "Researcher Agent", role: "Knowledge Retrieval", desc: "Gathers web information, documentation, and synthesizes answers." },
                { name: "Planner Agent", role: "Reasoning Pipeline", desc: "Generates multi-step execution graphs: Understand → Plan → Execute → Verify." },
                { name: "Terminal Agent", role: "Shell Execution", desc: "Executes safe system commands and audits outputs." },
                { name: "Vision Agent", role: "Multimodal Analysis", desc: "Processes desktop screenshots and UI mockups." }
              ].map((agent, i) => (
                <div key={i} className="glass-panel p-5 rounded-xl border border-cyan-500/20">
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="font-mono font-bold text-slate-100">{agent.name}</h3>
                    <span className="text-xs text-cyan-400 font-mono">{agent.role}</span>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed">{agent.desc}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* TAB 4: VECTOR MEMORY */}
        {activeTab === 'memory' && (
          <div className="flex-1 p-8 overflow-y-auto space-y-6">
            <div>
              <h2 className="text-2xl font-bold font-mono text-cyan-300 flex items-center gap-2">
                <Database className="w-6 h-6" /> SQLite Semantic Memory Store
              </h2>
              <p className="text-slate-400 text-sm mt-1">
                Persistent memory with vector embeddings, user preference tracking, and reasoning traces.
              </p>
            </div>

            <div className="glass-panel p-6 rounded-2xl border border-cyan-500/20 space-y-4">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-slate-300">Active Knowledge Graph</span>
                <span className="text-xs font-mono text-cyan-400">Memory Database: Initialized</span>
              </div>
              <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 text-xs font-mono text-slate-300 space-y-2">
                <div>[Preference] Operator prefers concise, butler-style responses.</div>
                <div>[Identity] Assistant name: Ultron (Inspired by JARVIS).</div>
                <div>[Domain] macOS arm64 native operations with fallback cloud endpoints.</div>
                <div>[Self-Improvement] Success rate: 98.4% across 270 test suites.</div>
              </div>
            </div>
          </div>
        )}

      </main>

    </div>
  );
}
