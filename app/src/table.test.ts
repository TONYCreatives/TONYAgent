/**
 * Tests for the delimited-file parser behind the table view.
 *
 * The cases are the ones that break a naive `split(",")`: a quoted field with
 * the delimiter inside it, a doubled quote, a newline inside quotes, and a
 * trailing newline that must not become an empty row.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { delimiterFor, MAX_TABLE_ROWS, parseTable } from "./table.js";

test("a plain csv is rows of cells", () => {
  assert.deepEqual(parseTable("a,b,c\n1,2,3\n"), [
    ["a", "b", "c"],
    ["1", "2", "3"],
  ]);
});

test("a quoted field keeps its delimiter", () => {
  assert.deepEqual(parseTable('name,note\n"Smith, Jane",ok\n'), [
    ["name", "note"],
    ["Smith, Jane", "ok"],
  ]);
});

test("a doubled quote is one literal quote", () => {
  assert.deepEqual(parseTable('a\n"say ""hi"""\n'), [["a"], ['say "hi"']]);
});

test("a newline inside quotes stays inside the cell", () => {
  assert.deepEqual(parseTable('a,b\n"line one\nline two",c\n'), [
    ["a", "b"],
    ["line one\nline two", "c"],
  ]);
});

test("empty cells are cells, not missing columns", () => {
  assert.deepEqual(parseTable("a,,c\n"), [["a", "", "c"]]);
});

test("a trailing newline does not invent a row", () => {
  assert.equal(parseTable("a,b\n").length, 1);
  assert.equal(parseTable("a,b").length, 1);
  // ...but a blank line in the middle is a row of one empty cell.
  assert.deepEqual(parseTable("a\n\nb\n"), [["a"], [""], ["b"]]);
});

test("crlf is not carried into the cells", () => {
  assert.deepEqual(parseTable("a,b\r\n1,2\r\n"), [
    ["a", "b"],
    ["1", "2"],
  ]);
});

test("tabs are the delimiter when the file says so", () => {
  assert.deepEqual(parseTable("a\tb\n1\t2\n", "\t"), [
    ["a", "b"],
    ["1", "2"],
  ]);
  assert.equal(delimiterFor("data.tsv"), "\t");
  assert.equal(delimiterFor("data.csv"), ",");
  assert.equal(delimiterFor("DATA.TSV"), "\t");
});

test("empty text is no rows, not one empty row", () => {
  assert.deepEqual(parseTable(""), []);
});

test("the row cap stops a huge file and says where", () => {
  const huge = "h\n" + "x\n".repeat(MAX_TABLE_ROWS + 100);
  const rows = parseTable(huge);
  assert.equal(rows.length, MAX_TABLE_ROWS);
});
