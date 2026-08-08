"use client";

import Editor, { loader } from "@monaco-editor/react";
import { useEffect, useRef, useState } from "react";

// Serve Monaco from this origin rather than a CDN, so the editor works offline
// and no third-party host sits in the load path of the main editing surface.
loader.config({ paths: { vs: "/monaco/vs" } });

export interface OpenTab {
  path: string;
  content: string;
  dirty: boolean;
  readOnly?: boolean;
  note?: string;
}

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  py: "python",
  json: "json",
  md: "markdown",
  css: "css",
  html: "html",
  yml: "yaml",
  yaml: "yaml",
  sh: "shell",
  toml: "ini",
  sql: "sql",
  rs: "rust",
  go: "go",
};

function languageFor(path: string): string {
  return LANGUAGE_BY_EXTENSION[path.split(".").pop()?.toLowerCase() ?? ""] ?? "plaintext";
}

interface Props {
  tabs: OpenTab[];
  activePath: string | null;
  agentTouchedPaths: Set<string>;
  onSelect: (path: string) => void;
  onClose: (path: string) => void;
  onChange: (path: string, content: string) => void;
  onSave: (path: string) => void;
}

export function EditorPane({
  tabs,
  activePath,
  agentTouchedPaths,
  onSelect,
  onClose,
  onChange,
  onSave,
}: Props) {
  const active = tabs.find((tab) => tab.path === activePath) ?? null;
  const [themeReady, setThemeReady] = useState(false);

  // Monaco owns keyboard focus, so its own command wins over a window listener.
  // The ref keeps the command's closure from going stale as tabs change.
  const saveRef = useRef<() => void>(() => {});
  saveRef.current = () => {
    if (activePath) onSave(activePath);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "s") {
        event.preventDefault();
        if (activePath) onSave(activePath);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activePath, onSave]);

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-base">
      <div className="flex h-8 shrink-0 items-stretch overflow-x-auto border-b border-edge bg-surface">
        {tabs.length === 0 && (
          <span className="flex items-center px-3 text-xs text-ink-faint">
            No file open — pick one from the explorer
          </span>
        )}
        {tabs.map((tab) => {
          const touched = agentTouchedPaths.has(tab.path);
          return (
            <div
              key={tab.path}
              onClick={() => onSelect(tab.path)}
              data-testid={`tab-${tab.path}`}
              className={`group flex cursor-pointer items-center gap-2 border-r border-edge px-3 text-xs ${
                tab.path === activePath
                  ? "bg-base text-ink"
                  : "text-ink-dim hover:text-ink"
              } ${touched ? "border-t-2 border-t-agent" : "border-t-2 border-t-transparent"}`}
            >
              <span className="font-mono">{tab.path.split("/").pop()}</span>
              {tab.dirty && <span className="h-1.5 w-1.5 rounded-full bg-attention" />}
              <button
                onClick={(event) => {
                  event.stopPropagation();
                  onClose(tab.path);
                }}
                className="text-ink-faint opacity-0 transition group-hover:opacity-100 hover:text-ink"
                aria-label={`Close ${tab.path}`}
              >
                ×
              </button>
            </div>
          );
        })}
      </div>

      <div className="min-h-0 flex-1" data-testid="editor-pane">
        {active ? (
          active.note ? (
            <div className="flex h-full items-center justify-center text-sm text-ink-faint">
              {active.note}
            </div>
          ) : (
            <Editor
              height="100%"
              theme={themeReady ? "sani-dark" : "vs-dark"}
              path={active.path}
              language={languageFor(active.path)}
              value={active.content}
              onChange={(value) => onChange(active.path, value ?? "")}
              beforeMount={(monaco) => {
                monaco.editor.defineTheme("sani-dark", {
                  base: "vs-dark",
                  inherit: true,
                  rules: [],
                  colors: {
                    "editor.background": "#0b0d12",
                    "editorGutter.background": "#0b0d12",
                    "editorLineNumber.foreground": "#626c7d",
                    "editor.lineHighlightBackground": "#12151c",
                  },
                });
                setThemeReady(true);
              }}
              onMount={(editor, monaco) => {
                editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () =>
                  saveRef.current(),
                );
              }}
              options={{
                fontSize: 13,
                fontFamily: "ui-monospace, 'SF Mono', Menlo, monospace",
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                readOnly: active.readOnly,
                automaticLayout: true,
                padding: { top: 12 },
                renderLineHighlight: "line",
              }}
            />
          )
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-ink-faint">
            Ṣāni&apos; Studio
          </div>
        )}
      </div>
    </section>
  );
}
