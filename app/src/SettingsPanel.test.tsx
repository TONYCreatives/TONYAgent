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
  diagnosticsText,
  sandboxIdentity,
  sandboxMeaning,
  updateMessage,
  type CommandSettings,
  type CoreSettings,
  type DiagnosticsInfo,
  type KeyEntry,
  type ProviderInfo,
  type SandboxSettings,
  type SettingsTab,
  type UpdateAnswer,
  type UpdateDownload,
} from "./SettingsPanel.js";
import { all, blur, click, one, render, setValue, wait } from "./test-render.js";
import type { MotionPreference } from "./motion.js";

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

/**
 * What `settings.get` answers with, in the shape the core sends it.
 *
 * The deny list is short here on purpose: it is a read-out in this panel, so
 * what the tests need from it is that it is drawn and that there is no way to
 * edit it -- not that all fifteen of the core's patterns survive the round trip.
 */
const COMMANDS: CommandSettings = {
  command_allowlist: ["python", "git", "npm"],
  command_allowlist_defaults: ["python", "python3", "node", "npm", "git"],
  command_denylist: ["\\brm\\b[^|;&]*\\s-[a-z]*r[a-z]*", "shutdown"],
};

/** A sandbox that is running and contained, which is what most tests want. */
const SANDBOX: SandboxSettings = {
  type: "auto",
  wsl_distro: "",
  enable_network: false,
  memory_limit: "2g",
  cpu_limit: "2.0",
  defaults: { wsl_distro: "", memory_limit: "2g", cpu_limit: "2.0" },
  runtime: {
    running: true,
    kind: "wsl",
    distro: "Ubuntu-24.04",
    isolated: true,
  },
};

const SETTINGS: CoreSettings = { tools: COMMANDS, sandbox: SANDBOX };

/**
 * What `diagnostics.get` answers with: a frozen build's facts.
 *
 * Frozen on purpose, because that is the shape the card has to name honestly:
 * a source checkout answering `frozen: true` would be the card claiming an
 * installed build it is not.
 */
const DIAGNOSTICS: DiagnosticsInfo = {
  version: "0.3.5",
  author: "Tony Lee",
  python: "3.13.2",
  frozen: true,
  config_path: "C:/Users/someone/AppData/Roaming/TONYAgent/config.toml",
  log_dir: "C:/Users/someone/AppData/Roaming/TONYAgent/logs",
};

/**
 * A core whose settings actually change when written.
 *
 * **The panel re-reads after every write**, on purpose -- a value that changed
 * because the write worked and one that changed because it failed are the same
 * thing to a component that trusts its own copy. So a fake that answered the
 * same payload twice would leave every row exactly as it was and make "it
 * changed" untestable. This is the smallest thing that behaves like the file:
 * take the write, answer with the result.
 */
function core(initial: CoreSettings = SETTINGS) {
  let state = initial;
  const writes: { key: string; value: unknown }[] = [];
  return {
    writes,
    read: async () => state,
    set: async (key: string, value: unknown) => {
      writes.push({ key, value });
      state = applyWrite(state, key, value);
      return null;
    },
  };
}

/** The one-key write, as the config file would apply it. */
function applyWrite(state: CoreSettings, key: string, value: unknown): CoreSettings {
  const tools = state.tools;
  const sandbox = state.sandbox;
  switch (key) {
    case "tools.command_allowlist":
      return {
        ...state,
        tools: {
          ...tools,
          command_allowlist:
            value === null ? [...tools.command_allowlist_defaults] : (value as string[]),
        },
      };
    case "sandbox.type":
      return { ...state, sandbox: { ...sandbox, type: String(value) } };
    case "sandbox.wsl_distro":
      return {
        ...state,
        sandbox: { ...sandbox, wsl_distro: value === null ? "" : String(value) },
      };
    case "sandbox.enable_network":
      return { ...state, sandbox: { ...sandbox, enable_network: value === true } };
    case "sandbox.memory_limit":
      return {
        ...state,
        sandbox: {
          ...sandbox,
          memory_limit:
            value === null ? sandbox.defaults.memory_limit : String(value),
        },
      };
    case "sandbox.cpu_limit":
      return {
        ...state,
        sandbox: {
          ...sandbox,
          cpu_limit: value === null ? sandbox.defaults.cpu_limit : String(value),
        },
      };
    default:
      return state;
  }
}

interface Overrides {
  providers?: ProviderInfo[];
  keys?: KeyEntry[];
  baseUrl?: string;
  connected?: boolean;
  petOpen?: boolean;
  onPet?: () => void;
  motion?: MotionPreference;
  onMotionChange?: (preference: MotionPreference) => void;
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
  settings?: CoreSettings | null;
  onReadSettings?: () => Promise<CoreSettings | null>;
  onSetSetting?: (key: string, value: unknown) => Promise<string | null>;
  diagnostics?: DiagnosticsInfo | null;
  onReadDiagnostics?: () => Promise<DiagnosticsInfo | null>;
  onCopyDiagnostics?: (text: string) => Promise<boolean>;
  onOpenLogFolder?: () => void;
  initialTab?: SettingsTab;
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
      motion={overrides.motion ?? "system"}
      onMotionChange={overrides.onMotionChange ?? noop}
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
      onReadSettings={overrides.onReadSettings ?? (async () => overrides.settings ?? SETTINGS)}
      onSetSetting={overrides.onSetSetting ?? (async () => null)}
      onReadDiagnostics={
        overrides.onReadDiagnostics ??
        (async () => (overrides.diagnostics !== undefined ? overrides.diagnostics : DIAGNOSTICS))
      }
      onCopyDiagnostics={overrides.onCopyDiagnostics ?? (async () => true)}
      onOpenLogFolder={overrides.onOpenLogFolder ?? noop}
      initialTab={overrides.initialTab}
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
  one(el, ".settings-key-actions .btn") as HTMLButtonElement;
// One provider's rows in the shared stored list. Groups, not sections: the
// tab draws one Stored section with a labelled group per provider that has
// rows, so a provider with nothing stored is absent rather than empty.
const group = (el: HTMLElement, label: string) =>
  all(el, ".settings-key-group").find(
    (g) => (one(g, ".settings-key-provider")?.textContent ?? "").trim() === label,
  )!;
// The add form, once opened. Absent until the button below is pressed: one
// form names its provider up front instead of N forms, one per provider.
const addForm = (el: HTMLElement) => one(el, ".settings-key-new");
const openAddForm = async (container: HTMLElement) => {
  await click(
    all(container, ".btn").find((b) => (b.textContent ?? "").trim() === "Add new API key")!,
  );
  await wait(0);
};
const addProvider = (el: HTMLElement) =>
  one(el, '[aria-label="Provider for the new key"]') as HTMLSelectElement;

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
    //
    // Behavior carries a second group now -- the command allow-list, which is
    // the list the ladder's ceiling is checked against. It is still the first
    // heading, so the panel still opens on the permissions.
    const container = await render(panel());

    assert.deepEqual(headings(container), ["Permission", "Commands"]);
    assert.equal(
      one(container, ".settings-key-new"),
      null,
      "a section behind another tab is mounted anyway",
    );
  });

  test("the Keys tab is one stored list, one add form, and nothing to pick a model with", async () => {
    const container = await opened();

    assert.deepEqual(headings(container), ["Stored keys", "Add a key", "Base URL"]);
    assert.deepEqual(names(group(container, "OpenRouter")), ["default", "work"]);
    assert.deepEqual(names(group(container, "OpenCode Go")), ["go"]);
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

  test("a directed open lands on the tab it names", async () => {
    // Sending with no provider opens Keys: the tab is read once as the
    // initial one, so the panel still opens on Behavior for everyone else.
    const container = await render(panel({ initialTab: "keys" }));
    await wait(0);

    assert.deepEqual(
      all(container, ".settings-tab")
        .filter((b) => b.getAttribute("aria-selected") === "true")
        .map((b) => (b.textContent ?? "").trim()),
      ["Keys"],
    );
    assert.deepEqual(headings(container), ["Stored keys", "Add a key", "Base URL"]);
  });
});

/**
 * The page's shape, which is what the stylesheet's rules are actually about.
 *
 * These are not cosmetic assertions: each one is the markup half of a CSS rule
 * that decides where the way out ends up, and a stylesheet cannot hold a control
 * still that is nested inside the thing it is meant to sit outside of.
 */
describe("the page's own shape", () => {
  test("the way out is in the nav, outside the scrolling body", async () => {
    // `.settings-body` is the scroller and the nav is a column of its own beside
    // it, which is what keeps the exit reachable however long the section is.
    // That holds only while the two are *siblings*: a back control nested inside
    // the body would scroll away with the content, which is the mid-page Close
    // this replaced.
    const container = await render(panel());
    const body = one(container, ".settings-body")!;
    const back = one(container, ".settings-back")!;
    const nav = one(container, ".settings-nav")!;

    assert.equal(body.contains(back), false, "the way out scrolls with the content");
    assert.equal(nav.contains(back), true, "the way out is not in the nav");
    assert.equal(nav.contains(body), false, "the body is inside the nav");
  });

  test("the section bodies share one scroller rather than one each", async () => {
    // A scroller per section would take the scroll position of the last one with
    // it.
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
      ["Permission", "Commands"],
      "the panel stopped opening on the permissions",
    );

    await click(tab(container, "App"));
    // Three sections, and the third is why the tab is called App rather than
    // Window: the version, the update check and the diagnostics are about the
    // program, the same kind of setting as the card, and none is a property of
    // the agent.
    assert.deepEqual(headings(container), ["Desktop pet", "Motion", "Version", "Diagnostics"]);
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

describe("the Motion menu, from the settings pane", () => {
  const menu = (container: HTMLElement) =>
    one(section(container, "Motion"), '[aria-label="Motion"]') as HTMLSelectElement;

  test("it shows the window's current choice", async () => {
    const container = await render(panel({ motion: "full" }));
    await click(tab(container, "App"));

    assert.equal(menu(container).value, "full");
  });

  test("choosing asks the window, which applies it", async () => {
    const asked: MotionPreference[] = [];
    const container = await render(panel({ onMotionChange: (next) => asked.push(next) }));
    await click(tab(container, "App"));

    await setValue(menu(container), "reduced");

    assert.deepEqual(asked, ["reduced"]);
  });

  test("it names all three answers, because two would hide the default", async () => {
    // System, Full, Reduced: the menu's job is the override, and an override
    // with no named default is a control that cannot be put back.
    const container = await render(panel());
    await click(tab(container, "App"));

    const options = Array.from(menu(container).querySelectorAll("option")).map((o) => o.value);
    assert.deepEqual(options, ["system", "full", "reduced"]);
  });
});

describe("the stored keys list", () => {
  test("every provider with keys gets its own group and its own rows, from the core", async () => {
    const container = await opened();

    assert.deepEqual(names(group(container, "OpenRouter")), ["default", "work"]);
    assert.deepEqual(names(group(container, "OpenCode Go")), ["go"]);
  });

  test("the active key is a flag, and every other key is offered as a Use", async () => {
    const container = await opened();
    const openrouter = group(container, "OpenRouter");

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

  test("with nothing stored there are no groups, only the hint and the button", async () => {
    const container = await opened({ keys: [] });

    assert.equal(
      all(container, ".settings-key-group").length,
      0,
      "an empty provider still draws a group",
    );
    assert.match(container.textContent ?? "", /No API keys stored yet/);
    assert.ok(
      all(container, ".btn").some(
        (b) => (b.textContent ?? "").trim() === "Add new API key",
      ),
      "a provider with no keys has no way to get one",
    );
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
    const openrouter = group(container, "OpenRouter");

    await click(eyes(openrouter)[1]);
    await wait(0);

    assert.deepEqual(asked, ["openrouter/work"], "the eye asked for the wrong row");
    assert.deepEqual(values(openrouter), ["sk-for-work"]);
  });

  test("a second press puts it away and takes the value out of the DOM", async () => {
    const container = await opened({
      onRevealKey: async (_provider, name) => "sk-for-" + name,
    });
    const openrouter = group(container, "OpenRouter");

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
    const openrouter = group(container, "OpenRouter");

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
    const openrouter = group(container, "OpenRouter");

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
    const openrouter = group(container, "OpenRouter");

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
    const openrouter = group(container, "OpenRouter");

    await click(bins(openrouter)[1]);
    await wait(0);

    assert.deepEqual(removed, ["openrouter/work"], "the bin removed the wrong row");
    assert.deepEqual(names(openrouter), ["default"]);
    assert.match(container.textContent ?? "", /Key removed for openrouter \(work\)/);
  });

  test("a removal the core refused says so rather than looking like it worked", async () => {
    const container = await opened({ onDeleteKey: async () => false });
    const openrouter = group(container, "OpenRouter");

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
    const openrouter = group(container, "OpenRouter");

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
    const openrouter = group(container, "OpenRouter");

    await click(uses(openrouter)[0]);
    await wait(0);

    assert.match(container.textContent ?? "", /Could not activate work/);
    assert.ok(one(rowFor(openrouter, "default"), ".settings-key-flag"));
  });
});

describe("adding a key", () => {
  test("the form is behind one button, not one per provider", async () => {
    const container = await opened();

    assert.equal(addForm(container), null, "the add form is on screen unasked");
    await openAddForm(container);
    assert.ok(addForm(container), "the button did not open the add form");
  });

  test("the form opens on this window's provider", async () => {
    // The panel is opened from a window bound to openrouter, so that is the
    // provider preselected -- the common case needs no touch at all.
    const container = await opened();
    await openAddForm(container);

    assert.equal(addProvider(container).value, "openrouter");
  });

  test("Save waits for a key, and the name alone is not enough", async () => {
    const container = await opened();
    await openAddForm(container);
    const form = addForm(container)!;

    assert.equal(saveButton(form).disabled, true, "Save is offered with nothing typed");
    await setValue(nameField(form, "openrouter"), "personal");
    assert.equal(
      saveButton(form).disabled,
      true,
      "a name with no key is still not a key to save",
    );
    await setValue(keyField(form, "openrouter"), "sk-typed");
    assert.equal(saveButton(form).disabled, false);
  });

  test("Save sends the provider, the name and the key, then puts the form away", async () => {
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
    await openAddForm(container);
    const form = addForm(container)!;

    await setValue(nameField(form, "openrouter"), "personal");
    await setValue(keyField(form, "openrouter"), "sk-typed");
    await click(saveButton(form));
    await wait(0);

    assert.deepEqual(saved, [["openrouter", "personal", "sk-typed"]]);
    // The secret outliving the save is the failure; the form closing is the
    // confirmation. Both are asserted: the field is gone with the form, and
    // the row is there without it.
    assert.equal(addForm(container), null, "the form stayed open after a good save");
    assert.ok(
      names(group(container, "OpenRouter")).includes("personal"),
      "the new row did not appear",
    );
    assert.match(container.textContent ?? "", /Key saved to the system keyring/);
  });

  test("the select sends to the provider it names", async () => {
    const saved: string[][] = [];
    const container = await opened({
      onSaveKey: async (provider, name, key) => {
        saved.push([provider, name, key]);
        return true;
      },
    });
    await openAddForm(container);

    await setValue(addProvider(container), "opencode-go");
    const form = addForm(container)!;
    await setValue(keyField(form, "opencode-go"), "sk-typed");
    await click(saveButton(form));
    await wait(0);

    assert.deepEqual(saved, [["opencode-go", "", "sk-typed"]]);
  });

  test("an empty name means the default slot", async () => {
    const saved: string[][] = [];
    const container = await opened({
      onSaveKey: async (provider, name, key) => {
        saved.push([provider, name, key]);
        return true;
      },
    });
    await openAddForm(container);
    const form = addForm(container)!;

    await setValue(keyField(form, "openrouter"), "sk-typed");
    await click(saveButton(form));
    await wait(0);

    assert.deepEqual(saved, [["openrouter", "", "sk-typed"]]);
  });

  test("switching the select keeps each provider's half-typed draft", async () => {
    const container = await opened();
    await openAddForm(container);

    await setValue(nameField(container, "openrouter"), "personal");
    await setValue(keyField(container, "openrouter"), "sk-typed");
    await setValue(addProvider(container), "opencode-go");

    assert.equal(nameField(container, "opencode-go").value, "");
    assert.equal(keyField(container, "opencode-go").value, "");

    await setValue(addProvider(container), "openrouter");
    assert.equal(nameField(container, "openrouter").value, "personal");
    assert.equal(keyField(container, "openrouter").value, "sk-typed");
  });

  test("Cancel puts the form away and clears the typed key", async () => {
    const container = await opened();
    await openAddForm(container);

    await setValue(nameField(container, "openrouter"), "personal");
    await setValue(keyField(container, "openrouter"), "sk-typed");
    await click(
      all(container, ".settings-key-actions .btn").find(
        (b) => (b.textContent ?? "").trim() === "Cancel",
      )!,
    );
    await wait(0);

    assert.equal(addForm(container), null, "Cancel left the form on screen");
    // Reopening is the only way back to the fields, and the secret must not
    // have survived the trip.
    await openAddForm(container);
    assert.equal(keyField(container, "openrouter").value, "");
  });

  test("a save the core refused keeps the form open and the name for a retry", async () => {
    const container = await opened({ onSaveKey: async () => false });
    await openAddForm(container);
    const form = addForm(container)!;

    await setValue(nameField(form, "openrouter"), "personal");
    await setValue(keyField(form, "openrouter"), "sk-typed");
    await click(saveButton(form));
    await wait(0);

    assert.ok(addForm(container), "a failed save put the form away");
    assert.equal(nameField(container, "openrouter").value, "personal");
    assert.equal(keyField(container, "openrouter").value, "");
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
    // No secret field until the form is asked for: one add form, opened on
    // purpose, and no others.
    assert.equal(all(container, 'input[type="password"]').length, 0);
    await openAddForm(container);
    assert.equal(all(container, 'input[type="password"]').length, 1);
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

    // Still four headings, and no Install among them -- with an update waiting,
    // which is the state that used to add a fifth.
    assert.deepEqual(headings(container), ["Desktop pet", "Motion", "Version", "Diagnostics"]);

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

/**
 * The command allow-list, on the Behavior tab.
 *
 * The list is the one the shell gate checks a command's first word against, so
 * the tests here are about the round trip rather than the drawing: what is sent
 * when a chip is dropped or a name is typed, and that the rows are redrawn from
 * what the core answered rather than from what was typed. The deny list is the
 * security half -- it is a read-out, and there must be no way to cut it from
 * this page.
 */
describe("the command allow-list", () => {
  const group = (container: HTMLElement) => section(container, "Commands")!;
  const chips = (container: HTMLElement) =>
    all(group(container), ".settings-command-name").map((n) => (n.textContent ?? "").trim());
  const drops = (container: HTMLElement) => all(group(container), ".settings-command-drop");
  const field = (container: HTMLElement) =>
    one(group(container), '[aria-label="Add a program to the allow-list"]') as HTMLInputElement;
  const addButton = (container: HTMLElement) =>
    all(group(container), ".btn").find((b) => /^add$/i.test((b.textContent ?? "").trim()))!;
  const restore = (container: HTMLElement) =>
    all(group(container), ".btn").find((b) => /restore defaults/i.test(b.textContent ?? ""));

  /** Mount with a fake core whose writes actually take. */
  async function writable(overrides: Overrides = {}) {
    const fake = core(overrides.settings ?? SETTINGS);
    const container = await render(
      panel({ onReadSettings: fake.read, onSetSetting: fake.set, ...overrides }),
    );
    await wait(0);
    return { container, fake };
  }

  test("it is on Behavior, beside the ladder it is checked against", async () => {
    // Not a tab of its own: the ladder is the ceiling on what a turn may do and
    // this is the list underneath it, so a page that asked "how much may it do"
    // and answered with only the ceiling would be answering half the question.
    const container = await render(panel());
    await wait(0);
    assert.deepEqual(chips(container), ["python", "git", "npm"]);
  });

  test("the list comes from the core rather than from the panel", async () => {
    // A window that drew its own copy would be describing rules nobody is held
    // to -- the same reason `tools.get` reads the session and not the file.
    let asked = 0;
    const container = await render(
      panel({
        onReadSettings: async () => {
          asked += 1;
          return SETTINGS;
        },
      }),
    );
    await wait(0);
    assert.equal(asked, 1, "the group did not read the settings");
    assert.deepEqual(chips(container), ["python", "git", "npm"]);
  });

  test("dropping a chip sends the list without it", async () => {
    const { container, fake } = await writable();
    assert.deepEqual(fake.writes, [], "a write before anything was pressed");

    await click(drops(container)[1]);
    await wait(0);

    assert.deepEqual(fake.writes, [{ key: "tools.command_allowlist", value: ["python", "npm"] }]);
    assert.deepEqual(chips(container), ["python", "npm"]);
  });

  test("a typed name is appended, and the field is cleared when it took", async () => {
    const { container, fake } = await writable();

    await setValue(field(container), "cargo");
    await click(addButton(container));
    await wait(0);

    assert.deepEqual(fake.writes, [
      { key: "tools.command_allowlist", value: ["python", "git", "npm", "cargo"] },
    ]);
    assert.equal(field(container).value, "", "the field kept a name that was added");
    assert.deepEqual(chips(container), ["python", "git", "npm", "cargo"]);
  });

  test("the rows are redrawn from what the core stored, not from what was typed", async () => {
    // The core trims, folds duplicates and refuses a name that could never
    // match, so the panel re-reads instead of patching its own copy. This fake
    // answers with its version of the list rather than the one it was handed.
    const fake = core();
    const container = await render(
      panel({
        onReadSettings: fake.read,
        onSetSetting: async () => {
          await fake.set("tools.command_allowlist", ["python", "git", "npm", "cargo"]);
          return null;
        },
      }),
    );
    await wait(0);

    await setValue(field(container), "  CARGO  ");
    await click(addButton(container));
    await wait(0);

    assert.deepEqual(chips(container), ["python", "git", "npm", "cargo"]);
  });

  test("a refused write says why and keeps the list it had", async () => {
    // For these settings the config file is the store, so a failed write means
    // nothing changed -- unlike the tool budget, which the session holds. The
    // core's own sentence is shown, because it is the one that names the rule.
    const container = await render(
      panel({
        onSetSetting: async () => "'/usr/bin/git' is a path, and the allow-list matches the program's name",
      }),
    );
    await wait(0);

    await setValue(field(container), "/usr/bin/git");
    await click(addButton(container));
    await wait(0);

    assert.deepEqual(chips(container), ["python", "git", "npm"]);
    assert.match(group(container).textContent ?? "", /is a path/i);
    assert.equal(field(container).value, "/usr/bin/git", "the name was thrown away");
  });

  test("Restore defaults sends null, and is offered only when it means something", async () => {
    // Null is *unset*: the key comes out of the file so the core's own list
    // applies, rather than a copy of today's default being frozen into it.
    const { container, fake } = await writable();

    await click(restore(container)!);
    await wait(0);

    assert.deepEqual(fake.writes, [{ key: "tools.command_allowlist", value: null }]);
    assert.deepEqual(chips(container), COMMANDS.command_allowlist_defaults);
    assert.equal(restore(container), undefined, "offered again for a list that is the default");
  });

  test("an empty list is drawn as a state, not as an absence", async () => {
    // "Nothing is allowed" and "the list has not been read" are different
    // claims, and only one of them is about the user's settings.
    const container = await render(
      panel({
        settings: { tools: { ...COMMANDS, command_allowlist: [] }, sandbox: SANDBOX },
      }),
    );
    await wait(0);
    assert.match(group(container).textContent ?? "", /nothing is allowed/i);
    assert.deepEqual(chips(container), []);
  });

  test("the deny list is drawn, and there is no control that edits it", async () => {
    // It is a floor: the core's own patterns plus whatever the file adds, and
    // the file cannot shorten it. A control here would be offering to cut it.
    const container = await render(panel());
    await wait(0);
    const readout = one(group(container), ".settings-denylist")!;

    assert.deepEqual(
      all(readout, "code").map((c) => (c.textContent ?? "").trim()),
      COMMANDS.command_denylist,
    );
    assert.equal(all(readout, "button").length, 0, "the deny list grew an editor");
  });

  test("nothing is read or written while the core is down", async () => {
    const fake = core();
    let asked = 0;
    const container = await render(
      panel({
        connected: false,
        onReadSettings: async () => {
          asked += 1;
          return fake.read();
        },
        onSetSetting: fake.set,
      }),
    );
    await wait(0);

    assert.equal(asked, 0, "the group asked a core that is not running");
    assert.equal(field(container).disabled, true);
    assert.equal((addButton(container) as HTMLButtonElement).disabled, true);
  });
});

/**
 * The sandbox card, on the Project tab.
 *
 * The question it answers is "what am I running in", and the reason it is two
 * halves -- the runtime sentence above, the controls below -- is that the
 * configured type is `auto` on most machines and says nothing about what it
 * resolved to. So the tests are about both: the identity comes from `runtime`
 * rather than from `type`, and each control writes the key it owns.
 */
describe("the sandbox card", () => {
  const group = (container: HTMLElement) => section(container, "Sandbox")!;
  const backend = (container: HTMLElement) =>
    one(group(container), ".settings-select") as HTMLSelectElement;
  const distro = (container: HTMLElement) =>
    one(group(container), '[aria-label="WSL distro"]') as HTMLInputElement;
  const network = (container: HTMLElement) =>
    one(group(container), "input[type='checkbox']") as HTMLInputElement;
  const memory = (container: HTMLElement) =>
    one(group(container), '[aria-label="Container memory limit"]') as HTMLInputElement;
  const cpu = (container: HTMLElement) =>
    one(group(container), '[aria-label="Container CPU limit"]') as HTMLInputElement;
  const identity = (container: HTMLElement) =>
    (one(group(container), ".settings-value")?.textContent ?? "").trim();

  /** Mount, then open the Project tab, with a fake core whose writes take. */
  async function opened(overrides: Overrides = {}) {
    const fake = core(overrides.settings ?? SETTINGS);
    const container = await render(
      panel({ onReadSettings: fake.read, onSetSetting: fake.set, ...overrides }),
    );
    await click(tab(container, "Project"));
    await wait(0);
    return { container, fake };
  }

  test("it sits under the folder it runs against", async () => {
    const container = await render(panel());
    await click(tab(container, "Project"));
    assert.deepEqual(
      all(container, ".settings-group h3").map((h) => (h.textContent ?? "").trim()),
      ["Project folder", "Sandbox"],
    );
  });

  test("the identity names the runtime, not the configured type", async () => {
    // The type is `auto`, which is not an answer. `runtime` is.
    const { container } = await opened();
    assert.equal(identity(container), "Running in WSL (Ubuntu-24.04).");
    assert.equal(backend(container).value, "auto", "the select stopped showing the choice");
  });

  test("a local runtime says so, and says what that costs", async () => {
    // The second sentence is the one that matters: on this runtime the
    // code-execution tools are refused below Full, and a user who is told only
    // "not isolated" has to work out what that means for their tools.
    const container = await render(
      panel({
        settings: {
          tools: COMMANDS,
          sandbox: {
            ...SANDBOX,
            type: "local",
            runtime: { running: true, kind: "local", distro: "", isolated: false },
          },
        },
      }),
    );
    await click(tab(container, "Project"));
    await wait(0);

    assert.equal(identity(container), "Running on this computer, without isolation.");
    assert.match(group(container).textContent ?? "", /unless the permission level is Full/i);
  });

  test("a stopped sandbox is a state, not an empty card", async () => {
    const container = await render(
      panel({
        settings: {
          tools: COMMANDS,
          sandbox: {
            ...SANDBOX,
            runtime: { running: false, kind: "", distro: "", isolated: false },
          },
        },
      }),
    );
    await click(tab(container, "Project"));
    await wait(0);

    assert.equal(identity(container), "Not running.");
    assert.equal(backend(container).value, "auto", "the controls vanished with the runtime");
  });

  test("the identity helpers cover a backend that did not name itself", () => {
    // A backend that reports no kind must not be drawn as stopped: it is
    // running, and the only fact missing is its name.
    const running = { running: true, kind: "", distro: "", isolated: true };
    assert.equal(sandboxIdentity(running), "Running.");
    assert.match(sandboxMeaning(running), /runs in there/i);
    assert.equal(sandboxIdentity(null), "Not running.");
    assert.match(sandboxMeaning(null), /press Start/i);
  });

  test("choosing a backend writes the type", async () => {
    const { container, fake } = await opened();

    await setValue(backend(container), "docker");
    await wait(0);

    assert.deepEqual(fake.writes, [{ key: "sandbox.type", value: "docker" }]);
    assert.equal(backend(container).value, "docker");
  });

  test("a stored backend the list does not offer is still drawn", async () => {
    // `windows` is in the settings model and is a documented stub. Showing it
    // as Automatic would be this page reporting a backend the core is not
    // configured for.
    const { container } = await opened({
      settings: {
        tools: COMMANDS,
        sandbox: { ...SANDBOX, type: "windows" },
      },
    });

    assert.equal(backend(container).value, "windows");
    assert.match(backend(container).textContent ?? "", /not available/i);
  });

  test("the distro field is committed on blur, trimmed, and empty means default", async () => {
    const { container, fake } = await opened();
    assert.equal(
      distro(container).placeholder,
      "Default distro",
      "an empty distro field does not say what empty means",
    );

    await setValue(distro(container), "  Ubuntu-24.04  ");
    distro(container).focus();
    await blur(distro(container));
    await wait(0);
    assert.deepEqual(fake.writes, [
      { key: "sandbox.wsl_distro", value: "Ubuntu-24.04" },
    ]);

    // Nothing is written per keystroke: a half-typed distro is not a choice.
    assert.equal(fake.writes.length, 1);

    await setValue(distro(container), "   ");
    distro(container).focus();
    await blur(distro(container));
    await wait(0);
    assert.deepEqual(fake.writes[1], { key: "sandbox.wsl_distro", value: null });
  });

  test("the network toggle writes a real boolean", async () => {
    // "false" would be a truthy string, which is the one direction this must
    // never fail in -- so the core only takes a bool and the box sends one.
    const { container, fake } = await opened();

    await click(network(container));
    await wait(0);

    assert.deepEqual(fake.writes, [{ key: "sandbox.enable_network", value: true }]);
    assert.equal(network(container).checked, true);
  });

  test("the Docker limits show the values the container would be given", async () => {
    // The effective values, not blank fields with defaults hidden behind them:
    // a cap the user cannot see is a cap they cannot reason about.
    const { container } = await opened();
    assert.equal(memory(container).value, "2g");
    assert.equal(cpu(container).value, "2.0");
  });

  test("clearing a Docker limit puts the core's default back", async () => {
    // `null` is unset, so the core answers with the default -- and the field
    // redraws to it. An empty field is how you say "default"; it does not stay
    // empty, because the effective limit is a number and this card shows what
    // is in force.
    const { container, fake } = await opened({
      settings: { tools: COMMANDS, sandbox: { ...SANDBOX, memory_limit: "4g" } },
    });
    assert.equal(memory(container).value, "4g");

    await setValue(memory(container), "");
    memory(container).focus();
    await blur(memory(container));
    await wait(0);

    assert.deepEqual(fake.writes, [{ key: "sandbox.memory_limit", value: null }]);
    assert.equal(memory(container).value, "2g", "the field did not redraw to the default");
  });

  test("a validation refusal is shown in the core's words", async () => {
    // The sentence names the rule ("a number with a unit"), which is the whole
    // reason the core validates rather than the panel.
    const container = await render(
      panel({
        onSetSetting: async () =>
          "'2' is not a memory limit. Use a number with a unit, such as 2g or 512m.",
      }),
    );
    await click(tab(container, "Project"));
    await wait(0);

    await setValue(memory(container), "2");
    memory(container).focus();
    await blur(memory(container));
    await wait(0);

    assert.match(group(container).textContent ?? "", /number with a unit/i);
    assert.equal(memory(container).value, "2", "the value was lost with the message");
  });

  test("a field adopts the core's spelling again, not the one that was typed", async () => {
    // The fields are uncontrolled, so a half-typed value is never fought over
    // by a re-render; `key` is what makes them adopt the stored value again
    // once it changes. The core lowercases a memory limit, so "4G" comes back
    // "4g".
    const fake = core();
    const container = await render(
      panel({
        onReadSettings: fake.read,
        onSetSetting: async (key, value) => {
          await fake.set(key, String(value).toLowerCase());
          return null;
        },
      }),
    );
    await click(tab(container, "Project"));
    await wait(0);

    await setValue(memory(container), "4G");
    memory(container).focus();
    await blur(memory(container));
    await wait(0);

    assert.equal(memory(container).value, "4g");
  });

  test("it says when a change takes effect", async () => {
    // Every field here is read at `sandbox.start`, so a change to the running
    // one is not a change to the running one. Said once, at the foot.
    const { container } = await opened();
    assert.match(group(container).textContent ?? "", /next time the sandbox starts/i);
  });

  test("the settings are read when Project opens, not per render", async () => {
    let asked = 0;
    const container = await render(
      panel({
        onReadSettings: async () => {
          asked += 1;
          return SETTINGS;
        },
      }),
    );
    const afterMount = asked;
    await click(tab(container, "Project"));
    await wait(0);

    assert.equal(asked, afterMount + 1, "opening Project did not read the settings");
    await click(tab(container, "Keys"));
    await click(tab(container, "Project"));
    await wait(0);
    assert.equal(asked, afterMount + 2);
  });
});


/**
 * A local model on this machine's CPU is a plain chat model.
 *
 * The core only offers it in Chat mode, so the panel has to say what it is
 * rather than leave the user to find out by switching modes and watching the
 * row disappear. It also has to say it needs no key -- the panel is about
 * keys, and a local provider with a key form on it is asking for a secret
 * that does not exist.
 */
describe("a chat-only provider says what it is", () => {
  const LOCAL: ProviderInfo[] = [
    { name: "openrouter", models: ["a/b"], has_credentials: true },
    {
      name: "airllm",
      models: ["Qwen/Qwen2.5-Coder-0.5B-Instruct"],
      has_credentials: false,
      chat_only: true,
    },
  ];

  test("it is named once as keyless, beside the stored list", async () => {
    const container = await opened({ providers: LOCAL });

    const stored = section(container, "Stored keys").textContent ?? "";
    assert.match(stored, /Airllm works in Chat mode only, and needs no API key/);
  });

  test("it takes no key, so the add form does not offer it", async () => {
    const container = await opened({ providers: LOCAL });
    await openAddForm(container);

    const options = Array.from(
      addProvider(container).querySelectorAll("option"),
    ).map((o) => o.value);
    assert.deepEqual(options, ["openrouter"]);
  });

  test("an ordinary provider is not marked that way", async () => {
    const container = await opened({ providers: LOCAL });

    const stored = section(container, "Stored keys").textContent ?? "";
    assert.doesNotMatch(stored, /OpenRouter works in Chat mode only/);
    assert.ok(group(container, "OpenRouter"), "the ordinary provider lost its group");
  });
});

/**
 * The diagnostics card, on the App tab beside the version.
 *
 * "Which build am I running" and "where does it keep its files" are one
 * question read twice, so the card sits under the version it belongs to rather
 * than in a tab of its own. The tests are about the round trip and the text:
 * the facts come from the core, and what gets pasted into an issue has to be
 * exactly what the card shows.
 */
describe("the diagnostics card", () => {
  const group = (container: HTMLElement) => section(container, "Diagnostics")!;
  const copyButton = (container: HTMLElement) =>
    all(group(container), ".btn").find((b) => /copy diagnostics/i.test(b.textContent ?? ""))!;
  const openButton = (container: HTMLElement) =>
    all(group(container), ".btn").find((b) => /open log folder/i.test(b.textContent ?? ""))!;

  /** Mount, then open the App tab, counting what the card asked for. */
  async function opened(overrides: Overrides = {}) {
    let asked = 0;
    const container = await render(
      panel({
        onReadDiagnostics: async () => {
          asked += 1;
          return DIAGNOSTICS;
        },
        ...overrides,
      }),
    );
    const before = asked;
    await click(tab(container, "App"));
    await wait(0);
    return { container, asked: () => asked, before };
  }

  test("it sits under the version it belongs to", async () => {
    const container = await render(panel());
    await click(tab(container, "App"));
    assert.deepEqual(
      all(container, ".settings-group h3").map((h) => (h.textContent ?? "").trim()),
      ["Desktop pet", "Motion", "Version", "Diagnostics"],
    );
  });

  test("nothing is read until the App tab opens", async () => {
    // The panel opens on Behavior, and facts nobody is looking at are not
    // worth a round trip -- the same reason the key list waits for its tab.
    const { asked, before } = await opened();
    assert.equal(before, 0, "the card asked before its tab opened");
    assert.equal(asked(), 1, "opening the App tab did not read the facts");
  });

  test("the card draws the build, the runtime and both paths", async () => {
    const { container } = await opened();
    const text = group(container).textContent ?? "";

    assert.match(text, /TONYAgent 0\.3\.5 by Tony Lee/);
    assert.match(text, /Installed app \(frozen bundle\), Python 3\.13\.2/);
    assert.match(text, /Config: C:\/Users\/someone\/AppData\/Roaming\/TONYAgent\/config\.toml/);
    assert.match(text, /Logs: C:\/Users\/someone\/AppData\/Roaming\/TONYAgent\/logs/);
  });

  test("a source checkout says so instead of claiming a bundle", async () => {
    const container = await render(
      panel({ diagnostics: { ...DIAGNOSTICS, frozen: false } }),
    );
    await click(tab(container, "App"));
    await wait(0);

    assert.match(group(container).textContent ?? "", /From source, Python/);
  });

  test("copying sends the card as text and says so", async () => {
    const copied: string[] = [];
    const { container } = await opened({
      onCopyDiagnostics: async (text) => {
        copied.push(text);
        return true;
      },
    });

    await click(copyButton(container));
    await wait(0);

    assert.equal(copied.length, 1, "the press copied nothing");
    assert.equal(copied[0], diagnosticsText(DIAGNOSTICS));
    assert.match(group(container).textContent ?? "", /Copied\./);
  });

  test("the pasted text is the card, not a second rendering of it", async () => {
    // One rendering, drawn and pasted alike: two copies of these facts are two
    // chances for the issue to say something the card does not.
    assert.equal(
      diagnosticsText(DIAGNOSTICS),
      [
        "TONYAgent 0.3.5 by Tony Lee",
        "Installed app (frozen bundle), Python 3.13.2.",
        "Config: C:/Users/someone/AppData/Roaming/TONYAgent/config.toml",
        "Logs: C:/Users/someone/AppData/Roaming/TONYAgent/logs",
      ].join("\n"),
    );
  });

  test("a copy that failed says so instead of claiming it took", async () => {
    const { container } = await opened({ onCopyDiagnostics: async () => false });

    await click(copyButton(container));
    await wait(0);

    assert.match(group(container).textContent ?? "", /Could not copy to the clipboard\./);
  });

  test("opening the log folder asks the host, not the core", async () => {
    // The folder is opened by the shell around the page, which is the only
    // thing that can reach the file explorer -- so this is a host call, and a
    // test that watched the core's traffic could not see it happen.
    let openedFolder = 0;
    const { container } = await opened({ onOpenLogFolder: () => void (openedFolder += 1) });

    await click(openButton(container));

    assert.equal(openedFolder, 1, "the press never reached the host");
  });

  test("with nothing read there is nothing to copy or open", async () => {
    // "Not read yet" and empty facts are different claims, and the buttons for
    // facts that are not there would be controls that cannot work.
    const container = await render(panel({ diagnostics: null }));
    await click(tab(container, "App"));
    await wait(0);

    assert.match(group(container).textContent ?? "", /Not read yet\./);
    assert.equal((copyButton(container) as HTMLButtonElement).disabled, true);
    assert.equal((openButton(container) as HTMLButtonElement).disabled, true);
  });

  test("nothing is read or offered while the core is down", async () => {
    let asked = 0;
    const container = await render(
      panel({
        connected: false,
        onReadDiagnostics: async () => {
          asked += 1;
          return DIAGNOSTICS;
        },
      }),
    );
    await click(tab(container, "App"));
    await wait(0);

    assert.equal(asked, 0, "the card asked a core that is not running");
    assert.match(group(container).textContent ?? "", /Not read yet\./);
  });
});
