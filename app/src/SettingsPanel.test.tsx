/**
 * The settings pane's own layout, its tabs and its key rows.
 *
 * Model selection is gone from this panel on purpose: it lives in the
 * composer's model chip, and two surfaces for one binding is two surfaces that
 * can disagree. The tests below assert the absence, not just the presence, of
 * the parts that moved out.
 *
 * The reveal tests are the security half. key.reveal is the one method in the
 * whole protocol whose reply carries a secret, and what makes it acceptable is
 * that the value exists only between a press and the press that hides it, and
 * only one row at a time -- which is a claim about this component, not the core.
 *
 * The key rows are named now, which is why every callback takes a provider AND a
 * name: a test that only checked the provider could not tell which of two rows
 * was revealed or deleted.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import {
  SettingsPanel,
  updateMessage,
  type KeyEntry,
  type ProviderInfo,
  type UpdateAnswer,
  type UpdateDownload,
} from "./SettingsPanel.js";
import { all, click, one, render, setValue, wait } from "./test-render.js";

const noop = () => {};

const PROVIDERS: ProviderInfo[] = [
  { name: "openrouter", models: ["a/b"], has_credentials: true },
  { name: "opencode-go", models: ["c/d"], has_credentials: false },
];

const LIST: KeyEntry[] = [
  { provider: "openrouter", name: "default", active: true },
  { provider: "openrouter", name: "work", active: false },
  { provider: "opencode-go", name: "go", active: true },
];

interface Overrides {
  providers?: ProviderInfo[];
  keys?: KeyEntry[];
  baseUrl?: string;
  connected?: boolean;
  petOpen?: boolean;
  onPet?: () => void;
  update?: UpdateAnswer | null;
  updateChecking?: boolean;
  updateFetching?: boolean;
  updateReady?: UpdateDownload | null;
  onCheckUpdate?: (force: boolean) => void;
  onDownloadUpdate?: () => void;
  onInstallUpdate?: () => void;
  onOpenReleases?: () => void;
  onRevealKey?: (provider: string, name: string) => Promise<string | null>;
  onDeleteKey?: (provider: string, name: string) => Promise<boolean>;
  onActivateKey?: (provider: string, name: string) => Promise<boolean>;
  onSaveKey?: (provider: string, name: string, key: string) => Promise<boolean>;
  onListKeys?: (provider?: string) => Promise<KeyEntry[]>;
  onApplyEndpoint?: (url: string) => void;
}

function panel(overrides: Overrides = {}) {
  return (
    <SettingsPanel
      connected={overrides.connected ?? true}
      busy={false}
      providers={overrides.providers ?? PROVIDERS}
      provider="openrouter"
      baseUrl={overrides.baseUrl ?? ""}
      project="C:/x"
      sandbox="stopped"
      trusted={false}
      permissionList={null}
      permission="medium"
      reasoning={null}
      error={null}
      notice={null}
      petOpen={overrides.petOpen ?? false}
      onPet={overrides.onPet ?? noop}
      update={overrides.update ?? null}
      updateChecking={overrides.updateChecking ?? false}
      updateFetching={overrides.updateFetching ?? false}
      updateReady={overrides.updateReady ?? null}
      onCheckUpdate={overrides.onCheckUpdate ?? noop}
      onDownloadUpdate={overrides.onDownloadUpdate ?? noop}
      onInstallUpdate={overrides.onInstallUpdate ?? noop}
      onOpenReleases={overrides.onOpenReleases ?? noop}
      onClose={noop}
      onChooseFolder={noop}
      onStartSandbox={noop}
      onStopSandbox={noop}
      onPermissionChange={noop}
      onReasoningChange={noop}
      onApplyEndpoint={overrides.onApplyEndpoint ?? noop}
      onTrust={noop}
      onSaveKey={overrides.onSaveKey ?? (async () => true)}
      onDeleteKey={overrides.onDeleteKey ?? (async () => true)}
      onRevealKey={overrides.onRevealKey ?? (async () => null)}
      onActivateKey={overrides.onActivateKey ?? (async () => true)}
      onListKeys={overrides.onListKeys ?? (async () => overrides.keys ?? LIST)}
    />
  );
}

const tab = (container: HTMLElement, label: string) =>
  all(container, ".settings-tab").find((b) => (b.textContent ?? "").trim() === label)!;

const headings = (container: HTMLElement) =>
  all(container, ".settings-group h3").map((h) => (h.textContent ?? "").trim());

const section = (container: HTMLElement, title: string) =>
  all(container, ".settings-group").find(
    (g) => (one(g, "h3")?.textContent ?? "").trim() === title,
  )!;

const names = (el: HTMLElement) =>
  all(el, ".settings-key-name").map((n) => (n.textContent ?? "").trim());
const eyes = (el: HTMLElement) => all(el, ".settings-keys .settings-reveal");
const bins = (el: HTMLElement) => all(el, ".settings-keys .settings-unkey");
const uses = (el: HTMLElement) => all(el, ".settings-keys .settings-key-use");
// Text, not the nodes: assert.deepEqual on an HTMLElement walks jsdom's whole
// object graph (ownerDocument and back), which is slow at best and blows the
// heap at worst.
const values = (el: HTMLElement) =>
  all(el, ".settings-key-value").map((c) => (c.textContent ?? "").trim());
const rowFor = (el: HTMLElement, name: string) =>
  all(el, ".settings-key-item").find(
    (li) => (one(li, ".settings-key-name")?.textContent ?? "").trim() === name,
  )!;

const nameField = (el: HTMLElement, provider: string) =>
  one(el, '[aria-label="Name for a new ' + provider + ' key"]') as HTMLInputElement;
const keyField = (el: HTMLElement, provider: string) =>
  one(el, '[aria-label="New API key for ' + provider + '"]') as HTMLInputElement;
const saveButton = (el: HTMLElement) =>
  one(el, ".settings-key-new .settings-key-actions .btn") as HTMLButtonElement;

// The key rows live behind the Keys tab, and the panel opens on Permission.
async function opened(overrides: Overrides = {}) {
  const container = await render(panel(overrides));
  await click(tab(container, "Keys"));
  await wait(0);
  return container;
}

describe("the settings tabs", () => {
  test("it opens on the permission ladder, which is what the panel led with", async () => {
    // The tab is labelled Behavior and the section inside it is Permission: the
    // tab names the page, the heading names the control. See `SETTINGS_TABS`.
    const container = await render(panel());

    assert.deepEqual(headings(container), ["Permission"]);
    assert.equal(
      one(container, ".settings-key-new"),
      null,
      "a section behind another tab is mounted anyway",
    );
  });

  test("the Keys tab is one section per provider, and nothing to pick a model with", async () => {
    const container = await opened();

    assert.deepEqual(headings(container), ["openrouter", "opencode-go", "Base URL"]);
    // The regression this pins: the provider and model pickers used to be here,
    // and a panel that still offered them would be a second place to bind the
    // window's provider while the composer has the first.
    assert.equal(one(container, ".settings-picker"), null, "a picker is still in the panel");
    assert.equal(one(container, '[aria-label="Model"]'), null, "the model picker is still here");
    assert.equal(one(container, '[aria-label="Provider"]'), null, "the provider picker is still here");
  });

  test("there are four, and the pill arithmetic is written for four", async () => {
    // The count is the load-bearing part: the tab strip draws one sliding pill
    // whose width and travel are an arithmetic division of the row. A fifth tab
    // added to the list would put the pill under the wrong label while every test
    // about which tab is *selected* went on passing.
    const container = await render(panel());
    const labels = all(container, ".settings-tab").map((b) =>
      (b.textContent ?? "").trim(),
    );
    assert.deepEqual(labels, ["Behavior", "Project", "Keys", "App"]);
  });

  test("exactly one tab says it is the chosen one", async () => {
    const container = await render(panel());
    const selected = () =>
      all(container, ".settings-tab")
        .filter((b) => b.getAttribute("aria-selected") === "true")
        .map((b) => (b.textContent ?? "").trim());

    assert.deepEqual(selected(), ["Behavior"]);
    await click(tab(container, "Keys"));
    assert.deepEqual(selected(), ["Keys"]);
  });
});

/**
 * The pane's shape, which is what the stylesheet's rules are actually about.
 *
 * These are not cosmetic assertions: each one is the markup half of a CSS rule
 * that decides where the Close button ends up, and a stylesheet cannot pin a row
 * that is nested inside the thing it is meant to sit below.
 */
describe("the pane's own shape", () => {
  test("the foot is outside the scrolling body, so CSS can pin it to the floor", async () => {
    // `.chatlist .settings-modal` makes the body the scroller and leaves the
    // Close row after it in the column, which is what puts the exit on the
    // sidebar's edge on every tab. That holds only while the row is a *sibling*
    // of the body: nested inside it, it would scroll away with the content and
    // the panel would be back to the mid-page Close this replaced.
    const container = await render(panel());
    const body = one(container, ".settings-body")!;
    const actions = one(container, ".modal-actions")!;

    assert.equal(body.contains(actions), false, "the Close row scrolls with the content");
    assert.equal(one(container, ".modal")!.contains(body), true);
  });

  test("the tab bodies share one scroller rather than one each", async () => {
    // A scroller per tab would take the scroll position of the last one with it,
    // and would make the footer's height depend on whichever tab was open.
    const container = await render(panel());
    await click(tab(container, "Keys"));
    assert.equal(all(container, ".settings-body").length, 1);
    assert.ok(one(container, ".settings-body")!.textContent!.includes("Base URL"));
  });
});

describe("the desktop pet, from the settings pane", () => {
  const petBox = (container: HTMLElement) =>
    one(section(container, "Desktop pet"), "input[type='checkbox']") as HTMLInputElement;

  test("it has a tab of its own, away from the permissions", async () => {
    // The pet changes nothing about the agent. Filing it under Permission would
    // put a control on a page whose question it does not answer, and the panel
    // reads as four clear pages only while that stays true.
    const container = await render(panel());
    assert.deepEqual(
      headings(container),
      ["Permission"],
      "the panel stopped opening on the permissions",
    );

    await click(tab(container, "App"));
    // Two sections, and the second is why the tab is called App rather than
    // Window: the version and the update check are about the program, the same
    // kind of setting as the card, and neither is a property of the agent.
    assert.deepEqual(headings(container), ["Desktop pet", "Version"]);
  });

  test("it draws the card's real state, and a press asks for the other one", async () => {
    const asked: number[] = [];
    const container = await render(panel({ petOpen: true, onPet: () => asked.push(1) }));
    await click(tab(container, "App"));

    assert.equal(petBox(container).checked, true, "the box does not show an open card");
    await click(petBox(container));
    assert.equal(asked.length, 1, "pressing it did nothing");
    // **Still checked**, and that is the claim. The box is drawn from what the
    // shell reports, never from the press: a checkbox that flipped itself would
    // claim a card the webview may well have refused to make.
    assert.equal(
      petBox(container).checked,
      true,
      "the box believed the press rather than the shell",
    );
  });

  test("it works with the core stopped, because the card is a window", async () => {
    // Every other control on this panel is disabled without a core. This one is
    // not: the shell can make a window whether or not anything is running, and a
    // card that says "waiting" beside a stopped core is telling the truth.
    const container = await render(panel({ connected: false }));
    await click(tab(container, "App"));

    assert.equal(petBox(container).disabled, false, "a window control was refused without a core");
  });
});

describe("the stored keys list", () => {
  test("every provider gets its own section and its own rows, from the core", async () => {
    const container = await opened();

    assert.deepEqual(names(section(container, "openrouter")), ["default", "work"]);
    assert.deepEqual(names(section(container, "opencode-go")), ["go"]);
  });

  test("the active key is a flag, and every other key is offered as a Use", async () => {
    const container = await opened();
    const openrouter = section(container, "openrouter");

    assert.ok(
      one(rowFor(openrouter, "default"), ".settings-key-flag"),
      "the active key is not marked",
    );
    assert.ok(
      one(rowFor(openrouter, "work"), ".settings-key-use"),
      "a non-active key has no way to become active",
    );
    assert.equal(
      one(rowFor(openrouter, "default"), ".settings-key-use"),
      null,
      "the active key offers to activate itself",
    );
  });

  test("a provider with no keys says so and still offers the add row", async () => {
    const container = await opened({
      keys: [{ provider: "openrouter", name: "default", active: true }],
    });
    const go = section(container, "opencode-go");

    assert.deepEqual(names(go), []);
    assert.match(go.textContent ?? "", /No keys stored for this provider yet/);
    assert.ok(saveButton(go), "a provider with no keys has no way to get one");
  });

  test("it draws no key value until one is asked for", async () => {
    const container = await opened();
    assert.deepEqual(values(container), []);
    assert.equal(one(container, ".settings-key-value"), null);
  });
});

describe("revealing a stored key", () => {
  test("a row's eye fetches exactly that provider's named key", async () => {
    const asked: string[] = [];
    const container = await opened({
      onRevealKey: async (provider, name) => {
        asked.push(provider + "/" + name);
        return "sk-for-" + name;
      },
    });
    const openrouter = section(container, "openrouter");

    await click(eyes(openrouter)[1]);
    await wait(0);

    assert.deepEqual(asked, ["openrouter/work"], "the eye asked for the wrong row");
    assert.deepEqual(values(openrouter), ["sk-for-work"]);
  });

  test("a second press puts it away and takes the value out of the DOM", async () => {
    const container = await opened({
      onRevealKey: async (_provider, name) => "sk-for-" + name,
    });
    const openrouter = section(container, "openrouter");

    await click(eyes(openrouter)[1]);
    await wait(0);
    assert.deepEqual(values(openrouter), ["sk-for-work"]);

    await click(eyes(openrouter)[1]);
    await wait(0);
    assert.deepEqual(values(openrouter), [], "the key outlived the press that showed it");
  });

  test("opening one row closes the row that was already open", async () => {
    const container = await opened({
      onRevealKey: async (_provider, name) => "sk-for-" + name,
    });
    const openrouter = section(container, "openrouter");

    await click(eyes(openrouter)[0]);
    await wait(0);
    await click(eyes(openrouter)[1]);
    await wait(0);

    assert.deepEqual(values(container), ["sk-for-work"], "two keys were on screen at once");
  });

  test("the value goes away when the row it came from is removed", async () => {
    const container = await opened({
      onRevealKey: async (_provider, name) => "sk-for-" + name,
      onDeleteKey: async () => true,
    });
    const openrouter = section(container, "openrouter");

    await click(eyes(openrouter)[0]);
    await wait(0);
    assert.deepEqual(values(openrouter), ["sk-for-default"]);

    await click(bins(openrouter)[0]);
    await wait(0);

    assert.deepEqual(values(container), [], "the key was still on screen after its row was gone");
  });

  test("with nothing stored the eye says so rather than failing silently", async () => {
    const container = await opened({
      onRevealKey: async () => null,
    });
    const openrouter = section(container, "openrouter");

    await click(eyes(openrouter)[0]);
    await wait(0);

    assert.match(container.textContent ?? "", /No key is stored under default/);
  });
});

describe("deleting a stored key", () => {
  test("the bin removes that provider's named key and re-reads the list", async () => {
    const state = { list: LIST.map((row) => ({ ...row })) };
    const removed: string[] = [];
    const container = await opened({
      onListKeys: async () => state.list,
      onDeleteKey: async (provider, name) => {
        removed.push(provider + "/" + name);
        state.list = state.list.filter(
          (row) => !(row.provider === provider && row.name === name),
        );
        return true;
      },
    });
    const openrouter = section(container, "openrouter");

    await click(bins(openrouter)[1]);
    await wait(0);

    assert.deepEqual(removed, ["openrouter/work"], "the bin removed the wrong row");
    assert.deepEqual(names(openrouter), ["default"]);
    assert.match(container.textContent ?? "", /Key removed for openrouter \(work\)/);
  });

  test("a removal the core refused says so rather than looking like it worked", async () => {
    const container = await opened({ onDeleteKey: async () => false });
    const openrouter = section(container, "openrouter");

    await click(bins(openrouter)[0]);
    await wait(0);

    assert.match(container.textContent ?? "", /Could not remove default for openrouter/);
  });
});

describe("activating a stored key", () => {
  test("Use makes that key active, and the flag moves once the list is re-read", async () => {
    const state = { list: LIST.map((row) => ({ ...row })) };
    const asked: string[] = [];
    const container = await opened({
      onListKeys: async () => state.list,
      onActivateKey: async (provider, name) => {
        asked.push(provider + "/" + name);
        state.list = state.list.map((row) =>
          row.provider === provider ? { ...row, active: row.name === name } : row,
        );
        return true;
      },
    });
    const openrouter = section(container, "openrouter");

    await click(uses(openrouter)[0]);
    await wait(0);

    assert.deepEqual(asked, ["openrouter/work"], "Use activated the wrong row");
    assert.ok(one(rowFor(openrouter, "work"), ".settings-key-flag"), "work is not marked active");
    assert.ok(
      one(rowFor(openrouter, "default"), ".settings-key-use"),
      "default did not go back to being a choice",
    );
  });

  test("a refused activation says so and leaves the choice where it was", async () => {
    const container = await opened({ onActivateKey: async () => false });
    const openrouter = section(container, "openrouter");

    await click(uses(openrouter)[0]);
    await wait(0);

    assert.match(container.textContent ?? "", /Could not activate work/);
    assert.ok(one(rowFor(openrouter, "default"), ".settings-key-flag"));
  });
});

describe("adding a key", () => {
  test("Save waits for a key, and the name alone is not enough", async () => {
    const container = await opened();
    const openrouter = section(container, "openrouter");

    assert.equal(saveButton(openrouter).disabled, true, "Save is offered with nothing typed");
    await setValue(nameField(openrouter, "openrouter"), "personal");
    assert.equal(
      saveButton(openrouter).disabled,
      true,
      "a name with no key is still not a key to save",
    );
    await setValue(keyField(openrouter, "openrouter"), "sk-typed");
    assert.equal(saveButton(openrouter).disabled, false);
  });

  test("Save sends the provider, the name and the key, then clears the secret", async () => {
    const state = { list: LIST.map((row) => ({ ...row })) };
    const saved: string[][] = [];
    const container = await opened({
      onListKeys: async () => state.list,
      onSaveKey: async (provider, name, key) => {
        saved.push([provider, name, key]);
        state.list = [
          ...state.list,
          { provider, name: name || "default", active: false },
        ];
        return true;
      },
    });
    const openrouter = section(container, "openrouter");

    await setValue(nameField(openrouter, "openrouter"), "personal");
    await setValue(keyField(openrouter, "openrouter"), "sk-typed");
    await click(saveButton(openrouter));
    await wait(0);

    assert.deepEqual(saved, [["openrouter", "personal", "sk-typed"]]);
    assert.equal(
      keyField(openrouter, "openrouter").value,
      "",
      "the key outlived the save that stored it",
    );
    assert.ok(names(openrouter).includes("personal"), "the new row did not appear");
    assert.match(container.textContent ?? "", /Key saved to the system keyring/);
  });

  test("an empty name means the default slot", async () => {
    const saved: string[][] = [];
    const container = await opened({
      onSaveKey: async (provider, name, key) => {
        saved.push([provider, name, key]);
        return true;
      },
    });
    const openrouter = section(container, "openrouter");

    await setValue(keyField(openrouter, "openrouter"), "sk-typed");
    await click(saveButton(openrouter));
    await wait(0);

    assert.deepEqual(saved, [["openrouter", "", "sk-typed"]]);
  });

  test("the two providers' add rows do not share a draft", async () => {
    const container = await opened();
    const openrouter = section(container, "openrouter");
    const go = section(container, "opencode-go");

    await setValue(nameField(openrouter, "openrouter"), "personal");
    await setValue(keyField(openrouter, "openrouter"), "sk-typed");

    assert.equal(nameField(go, "opencode-go").value, "");
    assert.equal(keyField(go, "opencode-go").value, "");
  });

  test("a save the core refused keeps the name for a retry", async () => {
    const container = await opened({ onSaveKey: async () => false });
    const openrouter = section(container, "openrouter");

    await setValue(nameField(openrouter, "openrouter"), "personal");
    await setValue(keyField(openrouter, "openrouter"), "sk-typed");
    await click(saveButton(openrouter));
    await wait(0);

    assert.equal(nameField(openrouter, "openrouter").value, "personal");
    assert.equal(keyField(openrouter, "openrouter").value, "");
    assert.match(container.textContent ?? "", /Could not save the key/);
  });
});

describe("the Base URL, which is not a model setting", () => {
  test("it prefills from the bound endpoint", async () => {
    const container = await opened({ baseUrl: "https://gateway.internal/v1" });
    const field = one(container, '[aria-label="Base URL"]') as HTMLInputElement;
    assert.equal(field.value, "https://gateway.internal/v1");
  });

  test("applying it sends the trimmed endpoint and nothing else", async () => {
    const applied: string[] = [];
    const container = await opened({ onApplyEndpoint: (url) => applied.push(url) });
    const field = one(container, '[aria-label="Base URL"]') as HTMLInputElement;

    await setValue(field, "  https://gateway.internal/v1  ");
    await click(
      all(container, ".settings-group")
        .find((g) => (one(g, "h3")?.textContent ?? "").trim() === "Base URL")!
        .querySelector(".btn")!,
    );

    assert.deepEqual(applied, ["https://gateway.internal/v1"]);
  });

  test("the key rows are a list and a form, not a second secret field elsewhere", async () => {
    const container = await opened();
    // One key input per provider's add row, and no others.
    assert.equal(all(container, 'input[type="password"]').length, 2);
  });
});

// --- the About tab -----------------------------------------------------------
//
// The one claim this feature must never make is "you are up to date" when the
// check could not run. A failed request has not learned that this version is the
// newest, so every failure has its own wording and none of them say it.
describe("what the update check says", () => {
  const answer = (over: Partial<UpdateAnswer> = {}): UpdateAnswer => ({
    current: "0.1.0",
    latest: "0.2.0",
    tag: "v0.2.0",
    available: false,
    prerelease: false,
    notes: "",
    published_at: "",
    url: "",
    asset: null,
    checked_at: 0,
    cached: false,
    reason: "",
    ...over,
  });

  test("a check that never ran does not claim anything", () => {
    assert.match(updateMessage(null), /not checked/i);
  });

  test("a successful check with nothing new is the only 'up to date'", () => {
    assert.match(updateMessage(answer()), /up to date/i);
    assert.match(updateMessage(answer({ available: true })), /v0\.2\.0 is available/);
  });

  test("every failure has its own wording, and none of them say up to date", () => {
    for (const reason of ["offline", "rate_limited", "not_found", "server", "malformed"]) {
      const said = updateMessage(answer({ reason }));
      assert.ok(said.length > 0, reason);
      assert.doesNotMatch(said, /up to date/i, `${reason} claimed the app was current`);
    }
    assert.match(updateMessage(answer({ reason: "offline" })), /connection/i);
    assert.match(updateMessage(answer({ reason: "not_found" })), /private|renamed/i);
  });

  test("the About tab shows the version and the answer", async () => {
    const container = await render(panel({ update: answer({ available: true }) }));
    await click(tab(container, "App"));

    const version = section(container, "Version");
    assert.match(version.textContent ?? "", /TONYAgent 0\.1\.0/);
    assert.match(version.textContent ?? "", /v0\.2\.0 is available/);
  });

  test("the installer is only offered once one is downloaded", async () => {
    const withUpdate = answer({
      available: true,
      asset: { name: "TONYAgent-0.2.0.msi", size: 1, digest: "sha256:x", url: "u" },
    });

    const before = await render(panel({ update: withUpdate }));
    await click(tab(before, "App"));
    assert.equal(
      all(before, ".btn").some((b) => /install and restart/i.test(b.textContent ?? "")),
      false,
      "offered to install before anything was downloaded",
    );
    assert.ok(
      all(before, ".btn").some((b) => /download the installer/i.test(b.textContent ?? "")),
    );

    const after = await render(
      panel({
        update: withUpdate,
        updateReady: {
          ok: true,
          reason: "",
          path: "C:/u/TONYAgent-0.2.0.msi",
          name: "TONYAgent-0.2.0.msi",
          size: 1,
        },
      }),
    );
    await click(tab(after, "App"));
    assert.ok(
      all(after, ".btn").some((b) => /install and restart/i.test(b.textContent ?? "")),
    );
  });

  test("the install controls are on the version card, not a card of their own", async () => {
    // It was a second `settings-group` headed Install, and the heading was the
    // problem: "which version am I running" and "do I want the new one" are one
    // question read twice. The second card also only existed while an update
    // did, which is exactly when the first one is being read.
    const withUpdate = answer({
      available: true,
      asset: { name: "TONYAgent-0.2.0.msi", size: 1, digest: "sha256:x", url: "u" },
    });
    const container = await render(
      panel({
        update: withUpdate,
        updateReady: {
          ok: true,
          reason: "",
          path: "C:/u/TONYAgent-0.2.0.msi",
          name: "TONYAgent-0.2.0.msi",
          size: 1,
        },
      }),
    );
    await click(tab(container, "App"));

    // Still two headings, and no Install among them -- with an update waiting,
    // which is the state that used to add the third.
    assert.deepEqual(headings(container), ["Desktop pet", "Version"]);

    // And the press that runs it is inside that card, under the version it
    // belongs to rather than beside a heading of its own.
    const version = section(container, "Version");
    assert.match(version.textContent ?? "", /is downloaded and verified/i);
    assert.ok(
      all(version, ".btn").some((b) => /install and restart/i.test(b.textContent ?? "")),
      "the install button is not on the version card",
    );
  });

  test("while the installer is being fetched, it says so and offers nothing to run", async () => {
    // The fetch now starts on its own, so this is the state the panel is in for
    // the few seconds after a check finds something. Two things have to be true
    // at once: the wait is visible, and there is no button that would run a file
    // that is not verified yet.
    const container = await render(
      panel({
        update: answer({
          available: true,
          asset: { name: "TONYAgent-0.2.0.msi", size: 1, digest: "sha256:x", url: "u" },
        }),
        updateFetching: true,
      }),
    );
    await click(tab(container, "App"));

    const install = section(container, "Version");
    assert.match(install.textContent ?? "", /fetching the installer/i);
    assert.equal(
      all(container, ".btn").some((b) => /install and restart/i.test(b.textContent ?? "")),
      false,
      "offered to install a file that has not arrived",
    );

    const download = all(container, ".btn").find((b) =>
      /downloading/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement | undefined;
    assert.ok(download, "the fetch is not visible anywhere");
    assert.equal(download.disabled, true, "the fetch can be started twice");
  });

  test("a fetch that failed is a retry, not a dead end", async () => {
    // The button is a plain control because it is a retry as often as it is a
    // first attempt: the fetch ran on its own, failed, and this is the way back.
    const container = await render(
      panel({
        update: answer({
          available: true,
          asset: { name: "TONYAgent-0.2.0.msi", size: 1, digest: "sha256:x", url: "u" },
        }),
        updateReady: { ok: false, reason: "offline", path: "", name: "", size: 0 },
      }),
    );
    await click(tab(container, "App"));

    assert.match(container.textContent ?? "", /could not be completed/i);
    const download = all(container, ".btn").find((b) =>
      /download the installer/i.test(b.textContent ?? ""),
    ) as HTMLButtonElement | undefined;
    assert.ok(download, "there is no way to try the download again");
    assert.equal(download.disabled, false, "the retry is disabled, so the failure is final");
  });

  test("a digest mismatch is reported as one, not as a failed download", async () => {
    const container = await render(
      panel({
        update: answer({
          available: true,
          asset: { name: "TONYAgent-0.2.0.msi", size: 1, digest: "sha256:x", url: "u" },
        }),
        updateReady: {
          ok: false,
          reason: "digest",
          path: "",
          name: "TONYAgent-0.2.0.msi",
          size: 0,
        },
      }),
    );
    await click(tab(container, "App"));
    assert.match(container.textContent ?? "", /did not match its published digest/i);
  });

  test("a release with no installer is not offered one", async () => {
    // The check already knows there is no `.msi`, so the button is never drawn
    // -- offering a control that cannot work is what the rest of this panel
    // avoids, and a download that fails later would report it too late.
    const container = await render(panel({ update: answer({ available: true }) }));
    await click(tab(container, "App"));
    assert.match(container.textContent ?? "", /no installer attached/i);
    assert.equal(
      all(container, ".btn").some((b) => /download the installer/i.test(b.textContent ?? "")),
      false,
    );
  });
});
