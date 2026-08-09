"use client";

import { useEffect, useState } from "react";

export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-edge-strong bg-raised px-1.5 font-mono text-[10px] font-medium text-ink-dim">
      {children}
    </kbd>
  );
}

/**
 * ⌘ on Apple platforms, Ctrl everywhere else.
 *
 * Resolved after mount rather than during render: the server has no navigator,
 * so deciding at render time makes the server and client disagree and React
 * throws a hydration error. Renders the neutral form first, then corrects.
 */
export function ModKey() {
  const [mac, setMac] = useState(false);

  useEffect(() => {
    setMac(/Mac|iPhone|iPad|iPod/.test(navigator.userAgent));
  }, []);

  return <>{mac ? "⌘" : "Ctrl"}</>;
}
