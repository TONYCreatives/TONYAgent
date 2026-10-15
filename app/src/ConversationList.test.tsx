/**
 * The conversation row's menu and its inline rename editor.
 *
 * These are interaction tests rather than render tests, because the rules worth
 * protecting are all about *what a keystroke does*: Enter commits, blur
 * commits, Escape throws the edit away, and a blank name is refused. A
 * snapshot of the markup would pass unchanged while every one of those four
 * behaviours was broken.
 *
 * The interesting one is the blank name. The core refuses it, but the editor
 * has to refuse it too, and refusing it wrongly -- by closing and showing the
 * old title -- reads as a successful rename. So the assertion is on both
 * halves: nothing is saved, *and* what the user typed is still there.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  ConversationList,
  rowsForFolder,
  type ConversationSummary,
} from "./ConversationList.js";
import {
  all,
  blur,
  click,
  contextMenu,
  one,
  pointerDown,
  press,
  render,
  rerender,
  setValue,
  texts,
  wait,
} from "./test-render.js";
import { exitDurationMs } from "./useDelayedUnmount.js";
import { dom } from "./test-dom.js";
import { readStylesheet } from "./stylesheet.js";

const { window } = dom;

/**
 * The real stylesheet, in the document.
 *
 * Only the menu's own colour and separator rules are read out of it, and they
 * are read by resolving them -- `getComputedStyle` on a rendered item -- rather
 * than by matching the stylesheet's text. Matching text would pass while the
 * rule lost the cascade, which is precisely the bug these were written for: the
 * danger colour was present in the file the whole time and never once applied.
 *
 * `tsc` emits the tests to `.tmp/` and copies no other file, so the stylesheet
 * is one directory up from the compiled module.
 */
const stylesheet = window.document.createElement("style");
const STYLESHEET = readStylesheet();
stylesheet.textContent = STYLESHEET;
window.document.head.appendChild(stylesheet);

function conversation(over: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    id: "a".repeat(32),
    title: "Original title",
    project: "",
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    message_count: 3,
    ...over,
  };
}

interface Handlers {
  onDismiss: () => void;
  onChooseProject: () => void;
  onOpen: (id: string) => void;
  onDelete: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDuplicate: (id: string) => void;
  // The rail's actions, which the panel carries in its foot while it covers
  // the rail. Rendered only; their disabled logic mirrors `IconRail`.
  onSearch: () => void;
  onSettings: () => void;
}

let calls: Handlers & {
  renamed: [string, string][];
  opened: string[];
  deleted: string[];
  duplicated: string[];
  picks: number;
  dismissals: number;
};

/** Mount the list. Cleaned up after each test by the shared harness. */
async function renderList(
  rows: ConversationSummary[],
  active = "",
  open = true,
  project = "",
): Promise<HTMLElement> {
  calls = {
    onDismiss: () => {
      calls.dismissals += 1;
    },
    onChooseProject: () => {
      calls.picks += 1;
    },
    onOpen: (id) => {
      calls.opened.push(id);
    },
    onDelete: (id) => {
      calls.deleted.push(id);
    },
    onRename: (id, title) => {
      calls.renamed.push([id, title]);
    },
    onDuplicate: (id) => {
      calls.duplicated.push(id);
    },
    onSearch: () => {},
    onSettings: () => {},
    renamed: [],
    opened: [],
    deleted: [],
    duplicated: [],
    picks: 0,
    dismissals: 0,
  };

  return render(
    <ConversationList
      open={open}
      conversations={rows}
      active={active}
      project={project}
      busy={false}
      connected
      pane="chats"
      onPaneChange={() => {}}
      files={[]}
      fileChanges={new Map()}
      fileFilter=""
      onFileFilterChange={() => {}}
      onChooseFolder={() => {}}
      onOpenFile={() => {}}
      hasProject={false}
      {...calls}
    />,
  );
}

const rows = (container: HTMLElement) => all(container, ".chatrow");
const titles = (container: HTMLElement) => texts(container, ".chatrow-title");
const input = (container: HTMLElement) =>
  one(container, ".chatrow-input") as HTMLInputElement | null;

const menuItems = () =>
  texts(document.body, ".rowmenu [role='menuitem']");

// --- the head ----------------------------------------------------------------
describe("the sidebar's head", () => {
  test("carries the toggle and no logo", async () => {
    // The app's mark is the *window's*, and it lives in the title bar's top-left
    // corner now. This head is only on screen while the panel is open, so a mark
    // here was a logo that came and went with a panel -- and the wordmark beside
    // it went too, because the tab up there already says "TONYAgent" whenever no
    // conversation is open.
    const container = await renderList([conversation()]);
    const head = one(container, ".chatlist-head")!;

    assert.deepEqual(
      [...head.children].map((element) => element.className.split(" ")[0]),
      ["chatlist-toggle"],
    );
    assert.equal(one(container, ".chatlist-brand"), null);
  });
});

// --- the foot ----------------------------------------------------------------
describe("the sidebar's foot", () => {
  test("carries the rail's actions, and no delete-a-chat button", async () => {
    // Clear was the third -- a trash glyph beside Search and Settings -- and it
    // read as "delete this chat", which is not what it did: it emptied the
    // transcript you were reading and left the conversation in the list.
    // Deleting a conversation is the row menu's Delete, which names the row it
    // acts on. Asserted as an absence, like the head's test above: the failure
    // is the button being there again.
    const container = await renderList([conversation()]);
    const labels = all(container, ".chatlist-act").map((b) =>
      b.getAttribute("aria-label"),
    );

    assert.deepEqual(labels, ["Search project", "Settings"]);
    assert.equal(
      one(container, '.chatlist-act[aria-label="Clear conversation"]'),
      null,
      "the delete-a-chat button is back in the foot",
    );
    // And no unnamed third control by another name: the foot is exactly the two
    // buttons the rail also carries.
    assert.equal(all(container, ".chatlist-foot button").length, 2);
  });
});


// --- the panel's own state ------------------------------------------------
describe("the panel reports which way it is moving", () => {
  test("open says so on the node, not by being absent", async () => {
    // The panel is an overlay with an enter and an exit, and both are CSS
    // animations keyed off `data-state`. So "open" cannot mean "the node is
    // there": a node that only exists while open has no closed state to animate
    // out of, and the exit would be a cut however long the keyframe claimed to
    // run. Asserted on the attribute because that is the whole contract the
    // stylesheet has.
    const container = await renderList([conversation()]);
    assert.equal(one(container, ".chatlist")!.dataset.state, "open");
  });

  test("choosing a conversation reports it and leaves closing to the parent", async () => {
    // The panel closes when you pick a conversation, and it has to close *from
    // the outside*. A list that unmounted itself would delete the node holding
    // the caret mid-press and, worse, leave no box for the exit animation to
    // play -- the close would be a cut. So this asserts both halves: `onOpen`
    // fires, and the panel is still there afterwards, still open.
    const container = await renderList([conversation({ title: "Chosen" })]);
    await click(one(container, ".chatrow-open")!);
    assert.deepEqual(calls.opened, [conversation().id]);
    assert.equal(one(container, ".chatlist")!.dataset.state, "open");
    assert.deepEqual(titles(container), ["Chosen"]);
  });

  test("a closing panel keeps its rows, and says closed while it does", async () => {
    // Same reason the row menu retains its items: a panel that emptied itself
    // on close would visibly collapse from nothing on its way out, which reads
    // as the animation announcing its own bug.
    const container = await renderList([conversation()]);
    const list = one(container, ".chatlist")!;
    await rerender(
      <ConversationList
        open={false}
        conversations={[conversation()]}
        active=""
        project=""
        busy={false}
        connected
        pane="chats"
        onPaneChange={() => {}}
        files={[]}
        fileChanges={new Map()}
        fileFilter=""
        onFileFilterChange={() => {}}
        onChooseFolder={() => {}}
        onOpenFile={() => {}}
        hasProject={false}
        {...calls}
      />,
    );
    assert.equal(one(container, ".chatlist"), list, "the node was replaced on close");
    assert.equal(list.dataset.state, "closed");
    assert.deepEqual(titles(container), ["Original title"]);
  });
});

// --- the scrim -------------------------------------------------------------
describe("the scrim behind the panel", () => {
  test("it says which way it is moving, like the panel it dims", async () => {
    // The scrim is a CSS-animated surface, so "open" cannot mean "the node is
    // there": a node that only exists while open has no closed state to fade
    // out of. Same `data-state` contract as the `.chatlist` it dims.
    const container = await renderList([conversation()]);
    assert.equal(one(container, ".chatlist-scrim")!.dataset.state, "open");

    await rerender(
      <ConversationList
        open={false}
        conversations={[conversation()]}
        active=""
        project=""
        busy={false}
        connected
        pane="chats"
        onPaneChange={() => {}}
        files={[]}
        fileChanges={new Map()}
        fileFilter=""
        onFileFilterChange={() => {}}
        onChooseFolder={() => {}}
        onOpenFile={() => {}}
        hasProject={false}
        {...calls}
      />,
    );
    assert.equal(one(container, ".chatlist-scrim")!.dataset.state, "closed");
  });

  test("clicking it asks the window to put the panel away", async () => {
    // The dismiss belongs to the window, not to this component: the panel's
    // lifetime already does, and a list that closed itself would delete the
    // node the exit animation is supposed to play on.
    const container = await renderList([conversation()]);
    await click(one(container, ".chatlist-scrim")!);
    assert.equal(calls.dismissals, 1, "the scrim did not ask to be dismissed");
  });

  test("and it is not a tab stop, because it is a dismiss and not a control", async () => {
    // A full-window backdrop in the tab order is the thing a keyboard user has
    // to tab past to reach the rail's Stop button, and it is reachable already
    // through the rail toggle and Escape.
    const container = await renderList([conversation()]);
    const scrim = one(container, ".chatlist-scrim") as HTMLButtonElement;
    assert.equal(scrim.tabIndex, -1);
    assert.equal(scrim.getAttribute("aria-label"), "Close conversations");
  });
});

async function rightClick(row: HTMLElement): Promise<void> {
  await contextMenu(row);
}

async function chooseMenuItem(label: string): Promise<void> {
  const item = all(document.body, ".rowmenu [role='menuitem']").find(
    (n) => n.textContent === label,
  );
  assert.ok(item, `no "${label}" in the menu`);
  await click(item);
}

async function openEditor(container: HTMLElement, index = 0): Promise<HTMLInputElement> {
  await rightClick(rows(container)[index]);
  await chooseMenuItem("Rename");
  const field = input(container);
  assert.ok(field, "Rename did not open an editor");
  return field;
}

// --- the menu -------------------------------------------------------------
describe("the row menu", () => {
  test("a right-click offers rename, duplicate and delete", async () => {
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    assert.deepEqual(menuItems(), ["Rename", "Duplicate", "Delete"]);
  });

  test("it opens on the row that was clicked, not the first one", async () => {
    const first = conversation();
    const second = conversation({ id: "b".repeat(32), title: "Second" });
    const container = await renderList([first, second]);
    await rightClick(rows(container)[1]);
    await chooseMenuItem("Duplicate");
    assert.deepEqual(calls.duplicated, [second.id]);
  });

  test("the ... button opens the same menu, for anyone not holding a mouse", async () => {
    const container = await renderList([conversation()]);
    const more = one(container, ".chatrow-more");
    assert.ok(more, "the row has no keyboard-reachable trigger");
    await click(more);
    assert.deepEqual(menuItems(), ["Rename", "Duplicate", "Delete"]);
  });

  test("escape closes it without acting", async () => {
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    await press("Escape");
    // Dismissed, but still in the tree: it has to be, or there is nothing for
    // the exit animation to play and the menu would only ever be able to
    // appear. "Closed" is a state, not an absence.
    assert.equal(one(document.body, ".rowmenu")!.dataset.state, "closed");
    assert.deepEqual(calls.renamed, []);
    assert.deepEqual(calls.deleted, []);
    await wait(exitDurationMs() + 60);
    assert.equal(one(document.body, ".rowmenu"), null);
  });

  test("pressing elsewhere closes it", async () => {
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    assert.ok(one(document.body, ".rowmenu"));
    await pointerDown(window.document.body);
    assert.equal(one(document.body, ".rowmenu")!.dataset.state, "closed");
    await wait(exitDurationMs() + 60);
    assert.equal(one(document.body, ".rowmenu"), null);
  });

  test("a closing menu keeps its items, so the exit does not empty itself", async () => {
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    await press("Escape");
    // The anchor and the items are both still there after dismissal. A menu
    // that dropped its contents on close would visibly collapse to nothing
    // while fading, which is the animation announcing its own bug.
    assert.deepEqual(menuItems(), ["Rename", "Duplicate", "Delete"]);
  });

  test("an open menu is not inert, a closing one is", async () => {
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    assert.equal(one(document.body, ".rowmenu")!.dataset.state, "open");
    // The real guard is in the stylesheet, but the attribute that drives it is
    // the half of that contract this side owns.
    await press("Escape");
    assert.equal(one(document.body, ".rowmenu")!.dataset.state, "closed");
  });

  test("Delete is the only item painted in the danger colour", async () => {
    // Resolved through the real stylesheet rather than asserted on the rule's
    // text, because the rule existing is not the same as the rule winning. It
    // was written as a bare `.rowmenu-danger`, and the rule it has to beat is
    // `.rowmenu button` -- one class plus one element, strictly more specific
    // than a single class -- so it lost wherever it sat and Delete rendered in
    // exactly the grey of its two neighbours. Measured in the packaged app
    // before the fix: `rgb(122, 122, 122)`, same as Rename.
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    const items = all(document.body, ".rowmenu [role='menuitem']");
    const colour = (label: string) =>
      dom.window.getComputedStyle(items.find((n) => n.textContent === label)!).color;

    assert.equal(colour("Delete"), "var(--danger)");
    // The other two must not have picked it up, or "the danger item" means
    // nothing: the whole point is that it is the one that differs.
    assert.equal(colour("Rename"), "var(--fg-mute)");
    assert.equal(colour("Duplicate"), "var(--fg-mute)");
  });

  test("Delete is set apart from the harmless items", async () => {
    // A control that destroys something should not sit flush against the ones
    // that do not, and the app's own separator token is what says "a different
    // kind of thing" everywhere else in this file.
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    const items = all(document.body, ".rowmenu [role='menuitem']");
    const deleteStyle = dom.window.getComputedStyle(items.find((n) => n.textContent === "Delete")!);
    const duplicateStyle = dom.window.getComputedStyle(items.find((n) => n.textContent === "Duplicate")!);

    // The gap is the part jsdom can resolve, and it is the part that proves the
    // danger rule is *winning*: `margin-top` is a longhand, so it survives the
    // cascade here, while a `.rowmenu-danger` written as a bare class would
    // resolve to nothing at all.
    assert.ok(
      Number.parseFloat(deleteStyle.marginTop) > 0,
      `Delete has no gap above it, so the danger rule is not winning: ${deleteStyle.marginTop}`,
    );
    // jsdom reports a computed zero length as `"0"` rather than `"0px"`, so this
    // is compared numerically rather than as a string to keep it honest.
    assert.equal(Number.parseFloat(duplicateStyle.marginTop) || 0, 0);

    // The divider itself is NOT checked here, and the reason is worth recording:
    // jsdom's CSS parser drops any shorthand containing `var()`, so
    // `border-top: 1px solid var(--border-soft)` computes to nothing however
    // correctly the cascade would resolve it. Asserting it would either fail
    // for the wrong reason or, worse, pass against an empty string. It is read
    // out of the stylesheet here and checked on the rendered menu in the real
    // browser instead.
    const dangerRule = /\.rowmenu button\.rowmenu-danger\s*\{([^}]*)\}/.exec(STYLESHEET);
    assert.ok(dangerRule, "the destructive item's rule is missing from the stylesheet");
    assert.match(
      dangerRule[1],
      /border-top:\s*1px solid var\(--border-soft\)/,
      `the divider is not the app's own token: ${dangerRule[1].trim()}`,
    );
  });

  test("hovering a menu item is not the same as selecting a conversation", async () => {
    // `--raised` is the selected-row colour, so the hover rule was painting a
    // hovered menu item identically to the conversation the user had chosen --
    // a menu that read as selected. Nine other rules use `--hover` for this,
    // and `--hover` is what the chat rows themselves use.
    //
    // Read from the stylesheet rather than computed, because jsdom cannot
    // resolve `:hover` at all -- there is no pointer, so the rule never matches
    // and a computed assertion would pass against anything.
    const hoverRule = /\.rowmenu button:hover[^{]*\{([^}]*)\}/.exec(STYLESHEET);
    assert.ok(hoverRule, "the menu hover rule is missing from the stylesheet");
    assert.match(
      hoverRule[1],
      /background:\s*var\(--hover\)/,
      `a hovered menu item is not using --hover: ${hoverRule[1].trim()}`,
    );
    assert.ok(
      !/background:[^;]*var\(--raised\)/.test(hoverRule[1]),
      "a hovered menu item is painted like a selected conversation row",
    );
  });

  test("a menu re-opened after a full close targets the right row", async () => {
    const first = conversation();
    const second = conversation({ id: "b".repeat(32), title: "Second" });
    const container = await renderList([first, second]);
    await rightClick(rows(container)[0]);
    await press("Escape");
    await wait(exitDurationMs() + 60);
    assert.equal(one(document.body, ".rowmenu"), null, "the first menu never went away");

    // The window listeners that dismiss the menu are torn down and rebuilt
    // around `openMenuAt`, so a stale one cannot survive to close the second
    // menu on its way in.
    await rightClick(rows(container)[1]);
    await chooseMenuItem("Duplicate");
    assert.deepEqual(calls.duplicated, [second.id]);
  });

  test("delete removes the row it was opened on", async () => {
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    await chooseMenuItem("Delete");
    assert.deepEqual(calls.deleted, [conversation().id]);
  });

  test("pressing a menu item is not a press elsewhere", async () => {
    // The same unguarded capture-phase `pointerdown` the model menu and the
    // budget popover had: it fired on the way *down*, for presses that landed
    // inside the menu, so a press on an item closed the menu underneath the
    // item that was being pressed.
    //
    // `data-state` rather than presence, because a closed menu is still in the
    // tree so the exit has something to animate.
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    const item = all(document.body, ".rowmenu [role='menuitem']")[0];
    await pointerDown(item);
    assert.equal(
      one(document.body, ".rowmenu")!.dataset.state,
      "open",
      "pressing a menu item dismissed the menu it was in",
    );
  });

  test("the item behind that press still acts", async () => {
    // The consequence of the previous one, and the reason it matters: a press
    // that closes the menu is a press whose click lands on a menu that is on its
    // way out. Asserting the action, not just the state, is what proves the
    // handler is being believed.
    const container = await renderList([conversation()]);
    await rightClick(rows(container)[0]);
    const item = all(document.body, ".rowmenu [role='menuitem']")[1];
    await pointerDown(item);
    await click(item);
    assert.deepEqual(calls.duplicated, [conversation().id]);
  });
});

// --- the inline editor ----------------------------------------------------
describe("renaming a conversation", () => {
  test("it opens holding the current title, focused", async () => {
    const container = await renderList([conversation({ title: "What I said" })]);
    const field = await openEditor(container);
    assert.equal(field.value, "What I said");
    assert.equal(window.document.activeElement, field);
    assert.equal(one(container, ".chatrow-title"), null);
  });

  test("enter saves the new title and closes the editor", async () => {
    const container = await renderList([conversation()]);
    const field = await openEditor(container);
    await setValue(field, "Invoice questions");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, [[conversation().id, "Invoice questions"]]);
    assert.equal(input(container), null);
  });

  test("blur saves too, because clicking away is also finishing", async () => {
    const container = await renderList([conversation()]);
    const field = await openEditor(container);
    await setValue(field, "Clicked away");
    await blur(field);
    assert.deepEqual(calls.renamed, [[conversation().id, "Clicked away"]]);
    assert.equal(input(container), null);
  });

  test("surrounding whitespace is trimmed off the name", async () => {
    const container = await renderList([conversation()]);
    const field = await openEditor(container);
    await setValue(field, "   Padded   ");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, [[conversation().id, "Padded"]]);
  });

  test("escape abandons the edit and keeps the old title", async () => {
    const container = await renderList([conversation({ title: "Keep me" })]);
    const field = await openEditor(container);
    await setValue(field, "Discarded");
    await press("Escape", field);
    assert.deepEqual(calls.renamed, []);
    assert.equal(input(container), null);
    assert.deepEqual(titles(container), ["Keep me"]);
  });

  test("a blank name is refused and what was typed is not thrown away", async () => {
    const container = await renderList([conversation({ title: "Untouched" })]);
    const field = await openEditor(container);
    await setValue(field, "");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, [], "a blank name must not be saved");
    assert.ok(input(container), "the editor closed on a refused name");
    assert.equal((input(container) as HTMLInputElement).value, "");
  });

  test("a name of only spaces is refused the same way", async () => {
    const container = await renderList([conversation({ title: "Untouched" })]);
    const field = await openEditor(container);
    await setValue(field, "   \t  ");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, [], "a blank name must not be saved");
    assert.ok(input(container), "the editor closed on a refused name");
    assert.deepEqual(titles(container), []);
  });

  test("a refused name does not silently fall back to the old one", async () => {
    /**
     * The failure this guards: closing the editor and leaving the old title on
     * screen. That looks exactly like a rename that worked, and the user has no
     * way to tell their name was dropped.
     */
    const container = await renderList([conversation({ title: "Untouched" })]);
    const field = await openEditor(container);
    await setValue(field, "  ");
    await press("Enter", field);
    assert.ok(input(container), "the row fell back to the old title");
    assert.equal(one(container, ".chatrow-title"), null);
  });

  test("escape after a refused name still cancels cleanly", async () => {
    const container = await renderList([conversation({ title: "Untouched" })]);
    const field = await openEditor(container);
    await setValue(field, "");
    await press("Enter", field);
    await press("Escape", field);
    assert.deepEqual(calls.renamed, []);
    assert.deepEqual(titles(container), ["Untouched"]);
  });

  test("a name in another language survives the round trip", async () => {
    const container = await renderList([conversation()]);
    const field = await openEditor(container);
    await setValue(field, "코어 동작 설명");
    await press("Enter", field);
    assert.deepEqual(calls.renamed, [[conversation().id, "코어 동작 설명"]]);
  });
});

// --- one folder at a time ---------------------------------------------------
describe("the list is the current folder's chats", () => {
  // Windows paths, escaped twice. A single backslash here would be an escape
  // sequence that JS eats -- `"\Users"` is `Users` -- and the test would then be
  // filtering on a path no Windows machine has ever produced.
  const TONY = "C:\\Users\\iig2y\\Desktop\\TONYAgent";
  const API = "D:\\work\\api";

  test("only the open folder's conversations are drawn", async () => {
    // The whole change. One folder at a time: the list is the folder the window
    // is working in, not a tree of every folder it has ever been pointed at.
    const container = await renderList(
      [
        conversation({ title: "Alpha work", project: TONY }),
        conversation({ id: "b", title: "Endpoint notes", project: API }),
      ],
      "",
      true,
      TONY,
    );

    assert.deepEqual(titles(container), ["Alpha work"]);
  });

  test("another folder's chats are filtered, not deleted", async () => {
    // They are still in what the core reported -- this is a view of one folder,
    // and changing back to that folder is what brings them back. Asserted on the
    // rule directly, because "not drawn" and "gone" look identical in the DOM
    // and only one of them is acceptable.
    const all = [
      conversation({ title: "Alpha work", project: TONY }),
      conversation({ id: "b", title: "Endpoint notes", project: API }),
    ];

    assert.deepEqual(
      rowsForFolder(all, API).map((c) => c.title),
      ["Endpoint notes"],
    );
    assert.deepEqual(
      rowsForFolder(all, TONY).map((c) => c.title),
      ["Alpha work"],
    );
  });

  test("an empty conversation is not listed until it has a message", async () => {
    // A chat created but not yet said into -- the one the core reuses at boot, or
    // a "+" chat with nothing typed -- is a draft, not a chat. The panel lists a
    // conversation from its first message, which is also what titles the row.
    const all = [
      conversation({ title: "New chat", message_count: 0 }),
      conversation({ id: "b", title: "Real chat", message_count: 1 }),
    ];
    assert.deepEqual(
      rowsForFolder(all, "").map((c) => c.title),
      ["Real chat"],
    );
  });

  test("with no folder open the list is everything", async () => {
    // There is nothing to scope by yet, and the alternative -- showing only the
    // chats that have no folder -- would greet a first run with an empty list
    // while the user's real chats sat behind a folder they had not picked yet.
    const container = await renderList([
      conversation({ title: "Alpha work", project: TONY }),
      conversation({ id: "b", title: "Endpoint notes", project: API }),
      conversation({ id: "c", title: "Old chat", project: "" }),
    ]);

    assert.deepEqual(titles(container), [
      "Alpha work",
      "Endpoint notes",
      "Old chat",
    ]);
  });

  test("the head names the folder, and its tooltip carries the whole path", async () => {
    // Two folders called `api` in different trees are the same label otherwise,
    // and which one is open is not something the user can work out from a name
    // they chose themselves.
    const container = await renderList(
      [conversation({ project: API })],
      "",
      true,
      API,
    );
    const head = one(container, ".chatlist-folder")!;

    assert.deepEqual(texts(container, ".chatlist-folder-name"), ["api"]);
    assert.ok(
      head.title.includes("D:\\work\\api"),
      `the tooltip lost the path: ${head.title}`,
    );
  });

  test("the head is also the way to change the folder", async () => {
    // The picker used to hang off the project group's header, which is gone. The
    // folder is now the only thing above the list, so it is the thing that has
    // to open the picker -- otherwise the chats pane has no way to change
    // folders at all, and the folder is what the whole list is scoped to.
    const container = await renderList(
      [conversation({ project: TONY })],
      "",
      true,
      TONY,
    );
    await click(one(container, ".chatlist-folder")!);

    assert.equal(calls.picks, 1);
  });
});
