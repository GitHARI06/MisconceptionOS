import React from 'react';
import katex from 'katex';

export const FormattedMathText = ({ text }) => {
  if (!text) return null;

  // Split by inline math ($...$) or LaTeX delimiters \(...\)
  const parts = [];
  const regex = /(\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\(.+?\\\)|\\[[.\s\S]+?\\])/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({
        type: 'text',
        content: text.substring(lastIndex, match.index)
      });
    }

    const rawMath = match[0];
    let cleanMath = rawMath;
    let isBlock = false;

    if (rawMath.startsWith('$$') && rawMath.endsWith('$$')) {
      cleanMath = rawMath.slice(2, -2);
      isBlock = true;
    } else if (rawMath.startsWith('$') && rawMath.endsWith('$')) {
      cleanMath = rawMath.slice(1, -1);
    } else if (rawMath.startsWith('\\(') && rawMath.endsWith('\\)')) {
      cleanMath = rawMath.slice(2, -2);
    } else if (rawMath.startsWith('\\[') && rawMath.endsWith('\\]')) {
      cleanMath = rawMath.slice(2, -2);
      isBlock = true;
    }

    try {
      const html = katex.renderToString(cleanMath, {
        displayMode: isBlock,
        throwOnError: false
      });
      parts.push({ type: 'math', html, isBlock });
    } catch (e) {
      parts.push({ type: 'text', content: rawMath });
    }

    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push({
      type: 'text',
      content: text.substring(lastIndex)
    });
  }

  return (
    <span className="leading-relaxed">
      {parts.map((p, idx) => {
        if (p.type === 'math') {
          return (
            <span
              key={idx}
              className={p.isBlock ? "block my-2 text-center" : "inline-block px-1 text-teal-300 font-mono"}
              dangerouslySetInnerHTML={{ __html: p.html }}
            />
          );
        }
        return <span key={idx}>{p.content}</span>;
      })}
    </span>
  );
};
