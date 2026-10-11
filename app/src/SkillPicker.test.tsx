/**
 * The `/` menu: the token, the filter, the rows, and the keys.
 *
 * The keyboard tests mount the real `Composer`, because that is where the keys
 * are handled -- the field owns the caret and the highlight has to follow it.
 * They live here rather than in `Composer.test.tsx` so that everything about
 * `/` is in one file: the token rules, the filter, the rows and the keys are
 * four halves of one behaviour, and a reader looking for "what does Escape do"
 * should not have to know which component happened to subscribe to the event.
 *
 * The two that matter most are the ones about a message that is *not* a
 * command. Enter must still send, because `/usr/local/bin` and `/tmp/x` are
 * things people type into a composer, and a menu that swallowed their Enter
 * would be blocking the message it was supposedly helping with.
 */

import "./test-dom.js";
import assert from "node:assert/strict";
import { describe, test } from "node:test";

import { Composer, type ModeInfo } from "./Composer.js";
import {
  SkillPicker,
  filterSkills,
  slashToken,
  type SkillInfo,
} from "./SkillPicker.js";
import { all, mouseDown, one, press, render, setValue, texts } from "./test-render.js";

const SKILLS: SkillInfo[] = [
  {
    name: "review",
    description: "Review a change for correctness.",
    source: "project",
    path: ".tonyagent/skills/review.md",
  },
  {
    name: "release",
    description: "Cut a release.",
    source: "project",
    path: ".tonyagent/skills/release.md",
  },
  {
    name: "tidy",
    description: "Sort the imports before a review.",
    source: "user",
    path: "C:/Users/me/AppData/Roaming/TONYAgent/skills/tidy.md",
  },
];

const MODES: ModeInfo[] = [
  { name: "build", label: "Build", description: "Anything goes", writes: true },
];

/** Mount a composer with a skill list, recording what it sends and asks for. */
async function composer(skills: SkillInfo[] = SKILLS) {
  const calls = { sent: [] as string[], needed: 0 };
  const container = await render(
    <Composer
      busy={false}
      disabled={false}
      modes={MODES}
      mode="build"
      skills={skills}
      onSkillsNeeded={() => {
        calls.needed += 1;
      }}
      onModeChange={() => {}}
      onSend={(text) => calls.sent.push(text)}
      onCancel={() => {}}
      maxToolCalls={10}
      budgetOpen={false}
      onBudgetOpen={() => {}}
      onBudgetClose={() => {}}
      onBudgetChange={() => {}}
    />,
  );
  const field = one(container, ".composer-inner textarea") as HTMLTextAreaElement;
  return { container, calls, field };
}

describe("the /name token", () => {
  test("a name being typed is a token", () => {
    assert.equal(slashToken("/rev"), "rev");
    assert.equal(slashToken("/"), "");
    assert.equal(slashToken("/Review_2"), "Review_2");
  });

  test("a message that is not a bare command is not one", () => {
    // A space means the name is finished and the arguments have started.
    assert.equal(slashToken("/review the parser"), null);
    // A slash that is not the first character is a path or a fraction.
    assert.equal(slashToken("see /review"), null);
    assert.equal(slashToken("2/3"), null);
    assert.equal(slashToken(""), null);
    // A newline is whitespace too: the command line is one line.
    assert.equal(slashToken("/review\nmore"), null);
  });
});

describe("the filter", () => {
  test("a prefix match leads a description match", () => {
    // "tidy" matches "review" by description, but the name the user is typing
    // towards has to be first.
    assert.deepEqual(
      filterSkills(SKILLS, "rev").map((s) => s.name),
      ["review", "tidy"],
    );
  });

  test("an empty query is the whole list, in the core's order", () => {
    assert.deepEqual(
      filterSkills(SKILLS, "").map((s) => s.name),
      ["review", "release", "tidy"],
    );
  });

  test("nothing matches is an empty list, not everything", () => {
    assert.deepEqual(filterSkills(SKILLS, "zzz"), []);
  });

  test("the list is bounded, and the bound is the limit", () => {
    const many = Array.from({ length: 20 }, (_, i) => ({
      name: `skill-${i}`,
      description: "",
      source: "project",
      path: `x-${i}.md`,
    }));
    assert.equal(filterSkills(many, "").length, 6);
    assert.equal(filterSkills(many, "skill-1", 2).length, 2);
  });
});

describe("the rendered menu", () => {
  test("a row names the skill, its purpose, and its root when not the project's", async () => {
    const c = await render(
      <SkillPicker
        query=""
        matches={SKILLS}
        total={3}
        index={0}
        onPick={() => {}}
        onHover={() => {}}
      />,
    );
    assert.deepEqual(texts(c, ".skills-name"), ["/review", "/release", "/tidy"]);
    assert.deepEqual(texts(c, ".skills-desc"), [
      "Review a change for correctness.",
      "Cut a release.",
      "Sort the imports before a review.",
    ]);
    // Only the user-level skill is labelled: which root a skill came from is
    // worth saying exactly when it is the surprise.
    assert.equal(all(c, ".skills-source").length, 1);
    assert.equal(one(c, ".skills-source")!.textContent, "user");
    assert.equal(all(c, ".skills-item.is-active").length, 1);
  });

  test("the empty state distinguishes no skills from no match", async () => {
    const none = await render(
      <SkillPicker query="" matches={[]} total={0} index={0} onPick={() => {}} onHover={() => {}} />,
    );
    assert.match(one(none, ".skills-empty")!.textContent!, /No skills yet/);

    const noMatch = await render(
      <SkillPicker query="zz" matches={[]} total={3} index={0} onPick={() => {}} onHover={() => {}} />,
    );
    assert.match(one(noMatch, ".skills-empty")!.textContent!, /No skill matches "\/zz"/);
  });

  test("pressing a row picks it", async () => {
    const picked: string[] = [];
    const container = await render(
      <SkillPicker
        query=""
        matches={SKILLS}
        total={3}
        index={0}
        onPick={(skill) => picked.push(skill.name)}
        onHover={() => {}}
      />,
    );
    await mouseDown(all(container, ".skills-item")[1]);
    assert.deepEqual(picked, ["release"]);
  });
});

describe("the composer's keys", () => {
  test("typing a slash opens the menu and asks for the names", async () => {
    const { container, calls, field } = await composer();
    assert.equal(all(container, ".skills-menu").length, 0);

    await setValue(field, "/");

    assert.equal(all(container, ".skills-menu").length, 1);
    assert.equal(all(container, ".skills-item").length, 3);
    assert.equal(calls.needed, 1, "the menu did not ask the core for the list");
    assert.equal(field.getAttribute("aria-activedescendant"), "skill-option-0");
  });

  test("the menu closes as soon as the arguments start", async () => {
    const { container, field } = await composer();
    await setValue(field, "/review ");
    assert.equal(all(container, ".skills-menu").length, 0);
  });

  test("Enter picks the highlighted skill into the field instead of sending", async () => {
    const { container, calls, field } = await composer();
    await setValue(field, "/rel");

    await press("Enter", field);

    assert.deepEqual(calls.sent, [], "Enter sent the message instead of picking");
    assert.equal(field.value, "/release ");
    assert.equal(all(container, ".skills-menu").length, 0);
  });

  test("the arrow keys move the highlight, and Tab picks what it landed on", async () => {
    const { container, field } = await composer();
    await setValue(field, "/re");

    await press("ArrowDown", field);
    assert.equal(
      one(container, ".skills-item.is-active")!.textContent,
      "/releaseCut a release.",
    );

    await press("Tab", field);
    assert.equal(field.value, "/release ");

    // Wrapping: up from the first row lands on the last.
    await setValue(field, "/");
    await press("ArrowUp", field);
    assert.equal(one(container, ".skills-item.is-active")!.textContent, "/tidySort the imports before a review.user");
  });

  test("Escape closes the menu and leaves the text where it was", async () => {
    const { container, calls, field } = await composer();
    await setValue(field, "/review");

    await press("Escape", field);

    assert.equal(all(container, ".skills-menu").length, 0);
    assert.equal(field.value, "/review", "Escape changed the message");
    // And with the menu gone, Enter is a send again -- which is the whole
    // reason Escape exists.
    await press("Enter", field);
    assert.deepEqual(calls.sent, ["/review"]);
  });

  test("Enter still sends when the name matches nothing", async () => {
    // The case that matters: a path typed into a composer is prose, and this
    // must not become the composer refusing to send it.
    const { container, calls, field } = await composer();
    await setValue(field, "/usr/local");

    assert.equal(all(container, ".skills-menu").length, 1, "the menu should still be up");
    assert.equal(all(container, ".skills-item").length, 0);
    assert.match(one(container, ".skills-empty")!.textContent!, /No skill matches/);

    await press("Enter", field);

    assert.deepEqual(calls.sent, ["/usr/local"]);
  });

  test("with no skills installed, Enter sends rather than picking nothing", async () => {
    const { container, calls, field } = await composer([]);
    await setValue(field, "/anything");
    assert.equal(all(container, ".skills-item").length, 0);

    await press("Enter", field);

    assert.deepEqual(calls.sent, ["/anything"]);
  });

  test("a shift-Enter newline is never a pick", async () => {
    const { container, calls, field } = await composer();
    await setValue(field, "/review");
    await press("Enter", field, { shiftKey: true });
    assert.deepEqual(calls.sent, []);
    assert.equal(all(container, ".skills-menu").length, 1, "the menu closed on a newline");
  });

  test("the menu does not open for an ordinary message", async () => {
    const { container, calls, field } = await composer();
    await setValue(field, "what does this project do?");
    assert.equal(all(container, ".skills-menu").length, 0);
    assert.equal(calls.needed, 0);
  });
});
