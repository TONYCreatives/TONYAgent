/**
 * The `/` menu: the saved skills a message may open with.
 *
 * The composer's placeholder has advertised `/` for skills since the beginning,
 * and until now nothing handled it -- the same class of problem as the
 * presentation-only mode pills were. The core resolves `/name` itself (it is
 * the piece that decides what the model is told), so *typing* the command
 * always works; this is the half that makes the name **findable**, which is the
 * half a user needs: a syntax you have to remember exactly is a syntax nobody
 * uses.
 *
 * **It is drawn from the core's own list, never from a local copy.** The store
 * reads the filesystem when it is asked, so a skill the user just added in
 * their editor appears the next time this menu opens, and a name in this menu
 * is a name `run_skill` will accept.
 *
 * **Nothing here filters on its own.** `filterSkills` is called by the
 * composer, because the composer is what has to know which row Enter selects;
 * this component draws what it is handed, so the highlighted row and the row
 * that would be picked cannot be two different rows.
 */

/**
 * How many rows the menu will draw.
 *
 * Six, because the menu opens *upward* over the transcript and a list that
 * covers the conversation is a list the user has to scroll to compare two
 * names. Filtering is what makes six enough: the first keystroke is what
 * narrows twenty skills down to a handful.
 */
export const MAX_SKILL_ROWS = 6;

/** One entry in the `skills.list` reply. */
export interface SkillInfo {
  name: string;
  description: string;
  /** `project` or `user` -- which root the file was found under. */
  source: string;
  path: string;
}

/** The id a row's `aria-activedescendant` points at. */
export function skillOptionId(index: number): string {
  return `skill-option-${index}`;
}

/**
 * The `/name` token being typed, or null when the message is not one.
 *
 * Three rules, and each one is a case that would otherwise misbehave:
 *
 * * the slash must be the **first character** -- a slash mid-sentence is a
 *   path or a fraction, not a command;
 * * the token must hold **no whitespace**, so the menu closes the moment the
 *   user types the space before the arguments;
 * * an empty query is the bare `/`, which opens the full list. That is the
 *   moment a user who has forgotten the names most needs it.
 */
export function slashToken(text: string): string | null {
  if (!text.startsWith("/")) return null;
  if (/\s/.test(text)) return null;
  return text.slice(1);
}

/**
 * The rows matching `query`, name-prefix matches first.
 *
 * Prefix matches lead because they are what the user is typing towards --
 * a description that happens to contain the letters is a worse guess about
 * which row they mean. Order inside each group is the core's, which is
 * project-first, so a project skill shadows a user skill in the list the same
 * way it shadows it in a lookup.
 */
export function filterSkills(
  skills: SkillInfo[],
  query: string,
  limit: number = MAX_SKILL_ROWS,
): SkillInfo[] {
  const wanted = query.trim().toLowerCase();
  if (!wanted) return skills.slice(0, limit);
  const prefix: SkillInfo[] = [];
  const rest: SkillInfo[] = [];
  for (const skill of skills) {
    const name = skill.name.toLowerCase();
    if (name.startsWith(wanted)) prefix.push(skill);
    else if (name.includes(wanted) || skill.description.toLowerCase().includes(wanted)) {
      rest.push(skill);
    }
  }
  return [...prefix, ...rest].slice(0, limit);
}

interface Props {
  /** What has been typed after the slash, for the empty-state wording. */
  query: string;
  matches: SkillInfo[];
  /** How many skills exist in total, which is a different thing from matches. */
  total: number;
  /** Which row is highlighted. Clamped by the caller. */
  index: number;
  onPick: (skill: SkillInfo) => void;
  onHover: (index: number) => void;
}

export function SkillPicker({ query, matches, total, index, onPick, onHover }: Props) {
  return (
    <ul className="skills-menu" id="skills-menu" role="listbox" aria-label="Skills">
      {matches.map((skill, i) => (
        <li
          key={`${skill.source}:${skill.name}`}
          id={skillOptionId(i)}
          role="option"
          aria-selected={i === index}
          className={`skills-item${i === index ? " is-active" : ""}`}
          /*
           * `mousedown`, not `click`, and the default is prevented so the
           * textarea never loses focus: a press that moved the caret out of the
           * field would close the menu it was picking from, and the user would
           * type the arguments into nothing.
           */
          onMouseDown={(event) => {
            event.preventDefault();
            onPick(skill);
          }}
          onMouseEnter={() => onHover(i)}
        >
          <span className="skills-name">/{skill.name}</span>
          {skill.description && (
            <span className="skills-desc" title={skill.description}>
              {skill.description}
            </span>
          )}
          {/* Named only when it is not the project's own file: which root a
              skill came from is worth knowing exactly when it is the surprise. */}
          {skill.source !== "project" && (
            <span className="skills-source">{skill.source}</span>
          )}
        </li>
      ))}

      {/*
        Two empty states, and they say different things. "I have written no
        skills" is a user's first visit and needs the how; "nothing matches what
        I typed" is a typo and needs to say so rather than look like an empty
        install.
      */}
      {matches.length === 0 && (
        <li className="skills-empty" role="presentation">
          {total === 0
            ? "No skills yet — add a .md file under .tonyagent/skills"
            : `No skill matches "/${query}"`}
        </li>
      )}
    </ul>
  );
}
