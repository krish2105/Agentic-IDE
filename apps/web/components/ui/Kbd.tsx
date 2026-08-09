export function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-edge-strong bg-raised px-1.5 font-mono text-[10px] font-medium text-ink-dim">
      {children}
    </kbd>
  );
}

/** Renders ⌘ on Apple platforms and Ctrl everywhere else. Resolved on the
 *  client only, so it never mismatches during hydration. */
export function ModKey() {
  if (typeof navigator === "undefined") return <>Ctrl</>;
  return <>{/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"}</>;
}
