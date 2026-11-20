import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Mic, Plus, SendHorizontal, Square } from "lucide-react";
import { api, type Chat, type ChatMessage } from "../lib/api";
import { useAuth } from "../App";
import Markdown from "../components/Markdown";
import { Skeleton } from "../components/Skeleton";
import { draftKeys, readDraft, writeDraft } from "../lib/drafts";
import { useUi } from "../shell/ui";

/**
 * The troubleshooting assistant (Hilfe → Assistent).
 *
 * The unsent input is kept per conversation in sessionStorage (lib/drafts.ts), in both UIs: typing a
 * question, looking something up on another page and coming back must not lose it.
 *
 * New UI (`useUi().calm`): the open conversation is in the URL (`/assistent/:chatId`), so Back and
 * reload land in the same one; `/assistent` opens the latest. Old UI: selection stays in component
 * state as before (a `/assistent/:chatId` link still opens that conversation there).
 */

const SUGGESTIONS = [
  "Das Internet ist weg — was soll ich prüfen?",
  "Der Drucker taucht nicht mehr auf.",
  "Welche Geräte laufen gerade auf dem Server?",
  "Erkläre mir, was mein Router eigentlich macht.",
];

// The Web Speech API has no shared/standard TypeScript lib entry (Chrome/Edge still only expose
// it under the webkit-prefixed name) -- this is the minimal shape this component actually uses,
// not a full typing of the API.
interface SpeechRecognitionLike extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
}
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;
const SpeechRecognitionImpl: SpeechRecognitionCtor | undefined =
  (window as unknown as { SpeechRecognition?: SpeechRecognitionCtor; webkitSpeechRecognition?: SpeechRecognitionCtor })
    .SpeechRecognition ??
  (window as unknown as { SpeechRecognition?: SpeechRecognitionCtor; webkitSpeechRecognition?: SpeechRecognitionCtor })
    .webkitSpeechRecognition;

function formatMessageMeta(m: ChatMessage): string {
  const when = new Date(m.createdAt).toLocaleString("de-DE", { dateStyle: "short", timeStyle: "medium" });
  if (m.durationMs == null) return when;
  const seconds = m.durationMs / 1000;
  return `${when} · Antwort in ${seconds >= 10 ? seconds.toFixed(0) : seconds.toFixed(1)} s`;
}

/** Phone keyboards overlay the page (the layout viewport keeps its height), so the pinned composer
 *  would sit behind them. `visualViewport` says how much is covered; shell.css shrinks the chat by
 *  that much (`--keyboard-inset`) and hides the bottom bar while the keyboard is up. */
function useKeyboardInset(enabled: boolean) {
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!enabled || !viewport) return;
    const root = document.documentElement;
    const update = () => {
      const inset = Math.max(0, Math.round(window.innerHeight - viewport.height - viewport.offsetTop));
      root.style.setProperty("--keyboard-inset", `${inset}px`);
      root.classList.toggle("keyboard-open", inset > 80);
    };
    update();
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    return () => {
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
      root.style.removeProperty("--keyboard-inset");
      root.classList.remove("keyboard-open");
    };
  }, [enabled]);
}

export default function ChatPage() {
  const { calm } = useUi();
  const { isAdmin } = useAuth();
  const navigate = useNavigate();
  const { chatId: routeChatId } = useParams();
  const [chats, setChats] = useState<Chat[]>([]);
  const [chatsLoaded, setChatsLoaded] = useState(false);
  const [localChatId, setLocalChatId] = useState<string>(routeChatId ?? "");
  // New UI: the URL is the source of truth for the open conversation.
  const chatId = calm ? routeChatId ?? "" : localChatId;
  // The conversation open right now, for async callbacks: an answer that arrives after the user
  // switched to another conversation must not overwrite that one's messages.
  const openChatRef = useRef(chatId);
  openChatRef.current = chatId;
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [input, setInputState] = useState(() => readDraft(draftKeys.chatInput(chatId)) ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [toolsUsed, setToolsUsed] = useState<string[]>([]);
  const [recording, setRecording] = useState(false);
  const [llmConfigured, setLlmConfigured] = useState<boolean | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  // A conversation this page just created: it is known to be empty, and fetching its messages
  // would wipe the optimistic echo of the question being sent.
  const justCreated = useRef<string | null>(null);

  useKeyboardInset(calm);

  // Stop an in-flight recording rather than leaving the microphone open when the user navigates
  // away mid-dictation.
  useEffect(() => () => recognitionRef.current?.stop(), []);

  useEffect(() => {
    api.listChats().then((r) => {
      setChats(r.chats);
      if (!calm && !routeChatId && r.chats.length > 0) setLocalChatId(r.chats[0].id);
    }).catch((e) => setError(e.message)).finally(() => setChatsLoaded(true));
    // Loaded once per visit; `calm`/`routeChatId` only pick the initial selection.
  }, []);

  // New UI: `/assistent` opens the latest conversation; an unknown id falls back to it too.
  useEffect(() => {
    if (!calm || !chatsLoaded) return;
    if (routeChatId && chats.some((c) => c.id === routeChatId)) return;
    if (chats.length > 0) navigate(`/assistent/${chats[0].id}`, { replace: true });
    else if (routeChatId) navigate("/assistent", { replace: true });
  }, [calm, chatsLoaded, chats, routeChatId, navigate]);

  // Whether a model is configured: shown up front instead of only after the first failed send.
  useEffect(() => {
    if (!calm) return;
    api.dashboard().then((d) => setLlmConfigured(d.llmConfigured)).catch(() => setLlmConfigured(null));
  }, [calm]);

  // Each conversation has its own unsent draft.
  useEffect(() => {
    setInputState(readDraft(draftKeys.chatInput(chatId)) ?? "");
  }, [chatId]);

  const known = !calm || chats.some((c) => c.id === chatId);
  useEffect(() => {
    if (!chatId || !chatsLoaded || !known) {
      setMessages([]);
      return;
    }
    if (justCreated.current === chatId) return;
    justCreated.current = null; // switched to another conversation: the new one is no longer "fresh"
    let cancelled = false;
    setMessagesLoading(true);
    setToolsUsed([]);
    api.listMessages(chatId)
      .then((r) => { if (!cancelled) setMessages(r.messages); })
      .catch((e) => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setMessagesLoading(false); });
    return () => { cancelled = true; };
  }, [chatId, chatsLoaded, known]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  function setInput(value: string, forChat: string = chatId) {
    setInputState(value);
    writeDraft(draftKeys.chatInput(forChat), value ? value : null);
  }

  function openChat(id: string, replace = false) {
    if (calm) navigate(`/assistent/${id}`, { replace });
    else setLocalChatId(id);
  }

  async function ensureChat(): Promise<string> {
    if (chatId) return chatId;
    const { chat } = await api.createChat();
    justCreated.current = chat.id;
    setChats((c) => [chat, ...c]);
    // The first question of a brand-new conversation: `/assistent` becomes its URL (replace, so
    // Back does not land on an empty page that would only redirect again).
    openChat(chat.id, true);
    return chat.id;
  }

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError("");
    setToolsUsed([]);
    setInput("");
    // Optimistic echo so the question appears instantly; the id is replaced when the turn returns.
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`, chatId: chatId, role: "user",
      content: trimmed, createdAt: new Date().toISOString(), durationMs: null,
    };
    setMessages((current) => [...current, optimistic]);
    let id = chatId;
    try {
      id = await ensureChat();
      const response = await api.sendMessage(id, trimmed);
      const messages = await api.listMessages(id).then((r) => r.messages);
      if (openChatRef.current === id) {
        setMessages(messages);
        setToolsUsed(response.toolsUsed);
      }
      setChats(await api.listChats().then((r) => r.chats));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      if (openChatRef.current === id) setMessages((current) => current.filter((m) => m.id !== optimistic.id));
      setInput(trimmed, id);
    } finally {
      justCreated.current = null;
      setBusy(false);
    }
  }

  function toggleVoiceInput() {
    if (!SpeechRecognitionImpl) return;
    if (recording) {
      recognitionRef.current?.stop();
      return;
    }
    const recognition = new SpeechRecognitionImpl();
    recognition.lang = "de-DE";
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let transcript = "";
      for (let i = 0; i < event.results.length; i++) transcript += event.results[i][0].transcript;
      setInput(transcript);
    };
    recognition.onerror = () => setRecording(false);
    recognition.onend = () => setRecording(false);
    recognitionRef.current = recognition;
    recognition.start();
    setRecording(true);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(input);
    }
  }

  async function newChat() {
    try {
      const { chat } = await api.createChat();
      justCreated.current = chat.id;
      setChats((c) => [chat, ...c]);
      setMessages([]);
      setToolsUsed([]);
      setError("");
      openChat(chat.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  // ----------------------------------------------------------------------------------- old UI

  if (!calm) {
    return (
      <>
        <div className="page-header">
          <div>
            <h1>KI-Assistent</h1>
            <p>
              Beschreibe in eigenen Worten, was nicht funktioniert. Der Assistent kennt deine Geräte und
              kann selbst nachmessen — pingen, Ports prüfen, Internetverbindung testen.
            </p>
          </div>
          <div className="row">
            {chats.length > 0 && (
              <select style={{ width: "auto" }} value={chatId} disabled={busy} onChange={(e) => setLocalChatId(e.target.value)}>
                {chats.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
              </select>
            )}
            <button className="secondary" onClick={() => void newChat()}>Neue Unterhaltung</button>
          </div>
        </div>

        {error && <div className="notice error">{error}</div>}

        <div className="chat-layout">
          <div className="chat-scroll" ref={scrollRef}>
            {messages.length === 0 && !busy && (
              <div className="card">
                <h2>Womit kann ich helfen?</h2>
                <p className="muted">Zum Beispiel:</p>
                <div className="row">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} className="secondary small" onClick={() => void send(s)}>{s}</button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m) => (
              <div key={m.id} className={`bubble ${m.role}`}>
                {m.role === "assistant" ? <Markdown>{m.content}</Markdown> : m.content}
                <div className="bubble-meta">{formatMessageMeta(m)}</div>
              </div>
            ))}

            {busy && (
              <div className="bubble assistant">
                <span className="spinner" /> <span className="muted">Ich schaue nach…</span>
              </div>
            )}

            {!busy && toolsUsed.length > 0 && (
              <div className="tools-used">
                Dafür geprüft: {Array.from(new Set(toolsUsed)).join(", ")}
              </div>
            )}
          </div>

          <div className="chat-input">
            <textarea
              placeholder="Was funktioniert gerade nicht? (Enter zum Senden, Shift+Enter für eine neue Zeile)"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              disabled={busy}
            />
            {SpeechRecognitionImpl && (
              <button
                type="button"
                className={`secondary ${recording ? "recording" : ""}`}
                onClick={toggleVoiceInput}
                disabled={busy}
                title={recording ? "Aufnahme stoppen" : "Spracheingabe starten"}
              >
                {recording ? "⏹" : "🎤"}
              </button>
            )}
            <button onClick={() => void send(input)} disabled={busy || !input.trim()}>Senden</button>
          </div>
        </div>
      </>
    );
  }

  // ----------------------------------------------------------------------------------- new UI

  const current = chats.find((c) => c.id === chatId);
  const showSkeleton = !chatsLoaded || (messagesLoading && messages.length === 0);

  return (
    <div className="chat-calm">
      <div className="chat-bar">
        {chats.length > 0 && (
          <label className="chat-picker">
            <span className="visually-hidden">Unterhaltung wählen</span>
            <span className="chat-picker-dot" aria-hidden="true" />
            <select value={current ? chatId : ""} disabled={busy} onChange={(e) => openChat(e.target.value)}>
              {!current && <option value="" disabled>Neue Unterhaltung</option>}
              {chats.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
            </select>
          </label>
        )}
        <button type="button" className="secondary small chat-new" onClick={() => void newChat()} disabled={busy}
                aria-label="Neue Unterhaltung">
          <Plus size={16} aria-hidden="true" />
          <span className="chat-new-long">Neue Unterhaltung</span>
          <span className="chat-new-short" aria-hidden="true">Neu</span>
        </button>
      </div>

      {llmConfigured === false && (
        <div className="notice info chat-setup">
          <strong>Der Assistent ist noch nicht eingerichtet.</strong>{" "}
          {isAdmin ? (
            <>
              Hinterlege unter Einstellungen → KI-Assistent einen Anbieter und Schlüssel; danach kann er antworten.
              <div><Link to="/einstellungen" className="chat-setup-link">KI-Assistent einrichten</Link></div>
            </>
          ) : (
            <>Bitte die Person, die HomeAtlas verwaltet, einen KI-Anbieter einzurichten.</>
          )}
        </div>
      )}

      {error && <div className="notice error" role="alert">{error}</div>}

      <div className="chat-layout">
        <div className="chat-scroll" ref={scrollRef} aria-live="polite">
          {showSkeleton ? (
            <div className="chat-skeleton" role="status">
              <span className="visually-hidden">Unterhaltung wird geladen …</span>
              <Skeleton width="55%" height={40} radius={14} style={{ marginLeft: "auto" }} />
              <Skeleton width="80%" height={14} />
              <Skeleton width="70%" height={14} />
              <Skeleton width="40%" height={14} />
            </div>
          ) : messages.length === 0 && !busy ? (
            <div className="chat-empty">
              <h2>Womit kann ich helfen?</h2>
              <p className="muted">
                Beschreib in eigenen Worten, was nicht funktioniert. Der Assistent kennt deine Geräte und
                kann selbst nachmessen – pingen, Ports prüfen, Internetverbindung testen.
              </p>
              <div className="chat-suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="secondary small" onClick={() => void send(s)}>{s}</button>
                ))}
              </div>
            </div>
          ) : null}

          {!showSkeleton && messages.map((m) => (
            <div key={m.id} className={`bubble ${m.role}`}>
              {m.role === "assistant" ? <Markdown>{m.content}</Markdown> : m.content}
              <div className="bubble-meta">{formatMessageMeta(m)}</div>
            </div>
          ))}

          {busy && (
            <div className="bubble assistant chat-thinking" role="status">
              <span className="chat-dots" aria-hidden="true"><span /><span /><span /></span>
              <span className="muted">Ich schaue nach …</span>
            </div>
          )}

          {!busy && toolsUsed.length > 0 && (
            <div className="chat-tools" aria-label="Dafür geprüft">
              <span className="chat-tools-label">Dafür geprüft:</span>
              {Array.from(new Set(toolsUsed)).map((tool) => <span key={tool} className="chat-tool">{tool}</span>)}
            </div>
          )}
        </div>

        <div className="chat-compose">
          {SpeechRecognitionImpl && (
            <button
              type="button"
              className={`sbtn chat-icon-button${recording ? " recording" : ""}`}
              onClick={toggleVoiceInput}
              disabled={busy}
              aria-label={recording ? "Aufnahme stoppen" : "Spracheingabe starten"}
              title={recording ? "Aufnahme stoppen" : "Spracheingabe starten"}
            >
              {recording ? <Square size={18} aria-hidden="true" /> : <Mic size={20} aria-hidden="true" />}
            </button>
          )}
          <textarea
            rows={1}
            aria-label="Frage an den Assistenten"
            placeholder="Frag etwas …"
            title="Enter sendet, Shift+Enter beginnt eine neue Zeile"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={busy}
          />
          <button type="button" className="sbtn chat-icon-button chat-send" onClick={() => void send(input)}
                  disabled={busy || !input.trim()} aria-label="Senden" title="Senden">
            <SendHorizontal size={20} aria-hidden="true" />
          </button>
        </div>
      </div>
    </div>
  );
}
