/**
 * The desktop pet's page: the card, the character, and what it is doing.
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
 * **The character is the app's own mark, with props.** The crossbar is the head
 * and the stem is the body -- the same two rects the title bar draws -- and
 * everything else is added around them for a pose: eyes that blink, a keyboard in
 * front for working, closed lids and three floating Z's for asleep, crossed eyes
 * for a failure. Redrawing the character as a *person* would have been a second
 * logo, which is the mistake `AppMark.tsx` was written to stop.
 *
 * **What moves, and what does not.** Every animation is CSS -- keyframes in
 * `pet.css`, cancelled in `reduced-motion.css` -- because that is where motion
 * belongs on a card whose whole job is to be glanced at: it runs off the main
 * thread and it stops the moment the user asks motion to stop. The one thing JS
 * decides is *which pose* is drawn, and the only pose with a clock behind it is
 * falling asleep. Nothing here animates on a timer.
 *
 * **The whole card is the drag handle.** `easy_drag` is off on this window --
 * see `DeskPet.drag` -- so a press starts the OS's own move loop through the
 * host. When that loop returns, the card asks whether it moved: a press that did
 * not move it is a *click*, and a click raises the app. The page cannot tell the
 * two apart by itself, because the modal loop swallows every event after the
 * press.
 */

// No stylesheet here, and none in `App.tsx` either. CSS is imported by the
// *entry* module (`petmain.tsx`, as `main.tsx` is for the app), which is the only
// shape a Node test can load: the compiled component is imported by
// `petcard.test.tsx`, and `import "./styles.css"` in it would be an ESM import of
// a CSS file that Node cannot resolve.
import { useEffect, useState } from "react";

import { MARK_EYES as PET_EYES, MARK_RECTS } from "./AppMark.js";import { installStatusHandler } from "./bridge.js";
import { petDrag, petFocusApp, petReady } from "./pet.js";
import { petPose, SLEEP_AFTER_MS, type PetMood, type PetPose, type PetStatus } from "./pet-status.js";

/**
 * The eyes, in the mark's own coordinate space.
 *
 * Placed on the crossbar, which leaves the stem below as the body: the same two
 * strokes the app draws everywhere else, read as a head and a body rather than
 * changed into one. `petcard.test.tsx` asserts both eyes are inside the crossbar's
 * rectangle -- an eye that spills over its edge is a drawing bug that reads as a
 * wink, and a wink is not something this card means.
 */
export { PET_EYES };

/**
 * The three Z's of the asleep pose, by their drawn position and size.
 *
 * **Beside the head rather than over it, and that is what the first version got
 * wrong twice.** Above the head they collided with the crossbar -- a grey glyph on
 * a near-white bar, invisible -- and clearing it put seventy units of headroom in
 * the frame that the character paid for in size. To the right of the head (`x >
 * 862`, where the crossbar ends) they can rise the whole way with nothing in the
 * way, and the frame is free to hug the drawing.
 *
 * Exported for the frame's test rather than for the drawing: the highest of them
 * plus `PET_Z_RISE` is what the frame has to have room for.
 */
export const PET_ZS: readonly { x: number; y: number; scale: number }[] = [
  { x: 634, y: 118, scale: 1.35 },
  { x: 738, y: 62, scale: 1.05 },
  { x: 822, y: 16, scale: 0.8 },
];

/**
 * How much bigger the eyes get when the card wants you.
 *
 * As an eye *hole* in the head rather than a pupil, "wide" is a bigger hole, which
 * is also why this is geometry rather than a CSS scale: the blink animation owns
 * the one transform these elements have.
 */
export const WIDE_EYE_SCALE = 1.22;

/** What the card draws before anything has happened, and after anything odd. */
export const PET_IDLE: PetStatus = { mood: "idle", label: "Ready when you are", detail: "" };

/**
 * The frame the character is drawn in, in the artwork's units.
 *
 * Not the mark's own `MARK_VIEWBOX`. The artwork is 1024 units square because
 * that is the canvas `icon.svg` draws in, and the *drawing* fills only part of it:
 * the head starts at y=168 and the feet end at 856, so a card that showed the
 * whole canvas spent a third of the figure's height on nothing. This is the
 * drawing's own bounds with room for the two poses that leave them -- the Z's that
 * rise (`PET_Z_RISE`) and the keyboard that sits in front -- which is worth about
 * 10% more character on the same card, and it is what keeps the Z's from being
 * clipped at the top, which the first version was: they floated out of the frame
 * and vanished.
 *
 * Square, so it fits the figure's box by height alone and the character cannot be
 * stretched by a card that is wider than it is tall.
 */
export const PET_FRAME = { x: 42, y: -70, width: 940, height: 940 };

/**
 * How far a Z rises, in the artwork's units.
 *
 * Exported because the frame above has to contain it, and asserted against it: a
 * rise longer than the frame's headroom is a Z that leaves the card. The distance
 * itself is in `pet.css`, which cannot read this -- so the two are a pair, and the
 * test is what holds them together.
 */
export const PET_Z_RISE = 70;

const MOODS: readonly PetMood[] = ["idle", "working", "waiting", "failed"];

/**
 * The open eyes for a pose, or none where the eyes are drawn another way.
 *
 * A pure function because it is the card's whole answer to "what does this pose
 * look like" for the part people actually look at, and because `asleep` and
 * `failed` are *not* open eyes of some size -- they are different drawings.
 */
export function eyesFor(pose: PetPose): readonly { cx: number; cy: number; r: number }[] {
  if (pose === "asleep" || pose === "failed") return [];
  const scale = pose === "waiting" ? WIDE_EYE_SCALE : 1;
  return PET_EYES.map((eye) => ({ cx: eye.cx, cy: eye.cy, r: eye.r * scale }));
}

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

/** One "z", drawn as three strokes so it needs no font to be a z. */
const Z_PATH = "M0 0 H44 L0 34 H44";

/**
 * The three Z's, rising to the upper right of the head.
 *
 * **Outside the crossbar, not over it.** The first version had them crossing the
 * head's right end and they were invisible there: the head is drawn in the card's
 * foreground colour and the Z's in a muted one, so a Z on the head is a light grey
 * glyph on a near-white bar. Every one of these sits above `y=168`, which is where
 * the head starts.
 *
 * The drift is a CSS transform on the *inner* path and the position is the outer
 * `<g>`'s `transform` attribute, which is not a style choice: a CSS `transform`
 * replaces the attribute outright, so animating the element that carries the
 * position would throw the position away on the first frame.
 */
const ZS = PET_ZS;

function Zzz() {
  return (
    <g
      className="pet-zzz"
      stroke="var(--fg-mute, #8a8a8a)"
      strokeWidth={11}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {ZS.map((z, index) => (
        <g key={`${z.x},${z.y}`} transform={`translate(${z.x} ${z.y}) scale(${z.scale})`}>
          {/* The delay staggers the three so they read as one breath rather than
              as three separate glyphs, and it is on the element rather than in
              the keyframes so one animation serves all three. */}
          <path className="pet-z" d={Z_PATH} style={{ animationDelay: `${index * 0.62}s` }} />
        </g>
      ))}
    </g>
  );
}

/**
 * The keyboard it works at, the keys, and the two hands on them.
 *
 * Drawn after the body so it sits in front of the lower stem: the character
 * leaning over a keyboard is the whole reading, and a keyboard behind it would be
 * a keyboard nobody is using.
 *
 * **The first version of this was invisible and this is what fixed it.** It was
 * `--input` (#2b2b2b) on a #202020 card, sixty-four units tall, so on screen it was
 * a nine-pixel shadow with two pale dots at its ends -- the hands read as knobs
 * because they were *outside* the key row, bracketing it rather than on it. Now
 * the keyboard is `--border-strong`, which is a surface step that can be seen
 * against the card, and the hands sit *inside* the row, directly under the body,
 * so they are hands on keys rather than furniture at the edges.
 */
export const PET_DESK = { x: 264, y: 796, width: 496, height: 72, rx: 20 };

/** Four keys in a row, lit one after another. Four reads as a keyboard; three read as a mistake. */
const KEYS: readonly number[] = [388, 470, 552, 634];

const HAND_R = 30;

/**
 * The two hands, half a cycle apart, at the ends of the keyboard.
 *
 * At the ends rather than under the body: what is drawn here is a keyboard with
 * keys *between* two hands, which is the arrangement a person sees when they look
 * down. Hands drawn under the body put them on the keys and hid the keys with
 * them -- the one thing on the card that says "typing" -- and hands drawn far
 * enough out to leave the keys alone look like furniture unless they are at the
 * keyboard's own edges.
 */
const HANDS: readonly { cx: number; delay: number; side: string }[] = [
  { cx: 320, delay: 0, side: "left" },
  { cx: 704, delay: 0.22, side: "right" },
];

function Desk() {
  return (
    <g className="pet-desk" aria-hidden="true">
      <rect
        x={PET_DESK.x}
        y={PET_DESK.y}
        width={PET_DESK.width}
        height={PET_DESK.height}
        rx={PET_DESK.rx}
        fill="var(--border-strong, #4a4a4a)"
      />
      {KEYS.map((x, index) => (
        <rect
          key={x}
          className="pet-key"
          x={x}
          y={824}
          width={68}
          height={16}
          rx={8}
          fill="var(--fg-mute, #8a8a8a)"
          style={{ animationDelay: `${(index * 0.21).toFixed(2)}s` }}
        />
      ))}
      {HANDS.map((hand) => (
        <circle
          key={hand.side}
          className={`pet-hand pet-hand-${hand.side}`}
          cx={hand.cx}
          cy={832}
          r={HAND_R}
          style={{ animationDelay: `${hand.delay}s` }}
        />
      ))}
    </g>
  );
}

/** The app's mark, with whatever the pose adds to it. */
function Figure({ pose }: { pose: PetPose }) {
  const eyes = eyesFor(pose);
  return (
    <svg
      className="pet-body"
      viewBox={`${PET_FRAME.x} ${PET_FRAME.y} ${PET_FRAME.width} ${PET_FRAME.height}`}
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

      {/* Asleep: the eyes are shut, which is two lids and not a smaller eye. */}
      {pose === "asleep" && (
        <g className="pet-lid" stroke="var(--surface, #202020)" strokeWidth={20} strokeLinecap="round">
          {PET_EYES.map((eye) => (
            <path key={eye.cx} d={`M${eye.cx - eye.r} ${eye.cy} H${eye.cx + eye.r}`} />
          ))}
        </g>
      )}

      {/* Failed: crossed out, which is the one drawing here that is a symbol
          rather than a face. */}
      {pose === "failed" && (
        <g
          className="pet-cross"
          stroke="var(--surface, #202020)"
          strokeWidth={22}
          strokeLinecap="round"
        >
          {PET_EYES.map((eye) => (
            <g key={eye.cx} transform={`translate(${eye.cx} ${eye.cy})`}>
              <path d={`M${-eye.r} ${-eye.r} L${eye.r} ${eye.r}`} />
              <path d={`M${eye.r} ${-eye.r} L${-eye.r} ${eye.r}`} />
            </g>
          ))}
        </g>
      )}

      {eyes.length > 0 && (
        <g className="pet-eyes" fill="var(--surface, #202020)">
          {eyes.map((eye) => (
            // A group per eye, because the blink scales each about its own
            // centre: one group around both would close them towards each other.
            <g className="pet-eye" key={eye.cx}>
              <circle cx={eye.cx} cy={eye.cy} r={eye.r} />
            </g>
          ))}
        </g>
      )}

      {pose === "working" && <Desk />}
      {pose === "asleep" && <Zzz />}
    </svg>
  );
}

export function PetCard() {
  const [status, setStatus] = useState<PetStatus>(PET_IDLE);
  /** Whether the idle clock has run out. See `petPose` for what may sleep. */
  const [asleep, setAsleep] = useState(false);
  /** Counts statuses, so the sleep clock restarts without a timestamp. */
  const [wakeful, setWakeful] = useState(0);

  useEffect(() => {
    // The handler first, then `ready`: the host flushes what it remembered
    // *during* that call, so a card that said it was listening before it was
    // would miss the first status and sit idle until something changed.
    installStatusHandler((raw) => {
      setStatus(readStatus(raw));
      // Any status at all is the agent doing something, which wakes it -- and
      // restarts the clock even when the status is the same one it was asleep
      // under, because a push only ever comes from a change.
      setWakeful((count) => count + 1);
    });

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

  // Falling asleep, and nothing else. A `setTimeout` rather than a poll, because
  // the question is "has it been quiet long enough" and that has an answer at
  // exactly one moment: it is cleared and re-set by every status, so the card
  // sleeps `SLEEP_AFTER_MS` after the *last* thing that happened.
  useEffect(() => {
    setAsleep(false);
    const timer = window.setTimeout(() => setAsleep(true), SLEEP_AFTER_MS);
    return () => window.clearTimeout(timer);
  }, [wakeful]);

  const pose = petPose(status, asleep);

  /**
   * A press: drag the card, or -- if it did not move -- open the app.
   *
   * Deliberately not awaited before the host call: the OS's move loop takes over
   * the mouse from the press it is told about, and the round trip to the host is
   * the same path the app's own title bar has always used. Nothing here is
   * allowed to reject into an unhandled promise, hence the `catch`.
   */
  const onPress = () => {
    void (async () => {
      try {
        const { moved } = await petDrag();
        if (!moved) await petFocusApp();
      } catch {
        // A pet that cannot be dragged or clicked is still a pet that is drawing
        // the right thing. Nothing to report and nowhere to report it.
      }
    })();
  };

  return (
    <div
      className="pet"
      // Two attributes because they are two vocabularies: `data-mood` is what the
      // *agent* is doing and drives the lamp's colour, `data-pose` is what the
      // *character* is doing and drives everything that moves. Collapsing them
      // would make "asleep" a mood, which is a thing no status can say.
      data-mood={status.mood}
      data-pose={pose}
      // One string for assistive tech rather than a live region: this card is
      // rewritten every few seconds while the agent works, and a status window
      // that interrupts a screen reader on every tool call is worse than one that
      // is quiet. The accessible account of a turn is the transcript.
      aria-label={`TONYAgent: ${status.label}${status.detail ? ` -- ${status.detail}` : ""}`}
      role="img"
      onPointerDown={onPress}
    >
      <span className="pet-dot" aria-hidden="true" />
      <div className="pet-figure">
        <Figure pose={pose} />
      </div>
      {/*
        One line, and the detail in the tooltip. The card is a circle now, and a
        chord is shorter than a diameter: at the height a second line would sit
        there is room for about fourteen characters of a file path, so the detail
        moved to the two places with room for it -- the tooltip and the label this
        card announces itself with. See `pet.css`.
      */}
      <div className="pet-text">
        <span className="pet-label" title={status.detail ? `${status.label} — ${status.detail}` : status.label}>
          {status.label}
        </span>
      </div>
    </div>
  );
}
