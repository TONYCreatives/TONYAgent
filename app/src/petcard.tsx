/**
 * The desktop pet's page: the card, and what is drawn on it.
 *
 * A second entry point in the same bundle as the app. Not a second build, and
 * not a second copy of anything: it imports the app's own mark, its own tokens
 * and its own host bridge, because the pet is the same program in a much smaller
 * window.
 *
 * **The file is `petcard.tsx` and not `pet.tsx`, and that is not tidiness.** The
 * host helpers are `pet.ts`, and both files would compile to `pet.js`: TypeScript
 * writes them in turn and the second silently replaces the first, so the card's
 * own module becomes the helper and tests that import `./pet.js` for the card get
 * the wrong module with no error anywhere. Measured -- the emitted `pet.js`
 * contained neither the card nor the mark.
 *
 * **It has no buttons, and that is deliberate.** The whole card is a drag handle
 * -- `easy_drag` on this window, unlike the app's own, which renounces it -- so
 * anything with a press of its own competes with the drag for the same gesture.
 * One gesture is left, a press that raises the app, and turning the card off
 * belongs where it was turned on: the app's rail.
 */

// No stylesheet here, and none in `App.tsx` either. CSS is imported by the
// *entry* module (`petmain.tsx`, as `main.tsx` is for the app), which is the only
// shape a Node test can load: the compiled component is imported by
// `petcard.test.tsx`, and `import "./styles.css"` in it would be an ESM import of
// a CSS file that Node cannot resolve.
import { useEffect, useState } from "react";

import { MARK_RECTS, MARK_VIEWBOX } from "./AppMark.js";
import { installStatusHandler } from "./bridge.js";
import { petFocusApp, petReady } from "./pet.js";
import type { PetMood, PetStatus } from "./pet-status.js";

/**
 * The eyes, in the mark's own coordinate space.
 *
 * Placed on the crossbar, which leaves the stem below as the body: the same two
 * strokes the app draws everywhere else, read as a head and a body rather than
 * changed into one. `petcard.test.tsx` asserts both eyes are inside the crossbar's
 * rectangle -- an eye that spills over its edge is a drawing bug that reads as a
 * wink, and a wink is not something this card means.
 */
export const PET_EYES: readonly { cx: number; cy: number; r: number }[] = [
  { cx: 348, cy: 260, r: 52 },
  { cx: 676, cy: 260, r: 52 },
];

/** What the card draws before anything has happened, and after anything odd. */
export const PET_IDLE: PetStatus = { mood: "idle", label: "Ready when you are", detail: "" };

const MOODS: readonly PetMood[] = ["idle", "working", "waiting", "failed"];

/**
 * A pushed status, checked before it is drawn.
 *
 * The push comes from the host, which was told by the app's page, which read it
 * off the core's stream -- three hops, and this window is the last one. It is
 * not a hostile input, but it is an *unchecked* one: a status that arrives
 * missing its label would render the word "undefined" on a card whose entire job
 * is to be glanceable, so it is validated down to the shape it is drawn from.
 */
export function readStatus(raw: unknown): PetStatus {
  if (typeof raw !== "object" || raw === null) return PET_IDLE;
  const { mood, label, detail } = raw as Partial<PetStatus>;
  if (typeof mood !== "string" || !MOODS.includes(mood as PetMood)) return PET_IDLE;
  if (typeof label !== "string" || !label) return PET_IDLE;
  return { mood: mood as PetMood, label, detail: typeof detail === "string" ? detail : "" };
}

/** The app's mark, with eyes. The strokes are the mark's own, not a redrawing. */
function Figure() {
  return (
    <svg
      className="pet-body"
      viewBox={`0 0 ${MARK_VIEWBOX} ${MARK_VIEWBOX}`}
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      {MARK_RECTS.map((rect) => (
        <rect
          key={`${rect.x},${rect.y}`}
          x={rect.x}
          y={rect.y}
          width={rect.width}
          height={rect.height}
          rx={rect.rx}
        />
      ))}
      {/* In the card's own background colour, so the eyes read as holes in the
          head rather than as two more shapes on it. */}
      <g className="pet-eye" fill="var(--surface,#202020)">
        {PET_EYES.map((eye) => (
          <circle key={eye.cx} cx={eye.cx} cy={eye.cy} r={eye.r} />
        ))}
      </g>
    </svg>
  );
}

export function PetCard() {
  const [status, setStatus] = useState<PetStatus>(PET_IDLE);

  useEffect(() => {
    // The handler first, then `ready`: the host flushes what it remembered
    // *during* that call, so a card that said it was listening before it was
    // would miss the first status and sit idle until something changed.
    installStatusHandler((raw) => setStatus(readStatus(raw)));

    // **And then it keeps asking until the host takes it.** The bridge is
    // injected after the document loads, and this effect runs at mount -- so the
    // first `ready` raced it, was dropped, and the card spent its whole life on
    // "ready when you are" while the agent worked. Measured on a real window:
    // `page_ready: false`, with the bridge present and the call working by hand.
    //
    // Ten tries at 250ms is longer than any injection has been observed to take
    // and short enough that a card with no host at all settles in a quarter of a
    // second. The host's `mark_ready` is idempotent, so an extra one costs a
    // round trip and nothing else.
    let live = true;
    void (async () => {
      for (let attempt = 0; attempt < 40 && live; attempt += 1) {
        if (await petReady()) return;
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
    })();
    return () => {
      live = false;
    };
  }, []);

  return (
    <div
      className="pet"
      data-mood={status.mood}
      // Pointer rather than click: a press that starts the window dragging may
      // never deliver a click, and the press is the half that arrives.
      onPointerDown={() => void petFocusApp()}
    >
      <div className="pet-head">
        <span>TONYAgent</span>
        <span className="pet-dot" />
      </div>
      <div className="pet-figure">
        <Figure />
      </div>
      <div className="pet-text">
        <span className="pet-label" title={status.label}>
          {status.label}
        </span>
        {status.detail && <span className="pet-detail">{status.detail}</span>}
      </div>
    </div>
  );
}

