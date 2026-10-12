/**
 * The pet's entry point: the stylesheet, and a root.
 *
 * The same split as the app's `main.tsx` and for the same reason -- CSS is
 * imported here and never in a component, because a component that imports a
 * stylesheet cannot be loaded by a Node test at all.
 *
 * No `StrictMode`, unlike the app's entry. It is not a policy disagreement: the
 * card's one effect installs the host's status handler and asks the host to flush
 * what it remembered, and StrictMode runs that effect twice in development. The
 * second `ready` is harmless and the second install replaces the first, so this is
 * about not paying for a double round trip on a window whose whole job is to be
 * cheap. The app's own window keeps it, where double-invoking effects have caught
 * real bugs.
 */

import { createRoot } from "react-dom/client";

import { PetCard } from "./petcard.js";
import "./styles.css";

const container = document.getElementById("root");
if (!container) throw new Error("#root is missing from pet.html");

createRoot(container).render(<PetCard />);
