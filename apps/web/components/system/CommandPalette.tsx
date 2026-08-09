"use client";

import { Command as Cmdk } from "cmdk";
import { motion } from "motion/react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { GROUP_ORDER, useCommands, type Command } from "@/lib/commands";
import { bloom, springs, useGatedMotion } from "@/lib/motion";
import { QUALITY_META, QUALITY_TIERS } from "@/lib/quality";
import { THEMES, THEME_META } from "@/lib/themes";
import { useAppearance } from "./ThemeProvider";
import { Kbd, ModKey } from "@/components/ui/Kbd";

/**
 * ⌘K. The universal control surface.
 *
 * Everything the product can do is reachable from here, which is what lets the
 * chrome stay quiet: a dense UI feels fast when the keyboard is the primary
 * input and the mouse is the fallback.
 */
export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const router = useRouter();
  const { theme, setTheme, quality, setQuality } = useAppearance();
  const registered = useCommands();
  const variants = useGatedMotion(bloom);

  /**
   * Whatever had focus when the palette was summoned.
   *
   * Captured in the keydown handler rather than an effect: cmdk moves focus to
   * its own input as it mounts, so by the time any effect runs the original is
   * already gone.
   */
  const restoreTo = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        if (!open) restoreTo.current = document.activeElement as HTMLElement | null;
        setOpen((value) => !value);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (!open) setSearch("");
  }, [open]);

  /**
   * Give focus back to whatever had it.
   *
   * ⌘K is global, so it gets pressed by accident mid-sentence. Left alone,
   * dismissing the palette drops focus on <body> and a keyboard user has to tab
   * all the way back to the field they were typing in -- which makes the
   * shortcut something to be careful around rather than something to reach for.
   *
   * Radix's Dialog does have this behaviour built in, but cmdk renders
   * `Dialog.Content` itself and forwards only `aria-label` and a className, so
   * `onCloseAutoFocus` is not reachable from here and its default does not fire
   * through cmdk's wrapper. Hence doing it by hand.
   *
   * The `setTimeout` matters: Radix tears its focus scope down in a layout
   * effect cleanup, synchronously, *after* this effect body runs. Restoring in
   * an effect or a rAF gets silently undone a beat later; a macrotask lands
   * after the teardown and sticks.
   */
  useEffect(() => {
    if (open) return;
    const target = restoreTo.current;
    restoreTo.current = null;
    if (!target?.isConnected) return;
    const timer = setTimeout(() => target.focus(), 0);
    return () => clearTimeout(timer);
  }, [open]);

  const appearanceCommands = useMemo<Command[]>(
    () => [
      ...THEMES.map((id) => ({
        id: `theme:${id}`,
        label: `Theme — ${THEME_META[id].label}`,
        group: "Appearance" as const,
        keywords: `${THEME_META[id].hint} colour color scheme`,
        hint: id === theme ? "active" : undefined,
        run: () => setTheme(id),
      })),
      ...QUALITY_TIERS.map((tier) => ({
        id: `quality:${tier}`,
        label: `Graphics — ${QUALITY_META[tier].label}`,
        group: "Appearance" as const,
        keywords: `${QUALITY_META[tier].hint} 3d performance fps motion`,
        hint: tier === quality ? "active" : undefined,
        run: () => setQuality(tier),
      })),
    ],
    [theme, setTheme, quality, setQuality],
  );

  const navCommands = useMemo<Command[]>(
    () => [
      {
        id: "nav:mission-control",
        label: "Go to Mission Control",
        group: "Navigate",
        keywords: "sessions dashboard home overview",
        run: () => router.push("/"),
      },
    ],
    [router],
  );

  const all = useMemo(
    () => [...registered, ...navCommands, ...appearanceCommands],
    [registered, navCommands, appearanceCommands],
  );

  const grouped = useMemo(() => {
    const buckets = new Map<string, Command[]>();
    for (const command of all) {
      const list = buckets.get(command.group) ?? [];
      list.push(command);
      buckets.set(command.group, list);
    }
    return GROUP_ORDER.filter((group) => buckets.has(group)).map((group) => ({
      group,
      commands: buckets.get(group)!,
    }));
  }, [all]);

  const run = useCallback((command: Command) => {
    setOpen(false);
    // Defer so the dialog's exit animation is not competing with whatever the
    // command does (navigation, a network call, a modal of its own).
    queueMicrotask(() => void command.run());
  }, []);

  return (
    /* The dialog stays mounted and is told to close, rather than being
       conditionally rendered away inside an AnimatePresence. Destroying it
       skips cmdk's and Radix's own teardown, which is how the Escape key ended
       up leaving a keyboard user on <body>. Keeping it mounted costs the exit
       animation; the entrance is the one that was doing any work, and the focus
       restore above is the part a person actually notices. */
    <Cmdk.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      className="fixed inset-0 z-[100]"
    >
      <motion.div
        className="fixed inset-0 bg-base/70 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.15 }}
        onClick={() => setOpen(false)}
      />

      <motion.div
        variants={variants}
        initial="hidden"
        animate="visible"
        transition={springs.settle}
        className="glass-elevated fixed left-1/2 top-[18vh] z-10 w-[min(92vw,620px)] -translate-x-1/2 overflow-hidden rounded-2xl shadow-[0_30px_90px_-24px_rgba(0,0,0,0.85)]"
        data-testid="command-palette"
      >
        <div className="flex items-center gap-3 border-b border-edge px-4">
          <span className="text-ink-faint" aria-hidden>
            ⌘
          </span>
          <Cmdk.Input
            value={search}
            onValueChange={setSearch}
            placeholder="Search commands…"
            data-testid="command-input"
            className="h-12 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
          />
          <Kbd>esc</Kbd>
        </div>

        <Cmdk.List className="max-h-[52vh] overflow-y-auto p-2">
          <Cmdk.Empty className="px-3 py-8 text-center text-sm text-ink-faint">
            Nothing matches “{search}”.
          </Cmdk.Empty>

          {grouped.map(({ group, commands }) => (
            <Cmdk.Group
              key={group}
              heading={group}
              className="mb-1 [&_[cmdk-group-heading]]:px-3 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-ink-faint"
            >
              {commands.map((command) => (
                <Cmdk.Item
                  key={command.id}
                  value={`${command.label} ${command.keywords ?? ""}`}
                  disabled={command.disabled}
                  onSelect={() => run(command)}
                  data-testid={`command-${command.id}`}
                  className={[
                    "flex cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm",
                    "text-ink-dim data-[selected=true]:bg-raised data-[selected=true]:text-ink",
                    "data-[disabled=true]:cursor-not-allowed data-[disabled=true]:opacity-40",
                    command.group === "Danger"
                      ? "data-[selected=true]:text-danger"
                      : "",
                  ].join(" ")}
                >
                  <span className="truncate">{command.label}</span>
                  {command.hint && (
                    <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-ink-faint">
                      {command.hint}
                    </span>
                  )}
                </Cmdk.Item>
              ))}
            </Cmdk.Group>
          ))}
        </Cmdk.List>
      </motion.div>
    </Cmdk.Dialog>
  );
}

/** The persistent affordance that teaches the shortcut exists. */
export function CommandHint() {
  return (
    <span className="hidden items-center gap-1.5 text-[11px] text-ink-faint sm:inline-flex">
      <Kbd>
        <ModKey />
      </Kbd>
      <Kbd>K</Kbd>
    </span>
  );
}
