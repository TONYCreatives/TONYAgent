/**
 * A static preview of one subagent card, for looking at the nested work.
 *
 * Not part of the app -- `index.html` is the only entry Vite builds. Run
 * `npm run dev` in `app/` and open `/nested-preview.html`; the transcript is
 * the real `MessageList`, with the real stylesheets, fed the shape
 * `applySubagentEvent` produces from a captured run: a child that ran three
 * tools and answered. It is the shortest honest answer to "what does this
 * look like", and it is disposable.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { MessageList } from "./MessageList.js";
import type { ChatMessage } from "./events.js";
import "./styles.css";

const messages: ChatMessage[] = [
  {
    id: "u1",
    role: "user",
    text: "Speed up the deploy poller, and tell me what you changed.",
    tools: [],
    reasoning: "",
    reasoningComplete: true,
    reasoningTruncated: false,
  },
  {
    id: "a1",
    role: "assistant",
    text:
      "I had a subagent audit the poller while I read the deploy path myself.\n\n" +
      "**What changed:** the fixed 5s sleep became exponential backoff -- 1s " +
      "doubling to a 30s cap, with jitter -- and 4xx responses are no longer " +
      "retried. The child's notes and the three tools it ran are under the " +
      "card above; the edit is in `poller.py`.",
    tools: [
      {
        id: "sub-1",
        name: "subagent",
        status: "ok",
        budget: "Tool call 1/7",
        detail: "subagent poller-audit: 3/10 tool calls",
        child: {
          name: "poller-audit",
          text:
            "The poller sleeps a fixed 5s between attempts and retries " +
            "immediately on 5xx. I added exponential backoff with jitter in " +
            "`poller.py`: base 1s, doubling, capped at 30s, plus 0-250ms " +
            "jitter, and the loop now leaves 4xx alone. Tests pass.",
          tools: [
            { id: "kid-1", name: "read", status: "ok", detail: "Read poller.py (120 lines)" },
            { id: "kid-2", name: "edit", status: "ok", detail: "Edited poller.py: +18/-4" },
            { id: "kid-3", name: "execute_command", status: "ok", detail: "pytest -q: 42 passed" },
          ],
          running: false,
        },
      },
      { id: "read-2", name: "read", status: "ok", detail: "Read deploy.py (60 lines)" },
    ],
    reasoning: "",
    reasoningComplete: true,
    reasoningTruncated: false,
  },
];

const container = document.getElementById("nested-preview");
if (!container) throw new Error("#nested-preview is missing");

createRoot(container).render(
  <StrictMode>
    <MessageList messages={messages} busy={false} project="D:/work/tonyagent" />
  </StrictMode>,
);
