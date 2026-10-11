/**
 * A delimited file, as rows.
 *
 * CSV and TSV are the two "documents" a code project contains that are
 * neither code nor prose, and the useful thing to do with one is to see its
 * *shape* -- which column is which, how many rows, where the empty cells are.
 * The source view is still there, because a viewer that only ever showed a
 * grid would hide the quoting that makes a file parse the way it does.
 *
 * Deliberately small: quoted fields, doubled quotes and embedded newlines are
 * handled because they are what breaks a naive `split(",")` on real data, and
 * nothing else is. No type inference, no delimiter sniffing beyond the tab
 * that names the file, no escaping rules for a dialect nobody here writes.
 */

/** How many rows are shown. A million-row export is not a table to scroll. */
export const MAX_TABLE_ROWS = 2000;

/**
 * Parse delimited text into rows of cells.
 *
 * The tab is chosen by the caller (the file's own extension), because
 * guessing from the content gets it wrong exactly when a CSV has one column.
 */
export function parseTable(text: string, delimiter = ","): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];

    if (quoted) {
      if (character === '"') {
        if (text[index + 1] === '"') {
          // A doubled quote inside a quoted field is one literal quote.
          cell += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += character;
      }
      continue;
    }

    if (character === '"' && cell === "") {
      quoted = true;
      continue;
    }
    if (character === delimiter) {
      row.push(cell);
      cell = "";
      continue;
    }
    if (character === "\n") {
      row.push(cell);
      rows.push(row);
      row = [];
      cell = "";
      if (rows.length >= MAX_TABLE_ROWS) return rows;
      continue;
    }
    if (character === "\r") continue;
    cell += character;
  }

  // The last line has no newline of its own; a file that ends with one has
  // already pushed its final row, and an empty trailing cell is not a row.
  if (cell !== "" || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}

/** The delimiter a file's extension implies. */
export function delimiterFor(path: string): string {
  return path.toLowerCase().endsWith(".tsv") ? "\t" : ",";
}
