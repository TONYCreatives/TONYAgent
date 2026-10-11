/**
 * A static preview of the `/` menu, for looking at it.
 *
 * Not part of the app -- `index.html` is the only entry Vite builds. Run
 * `npm run dev` in `app/` and open `/skills-preview.html`. The composer is the
 * real one with the real stylesheets; the only thing this file does that the
 * app does not is type the slash itself, so the menu is on screen without
 * anybody sitting there pressing a key.
 *
 * It exists because the menu is positioned *absolutely* against the composer's
 * own box (`bottom: calc(100% + 6px)`), and whether that lands above the field,
 * at the text column's inset, over the transcript, is a question about pixels
 * that no DOM assertion answers.
 */

import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";

import { Composer, type ModeInfo } from "./Composer.js";
import type { SkillInfo } from "./SkillPicker.js";
import "./styles.css";

const MODES: ModeInfo[] = [
  { name: "build", label: "Build", description: "Full access.", writes: true },
  { name: "plan", label: "Plan", description: "Read only.", writes: false },
  { name: "skills", label: "Skills", description: "No side effects.", writes: false },
];

/** What `/` shows when there are none: the one row that says where to put them. */
const EMPTY: SkillInfo[] = [];

const SKILLS: SkillInfo[] = [
  {
    name: "review",
    description: "Review a change for correctness, clarity and risk.",
    source: "project",
    path: ".tonyagent/skills/review.md",
  },
  {
    name: "release",
    description: "Cut a release: changelog, tag, notes.",
    source: "project",
    path: ".tonyagent/skills/release.md",
  },
  {
    name: "tidy",
    description: "Sort imports and remove dead code before review.",
    source: "user",
    path: "AppData/Roaming/TONYAgent/skills/tidy.md",
  },
];

function Page({ skills, typed }: { skills: SkillInfo[]; typed: string }) {
  const field = useRef<HTMLTextAreaElement | null>(null);
  const [text, setText] = useState("");

  // The keystroke the app would have received. The native setter is used for
  // the same reason the test harness uses it: assigning `value` does not notify
  // React, so the composer would never see it.
  useEffect(() => {
    const node = field.current;
    if (!node) return;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    )!.set!;
    setter.call(node, typed);
    node.dispatchEvent(new window.Event("input", { bubbles: true }));
  }, [typed]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "flex-end",
        minHeight: "100vh",
        padding: "0 0 12px",
      }}
    >
      <p style={{ padding: "0 32px", color: "var(--fg-mute)" }}>
        Typing <code>{typed || "(nothing)"}</code> in the composer:
      </p>
      <Composer
        inputRef={field}
        busy={false}
        disabled={false}
        modes={MODES}
        mode="build"
        skills={skills}
        onSkillsNeeded={() => {}}
        onModeChange={() => {}}
        onSend={(sent) => setText(sent)}
        onCancel={() => {}}
        maxToolCalls={10}
        budgetOpen={false}
        onBudgetOpen={() => {}}
        onBudgetClose={() => {}}
        onBudgetChange={() => {}}
      />
      <p className="hint" style={{ color: "var(--fg-mute)" }}>
        last sent: {text || "(nothing)"}
      </p>
    </div>
  );
}

/** Two presses, side by side, so both states are in one screenshot. */
function Gallery() {
  return (
    <div>
      <Page skills={SKILLS} typed="/" />
      <Page skills={SKILLS} typed="/re" />
      <Page skills={SKILLS} typed="/usr/local" />
      <Page skills={EMPTY} typed="/" />
    </div>
  );
}

createRoot(document.getElementById("skills-preview")!).render(
  <StrictMode>
    <Gallery />
  </StrictMode>,
);
