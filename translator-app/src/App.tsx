import { useEffect, useState, useRef } from "react";
import { listen } from "@tauri-apps/api/event";
import { Window } from "@tauri-apps/api/window";
import { Loader2, X } from "lucide-react";

export default function App() {
  const [selectedText, setSelectedText] = useState("");
  const [translation, setTranslation] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    // Listen for text-selected event from Rust backend
    const unlistenTextSelected = listen<string>("text-selected", async (event) => {
      const text = event.payload;
      if (!text || text.trim() === "") return;
      
      setSelectedText(text);
      setTranslation("");
      setError("");
      setIsLoading(true);

      // Cancel previous request if exists
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      abortControllerRef.current = new AbortController();

      try {
        // Assuming llama.cpp server is running locally on 8080
        // Change the URL if your llama.cpp runs on a different port
        const response = await fetch("http://localhost:8080/v1/chat/completions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            messages: [
              { role: "system", content: "You are a professional translator. Translate the following text into fluent Chinese. If it is already in Chinese, translate it to English. Only output the translation result, without any extra text or explanations." },
              { role: "user", content: text }
            ],
            stream: true,
          }),
          signal: abortControllerRef.current.signal,
        });

        if (!response.ok) {
          throw new Error("Failed to connect to llama.cpp server. Is it running?");
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder("utf-8");

        if (reader) {
          let done = false;
          while (!done) {
            const { value, done: readerDone } = await reader.read();
            done = readerDone;
            if (value) {
              const chunk = decoder.decode(value, { stream: true });
              const lines = chunk.split('\n').filter(line => line.trim() !== '');
              for (const line of lines) {
                if (line === 'data: [DONE]') return;
                if (line.startsWith('data: ')) {
                  try {
                    const data = JSON.parse(line.substring(6));
                    if (data.choices[0].delta?.content) {
                      setTranslation((prev) => prev + data.choices[0].delta.content);
                    }
                  } catch (e) {
                    console.error("Error parsing stream chunk", e);
                  }
                }
              }
            }
          }
        }
      } catch (err: any) {
        if (err.name !== 'AbortError') {
          setError(err.message || "An error occurred");
        }
      } finally {
        setIsLoading(false);
      }
    });

    // Listen to window blur to hide the app
    const appWindow = new Window('main');
    const unlistenBlur = appWindow.onFocusChanged(({ payload: focused }) => {
      if (!focused) {
        appWindow.hide();
      }
    });

    return () => {
      unlistenTextSelected.then((f) => f());
      unlistenBlur.then((f) => f());
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  const closeWindow = () => {
    const appWindow = new Window('main');
    appWindow.hide();
  };

  return (
    <div className="w-full h-screen bg-gray-900/95 text-white rounded-xl shadow-2xl border border-gray-700 flex flex-col overflow-hidden backdrop-blur-md">
      {/* Header (Drag area) */}
      <div 
        data-tauri-drag-region 
        className="h-10 bg-gray-800/50 flex items-center justify-between px-4 cursor-move border-b border-gray-700/50"
      >
        <span className="text-xs font-semibold text-gray-400 select-none pointer-events-none">
          AI Translator (llama.cpp)
        </span>
        <button 
          onClick={closeWindow}
          className="text-gray-400 hover:text-white hover:bg-gray-700 rounded-md p-1 transition-colors"
        >
          <X size={16} />
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 p-5 overflow-y-auto custom-scrollbar flex flex-col gap-4">
        {selectedText ? (
          <>
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Original</span>
              <p className="text-sm text-gray-300 leading-relaxed border-l-2 border-blue-500/30 pl-3">
                {selectedText}
              </p>
            </div>

            <div className="h-px bg-gray-700/50 w-full rounded-full" />

            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">Translation</span>
                {isLoading && <Loader2 size={12} className="animate-spin text-blue-400" />}
              </div>
              
              {error ? (
                <div className="text-sm text-red-400 bg-red-950/30 p-3 rounded-lg border border-red-900/50">
                  {error}
                </div>
              ) : (
                <p className="text-sm text-white leading-relaxed">
                  {translation}
                  {isLoading && <span className="inline-block w-1.5 h-4 ml-1 bg-blue-500 animate-pulse align-middle" />}
                </p>
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-center opacity-50 select-none">
            <p className="text-sm">Select any text and press</p>
            <kbd className="mt-2 px-2 py-1 bg-gray-800 rounded-md text-xs font-mono border border-gray-700 text-blue-400">Ctrl + Y</kbd>
          </div>
        )}
      </div>
    </div>
  );
}
