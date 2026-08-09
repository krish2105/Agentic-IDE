/**
 * Accessibility, asserted rather than asserted-about.
 *
 * The redesign's quality bar promised keyboard access, `prefers-reduced-motion`
 * support and WCAG AA contrast. Those are the easiest promises in a design
 * system to quietly break -- a `text-ink-faint` on a glass panel passes review
 * by eye and fails at 3:1 -- so they are checked here by a machine, on every
 * theme, against a real running app.
 *
 * axe is the floor, not the ceiling. The hand-written tests below cover the
 * things axe cannot see: that the approval gate is reachable and operable from
 * the keyboard alone, and that reduced motion genuinely removes motion rather
 * than merely shortening it.
 *
 * Both servers must already be running. See e2e/README.md.
 */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SERVER, preflight } from "./preflight";

const THEMES = ["void", "nebula", "aurora", "solar", "mono", "daylight"] as const;

function makeWorkspace(): string {
  const dir = mkdtempSync(join(tmpdir(), "sani-a11y-"));
  writeFileSync(join(dir, "README.md"), "# Demo project\n\nNothing here yet.\n");
  writeFileSync(join(dir, "scratch.tmp"), "left over from a previous run\n");
  return dir;
}

async function blockedSession(page: Page): Promise<string> {
  const response = await page.request.post(`${SERVER}/session`, {
    data: { task: "add a greeting module", workspace: makeWorkspace() },
  });
  const { session_id } = await response.json();
  await page.goto(`/session/${session_id}`);
  await expect(page.getByTestId("approval-card")).toBeVisible();
  return session_id;
}

/**
 * Wait for entrance animations to finish.
 *
 * Axe measures contrast against what is actually composited, so an element
 * caught mid-fade at opacity 0.4 fails on colours that are fine once it lands.
 * Scanning without this reports the animation, not the palette -- and the
 * difference matters, because one is a real bug and the other is noise that
 * teaches you to ignore the suite.
 */
async function settle(page: Page): Promise<void> {
  await page.waitForFunction(
    () =>
      document
        .getAnimations()
        // Deliberately-infinite animations never finish -- the amber pulse on a
        // pending approval and the ambient field are both meant to keep going.
        // Waiting on those would hang forever; they also do not fade content.
        .filter((a) => a.effect?.getComputedTiming().iterations !== Infinity)
        .every((a) => a.playState !== "running"),
    undefined,
    { timeout: 10_000 },
  );
}

/** Serious and critical only. Axe's "minor" bucket is largely advisory and a
 *  suite that fails on it gets muted, which is worse than not having one. */
async function scan(page: Page) {
  await settle(page);
  return new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
}

function serious(results: Awaited<ReturnType<typeof scan>>) {
  return results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

/**
 * Readable failure: axe's own output is a wall of JSON, and a contrast failure
 * you cannot act on gets suppressed rather than fixed. So print the two colours
 * and the measured ratio -- that is the whole fix, right there in the error.
 */
function describe(results: Awaited<ReturnType<typeof scan>>): string {
  return serious(results)
    .map((violation) => {
      const nodes = violation.nodes.map((node) => {
        const data = node.any[0]?.data as
          | { fgColor?: string; bgColor?: string; contrastRatio?: number }
          | undefined;
        const measured = data?.contrastRatio
          ? ` — ${data.fgColor} on ${data.bgColor} = ${data.contrastRatio.toFixed(2)}:1`
          : "";
        return `    ${node.target.join(" ")}${measured}`;
      });
      return `${violation.impact} · ${violation.id}: ${violation.help}\n${nodes.join("\n")}`;
    })
    .join("\n");
}

test.describe("accessibility", () => {
  test.beforeAll(preflight);

  test.beforeEach(async ({ page }) => {
    await page.addInitScript((server) => {
      window.localStorage.setItem("sani.serverUrl", server);
      window.localStorage.setItem("sani.quality", "off");
    }, SERVER);
  });

  // --- contrast, on every theme ----------------------------------------

  for (const theme of THEMES) {
    test(`the ${theme} theme has no serious violations on the landing page`, async ({
      page,
    }) => {
      await page.addInitScript((id) => window.localStorage.setItem("sani.theme", id), theme);
      await page.goto("/");
      await expect(page.getByTestId("landing-hero")).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);

      const results = await scan(page);
      expect(describe(results), `${theme}: ${serious(results).length} violation(s)`).toBe("");
    });
  }

  // The approval card is the surface that matters most, and it sits on
  // `.glass-elevated` -- 72% opacity plus `saturate(1.4)`, which composites to a
  // lighter background than any solid token. Text that clears AA on `--t-raised`
  // can still fail on the glass, so every theme is checked here rather than
  // trusting the landing-page scan.
  for (const theme of THEMES) {
    test(`the ${theme} session view has no serious violations while blocked`, async ({
      page,
    }) => {
      await page.addInitScript((id) => window.localStorage.setItem("sani.theme", id), theme);
      await blockedSession(page);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);

      const results = await scan(page);
      expect(describe(results), `${theme}: ${serious(results).length} violation(s)`).toBe("");
    });
  }

  // --- keyboard ---------------------------------------------------------

  test("an approval can be granted without a mouse", async ({ page }) => {
    // The approval gate is the product. If it is only reachable by pointer,
    // the safety model excludes keyboard and screen-reader users from the one
    // decision that matters.
    await blockedSession(page);

    const approve = page.getByTestId("approve-button");
    await approve.focus();
    await expect(approve).toBeFocused();

    // A real focus ring, not just focusability -- an invisible focus state is
    // the same as none for a sighted keyboard user.
    const outline = await approve.evaluate((el) => {
      const style = getComputedStyle(el);
      return {
        outlineWidth: style.outlineWidth,
        outlineStyle: style.outlineStyle,
        boxShadow: style.boxShadow,
      };
    });
    expect(
      outline.outlineStyle !== "none" || outline.boxShadow !== "none",
      "the approve button has no visible focus indicator",
    ).toBe(true);

    await page.keyboard.press("Enter");
    await expect(page.getByTestId("status-pill")).toHaveAttribute("data-status", "complete", {
      timeout: 30_000,
    });
  });

  test("the command palette traps and returns focus", async ({ page }) => {
    await page.goto("/");
    const task = page.getByTestId("task-input");
    await task.focus();

    await page.keyboard.press("ControlOrMeta+k");
    await expect(page.getByTestId("command-input")).toBeFocused();

    await page.keyboard.press("Escape");
    await expect(page.getByTestId("command-palette")).toBeHidden();
    // Returning focus to where it was is what makes the shortcut safe to press
    // by accident mid-task.
    await expect(task).toBeFocused();
  });

  test("every interactive control on the session view is a real button or link", async ({
    page,
  }) => {
    await blockedSession(page);

    // A div with an onClick is invisible to assistive tech and to the keyboard.
    // This catches the drift that creeps in when a component is styled first.
    const fakes = await page.evaluate(() => {
      const bad: string[] = [];
      for (const el of document.querySelectorAll<HTMLElement>("[data-testid]")) {
        const tag = el.tagName.toLowerCase();
        const interactive = ["button", "a", "input", "select", "textarea"].includes(tag);
        const role = el.getAttribute("role");
        const looksClickable = el.style.cursor === "pointer" || el.className.includes("cursor-pointer");
        if (looksClickable && !interactive && !role) bad.push(`${tag}[data-testid=${el.dataset.testid}]`);
      }
      return bad;
    });
    expect(fakes).toEqual([]);
  });

  // --- reduced motion ---------------------------------------------------

  test("reduced motion removes animation rather than shortening it", async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: "reduce" });
    const page = await context.newPage();
    await page.addInitScript((server) => {
      window.localStorage.setItem("sani.serverUrl", server);
      window.localStorage.setItem("sani.quality", "off");
    }, SERVER);

    await page.goto("/");
    await expect(page.getByTestId("landing-hero")).toBeVisible();

    // The kinetic headline is the one place motion carries meaning, so it is
    // also the place a reduced-motion bug would be most visible: the words must
    // be at full opacity immediately, not fading in faster.
    const opacity = await page
      .getByTestId("landing-hero")
      .locator("span")
      .first()
      .evaluate((el) => getComputedStyle(el).opacity);
    expect(Number(opacity)).toBe(1);

    // And the content is all there -- reduced motion must never mean less.
    await expect(page.getByTestId("landing-hero")).toContainText("Watch");
    await expect(page.getByTestId("landing-hero")).toContainText("think");

    const results = await scan(page);
    expect(describe(results)).toBe("");
    await context.close();
  });

  test("the work surface is usable at a phone width", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await blockedSession(page);

    // Nothing may force a horizontal scroll -- the approval card in particular,
    // because a decision you have to scroll sideways to read is a decision
    // people stop reading.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(page.getByTestId("approve-button")).toBeVisible();
  });
});
