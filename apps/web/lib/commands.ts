"use client";

import { useEffect, useSyncExternalStore } from "react";

/**
 * The command registry.
 *
 * Static commands (theme, quality, navigation) are registered once by the
 * palette itself. Session-scoped commands (approve, reject, pause, kill, scrub)
 * are registered by whichever surface owns them and torn down on unmount, so
 * the palette can never offer an action that has no live target behind it.
 *
 * A tiny external store rather than context: the palette subscribes, and
 * registering from a deep component does not re-render the tree.
 */

export type CommandGroup =
  | "Session"
  | "Navigate"
  | "Appearance"
  | "Review"
  | "Danger";

export interface Command {
  id: string;
  label: string;
  group: CommandGroup;
  /** Extra text matched by the fuzzy filter but not displayed. */
  keywords?: string;
  /** Rendered right-aligned: a shortcut hint or current value. */
  hint?: string;
  /** Disabled commands stay visible so the palette teaches what exists. */
  disabled?: boolean;
  run: () => void | Promise<void>;
}

type Listener = () => void;

const registry = new Map<string, Command[]>();
const listeners = new Set<Listener>();
let snapshot: Command[] = [];

function recompute(): void {
  snapshot = Array.from(registry.values()).flat();
  for (const listener of listeners) listener();
}

export function registerCommands(scope: string, commands: Command[]): () => void {
  registry.set(scope, commands);
  recompute();
  return () => {
    registry.delete(scope);
    recompute();
  };
}

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

const EMPTY: Command[] = [];

export function useCommands(): Command[] {
  return useSyncExternalStore(
    subscribe,
    () => snapshot,
    () => EMPTY,
  );
}

/**
 * Register a scope's commands for the lifetime of the calling component.
 *
 * `deps` controls re-registration. Callers must include anything their `run`
 * closures capture, or the palette will invoke a stale closure.
 */
export function useRegisterCommands(
  scope: string,
  commands: Command[],
  deps: React.DependencyList,
): void {
  useEffect(
    () => registerCommands(scope, commands),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [scope, ...deps],
  );
}

export const GROUP_ORDER: CommandGroup[] = [
  "Session",
  "Review",
  "Navigate",
  "Appearance",
  "Danger",
];
