/**
 * The caption buttons, drawn by the app because the window has no OS title bar.
 *
 * Presentational: every action arrives as a prop, so this file needs no window API
 * and can be tested in jsdom. `useWindowControls` is what supplies them, and it
 * declines to supply anything outside the shell.
 *
 * Three decisions that are not visible in the markup:
 *
 * - **The glyphs are drawn, not characters.** "??, "?? and "×" are laid out by
 *   whatever font happens to be installed and sit at different baselines in
 *   each of them; the caption is the one part of a window whose alignment is
 *   judged against the OS, and it has to line up with itself.
 * - **Close is last and red.** Windows puts it last too, and colour-coding it is
 *   the one piece of the system caption people expect to still be there.
 * - **Every button is named and has a tooltip.** The glyphs are decoration; a
 *   screen reader announces "button" three times in a row otherwise.
 */

import type { ReactNode } from "react";

interface Props {
  /** Whether the window is maximized, so the middle button restores it. */
  maximized: boolean;
  onMinimize: () => void;
  onToggleMaximize: () => void;
  onClose: () => void;
}

/** 10px of glyph in a 42px bar, which is what the Windows caption uses. */
const GLYPH = { width: 10, height: 10 };

function Glyph({ children }: { children: ReactNode }) {
  return (
    <svg
      width={GLYPH.width}
      height={GLYPH.height}
      viewBox="0 0 10 10"
      fill="none"
      stroke="currentColor"
      strokeWidth="1"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function WindowControls({
  maximized,
  onMinimize,
  onToggleMaximize,
  onClose,
}: Props) {
  return (
    <div className="window-controls" role="group" aria-label="Window">
      <button
        type="button"
        className="win-btn"
        onClick={onMinimize}
        title="Minimize"
        aria-label="Minimize window"
      >
        <Glyph>
          <path d="M0.5 5h9" />
        </Glyph>
      </button>

      <button
        type="button"
        className="win-btn"
        onClick={onToggleMaximize}
        title={maximized ? "Restore" : "Maximize"}
        aria-label={maximized ? "Restore window" : "Maximize window"}
      >
        {maximized ? (
          // Two overlapping squares: one in front, the outline of the one it
          // was covering behind it. A single square would be indistinguishable
          // from the maximize glyph at 10px.
          <Glyph>
            <path d="M2.5 0.5h7v7" />
            <path d="M0.5 2.5h7v7h-7z" />
          </Glyph>
        ) : (
          <Glyph>
            <rect x="0.5" y="0.5" width="9" height="9" />
          </Glyph>
        )}
      </button>

      <button
        type="button"
        className="win-btn is-close"
        onClick={onClose}
        title="Close"
        aria-label="Close window"
      >
        <Glyph>
          <path d="M0.5 0.5l9 9M9.5 0.5l-9 9" />
        </Glyph>
      </button>
    </div>
  );
}