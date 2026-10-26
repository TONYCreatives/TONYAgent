/**
 * The workspace switch, in its two forms.
 *
 * The labelled form moved out of the top bar in Phase 2, and the move is the
 * thing these tests hold: all three workspaces are named, the one in front is
 * the one pressed, Code is refused with no folder, and the control does not
 * carry the window's drag class (a press on it must change the view, not move
 * the window).
 *
 * The rail's form is the compact one: a single named button showing the current
 * view, and a menu with the three. What is pinned there is that the menu is a
 * *radio* menu -- one checked item -- and that the choice is reported rather
 * than applied locally, the same contract every other controlled control in the
 * window has.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { RailViewButton, ViewSwitch } from "./ViewSwitch.js";
import { all, click, one, render } from "./test-render.js";

const options = (c: HTMLElement) => textsOf(c, ".viewswitch-option");

function textsOf(c: HTMLElement, selector: string): string[] {
  return all(c, selector).map((node) => (node.textContent ?? "").trim());
}

const active = (c: HTMLElement) =>
  (one(c, ".viewswitch-option.is-active")?.textContent ?? "").trim();

describe("the labelled switch", () => {
  test("it names every workspace, and presses the one in front", async () => {
    const container = await render(
      <ViewSwitch mode="agent" canCode onChange={() => {}} />,
    );
    assert.deepEqual(options(container), ["Agent", "Code", "Trajectory"]);
    assert.equal(active(container), "Agent");
    assert.equal(
      one(container, ".viewswitch")!.getAttribute("aria-label"),
      "View",
      "a group of buttons needs a name",
    );
  });

  test("it says which workspace is in front, both ways", async () => {
    const code = await render(<ViewSwitch mode="code" canCode onChange={() => {}} />);
    assert.equal(active(code), "Code");

    const trajectory = await render(
      <ViewSwitch mode="trajectory" canCode onChange={() => {}} />,
    );
    assert.equal(active(trajectory), "Trajectory");
  });

  test("settings lights no segment, because it is not one of the three", async () => {
    // The page has no transcript behind it to come back to, so the switch is
    // honest about there being no current view among the three. It is not
    // rendered in Settings at all; this is what would happen if it were.
    const container = await render(
      <ViewSwitch mode="settings" canCode onChange={() => {}} />,
    );
    assert.equal(one(container, ".viewswitch-option.is-active"), null);
  });

  test("pressing a workspace asks for it", async () => {
    const asked: string[] = [];
    const container = await render(
      <ViewSwitch mode="agent" canCode onChange={(next) => asked.push(next)} />,
    );
    const trajectory = all(container, ".viewswitch-option").find(
      (b) => b.textContent === "Trajectory",
    )!;

    await click(trajectory);

    assert.deepEqual(asked, ["trajectory"]);
    assert.equal(
      trajectory.getAttribute("aria-pressed"),
      "false",
      "the parent owns the state",
    );
  });

  test("the code workspace is refused with no folder, and says why", async () => {
    const asked: string[] = [];
    const container = await render(
      <ViewSwitch mode="agent" canCode={false} onChange={(m) => asked.push(m)} />,
    );
    const code = all(container, ".viewswitch-option").find(
      (b) => b.textContent === "Code",
    )!;

    assert.equal((code as HTMLButtonElement).disabled, true);
    assert.match(code.getAttribute("title") ?? "", /project folder/);
    await click(code);
    assert.deepEqual(asked, [], "a disabled workspace must not be enterable");
  });

  test("trajectory is never disabled, because it needs no folder", async () => {
    const asked: string[] = [];
    const container = await render(
      <ViewSwitch mode="agent" canCode={false} onChange={(m) => asked.push(m)} />,
    );
    const trajectory = all(container, ".viewswitch-option").find(
      (b) => b.textContent === "Trajectory",
    )!;
    assert.equal((trajectory as HTMLButtonElement).disabled, false);
    await click(trajectory);
    assert.deepEqual(asked, ["trajectory"]);
  });

  test("the control is not a drag handle", async () => {
    // The bar it used to sit in is the window's move handle, and a press moves
    // the window only when it lands on an element carrying the class itself.
    // The switch is in the nav now and the class must not have come with it.
    const container = await render(
      <ViewSwitch mode="agent" canCode onChange={() => {}} />,
    );
    assert.equal(
      one(container, ".viewswitch")!.classList.contains("app-drag-region"),
      false,
    );
  });
});

const glyphs = {
  agent: <span className="glyph-agent" />,
  code: <span className="glyph-code" />,
  trajectory: <span className="glyph-trajectory" />,
};

describe("the rail's switch", () => {
  test("one button, named for the view it is showing", async () => {
    const container = await render(
      <RailViewButton mode="code" canCode onChoose={() => {}} glyphs={glyphs} />,
    );
    const button = one(container, ".rail-view")!;
    assert.equal(button.getAttribute("aria-label"), "View: Code");
    assert.equal(button.getAttribute("aria-haspopup"), "menu");
    assert.ok(one(button, ".glyph-code"), "the button is not showing Code's glyph");
  });

  test("the menu names all three and checks exactly the one in front", async () => {
    const container = await render(
      <RailViewButton mode="agent" canCode onChoose={() => {}} glyphs={glyphs} />,
    );
    await click(one(container, ".rail-view")!);

    // Portalled to the body, so it is not inside the rail's container.
    const items = all(document.body, ".viewmenu-item");
    assert.deepEqual(
      items.map((item) => (item.textContent ?? "").replace("✓", "").trim()),
      ["Agent", "Code", "Trajectory"],
    );
    assert.deepEqual(
      items.map((item) => item.getAttribute("aria-checked")),
      ["true", "false", "false"],
    );
  });

  test("choosing one reports it and closes the menu", async () => {
    const asked: string[] = [];
    const container = await render(
      <RailViewButton
        mode="agent"
        canCode
        onChoose={(next) => asked.push(next)}
        glyphs={glyphs}
      />,
    );
    await click(one(container, ".rail-view")!);
    const trajectory = all(document.body, ".viewmenu-item").find(
      (item) => item.textContent?.startsWith("Trajectory"),
    )!;

    await click(trajectory);

    assert.deepEqual(asked, ["trajectory"]);
    assert.equal(all(document.body, ".viewmenu").length, 0, "the menu stayed open");
  });

  test("pressing the current view closes the menu without asking again", async () => {
    const asked: string[] = [];
    const container = await render(
      <RailViewButton
        mode="agent"
        canCode
        onChoose={(next) => asked.push(next)}
        glyphs={glyphs}
      />,
    );
    await click(one(container, ".rail-view")!);
    const agent = all(document.body, ".viewmenu-item")[0];
    await click(agent);
    assert.deepEqual(asked, []);
    assert.equal(all(document.body, ".viewmenu").length, 0);
  });

  test("code is refused there too, with the same reason", async () => {
    const asked: string[] = [];
    const container = await render(
      <RailViewButton
        mode="agent"
        canCode={false}
        onChoose={(next) => asked.push(next)}
        glyphs={glyphs}
      />,
    );
    await click(one(container, ".rail-view")!);
    const code = all(document.body, ".viewmenu-item").find((item) =>
      item.textContent?.startsWith("Code"),
    )!;
    assert.equal((code as HTMLButtonElement).disabled, true);
    assert.match(code.getAttribute("title") ?? "", /project folder/);
    await click(code);
    assert.deepEqual(asked, []);

    // And the menu is still up: a refused press is not a dismissal.
    assert.equal(all(document.body, ".viewmenu").length, 1);
  });
});
