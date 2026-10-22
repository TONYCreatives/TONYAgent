/**
 * Renders the token tree from `markdown.ts` as React elements.
 *
 * There is deliberately no `dangerouslySetInnerHTML` anywhere in this file.
 * Assistant text is untrusted output from a remote model; building elements
 * means React escapes every string for us, and the only place a URL reaches the
 * DOM is the `<a href>`, already sanitised by the parser. A string-to-HTML
 * renderer would make each of those a thing to remember instead of a thing the
 * type system enforces.
 */

import { useMemo } from "react";
import { parseMarkdown, type Block, type Inline } from "./markdown.js";

function Inlines({ nodes }: { nodes: Inline[] }) {
  return (
    <>
      {nodes.map((node, index) => (
        <InlineView key={index} node={node} />
      ))}
    </>
  );
}

function InlineView({ node }: { node: Inline }) {
  switch (node.kind) {
    case "text":
      return <>{node.text}</>;
    case "code":
      return <code className="md-code">{node.text}</code>;
    case "strong":
      return (
        <strong>
          <Inlines nodes={node.children} />
        </strong>
      );
    case "em":
      return (
        <em>
          <Inlines nodes={node.children} />
        </em>
      );
    case "strike":
      return (
        <del>
          <Inlines nodes={node.children} />
        </del>
      );
    case "break":
      return <br />;
    case "link":
      // An empty href means the parser rejected the scheme. Keep the text,
      // drop the anchor: a clickable `javascript:` link is the whole reason
      // the scheme check exists.
      if (!node.href) return <Inlines nodes={node.children} />;
      return (
        <a className="md-link" href={node.href} target="_blank" rel="noreferrer noopener">
          <Inlines nodes={node.children} />
        </a>
      );
  }
}

function BlockView({ block }: { block: Block }) {
  switch (block.kind) {
    case "heading":
      // A real heading element would fight the app's own h1/h2 styling and
      // outline; `role="heading"`/`aria-level` keeps the semantics without the
      // cascade.
      return (
        <div className={`md-h md-h${block.level}`} role="heading" aria-level={block.level}>
          <Inlines nodes={block.children} />
        </div>
      );
    case "paragraph":
      return (
        <p className="md-p">
          <Inlines nodes={block.children} />
        </p>
      );
    case "code":
      return (
        <pre className="md-pre">
          <code>{block.text}</code>
        </pre>
      );
    case "list": {
      const items = block.items.map((item, index) => (
        <li key={index}>
          <Inlines nodes={item} />
        </li>
      ));
      return block.ordered ? (
        <ol className="md-list md-ol">{items}</ol>
      ) : (
        <ul className="md-list md-ul">{items}</ul>
      );
    }
    case "quote":
      return (
        <blockquote className="md-quote">
          {block.blocks.map((inner, index) => (
            <BlockView key={index} block={inner} />
          ))}
        </blockquote>
      );
    case "table": {
      // Alignment rides `style` rather than a class per side: three classes
      // for three values is machinery around one CSS property, and the value
      // comes from the document rather than the palette.
      const alignFor = (side: string): "left" | "center" | "right" =>
        side === "center" ? "center" : side === "right" ? "right" : "left";
      return (
        <div className="md-table-wrap">
          <table className="md-table">
            <thead>
              <tr>
                {block.head.map((cell, index) => (
                  <th key={index} style={{ textAlign: alignFor(block.align[index]) }}>
                    <Inlines nodes={cell} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} style={{ textAlign: alignFor(block.align[cellIndex]) }}>
                      <Inlines nodes={cell} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    case "hr":
      return <hr className="md-hr" />;
  }
}

export function MarkdownText({ text }: { text: string }) {
  // Re-parse only when the text changes. During streaming this runs per delta,
  // which is fine: the parser is linear and allocation-light for the sizes a
  // chat message reaches.
  const blocks = useMemo(() => parseMarkdown(text), [text]);
  return (
    <div className="md">
      {blocks.map((block, index) => (
        <BlockView key={index} block={block} />
      ))}
    </div>
  );
}
