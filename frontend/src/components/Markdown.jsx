import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const CITE = /\[(\d+(?:\s*[,;]\s*\d+)*)\]/g;

// Turns [1] / [1, 2] into clickable citation chips that point at the source passages.
export default function Markdown({ text, onCite }) {
  const md = (text || "").replace(CITE, (_, g) =>
    g.split(/[,;]/).map((n) => `[${n.trim()}](cite:${n.trim()})`).join(""));
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={(u) => u}
      components={{
        a: ({ href, children }) =>
          href && href.startsWith("cite:") ? (
            <button className="cite" onClick={() => onCite && onCite(Number(href.slice(5)))}>{children}</button>
          ) : (
            <a href={href} target="_blank" rel="noreferrer">{children}</a>
          ),
      }}
    >
      {md}
    </ReactMarkdown>
  );
}
