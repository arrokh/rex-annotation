// Small fixture reader, not a CommonMark implementation. Never interpret reply HTML.
(() => {
  function inline(parent, text) {
    const tokens = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g;
    let end = 0;
    for (const match of text.matchAll(tokens)) {
      parent.append(text.slice(end, match.index));
      const token = match[0], bold = token.startsWith('**');
      const element = document.createElement(token[0] === '`' ? 'code' : bold ? 'strong' : 'em');
      const width = bold ? 2 : 1;
      element.textContent = token.slice(width, -width);
      parent.append(element);
      end = match.index + token.length;
    }
    parent.append(text.slice(end));
  }

  window.renderFixtureMarkdown = (root, lines) => {
    root.replaceChildren();
    const add = (tag, text, parent = root) => {
      const element = document.createElement(tag);
      if (text !== undefined) inline(element, text);
      parent.append(element);
      return element;
    };
    let paragraph, list, quote;
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const fence = line.match(/^ {0,3}(`{3,}|~{3,})(?:\s*[\w+-]+)?\s*$/);
      const heading = line.match(/^ {0,3}(#{1,6})\s+(.+)$/);
      const item = line.match(/^ {0,3}(?:([-+*])|(\d+)\.)\s+(.+)$/);
      const quoted = line.match(/^ {0,3}>\s?(.*)$/);
      if (fence) {
        const marker = fence[1];
        const closing = new RegExp(`^ {0,3}${marker[0]}{${marker.length},}\\s*$`);
        const code = [];
        while (i + 1 < lines.length && !closing.test(lines[i + 1])) code.push(lines[++i]);
        if (i + 1 < lines.length) i++;
        add('code', undefined, add('pre')).textContent = code.join('\n');
      } else if (heading) {
        add(`h${Math.min(6, heading[1].length + 2)}`, heading[2]);
      } else if (item) {
        const tag = item[2] ? 'ol' : 'ul';
        if (!list || list.localName !== tag) {
          list = add(tag);
          if (item[2]) list.start = Number(item[2]);
        }
        add('li', item[3], list);
      } else if (quoted) {
        quote ??= add('blockquote');
        if (quote.childNodes.length) quote.append('\n');
        inline(quote, quoted[1]);
      } else if (line.trim()) {
        if (paragraph) paragraph.append(' ');
        paragraph ??= add('p');
        inline(paragraph, line);
        list = quote = null;
        continue;
      }
      paragraph = null;
      if (!item) list = null;
      if (!quoted) quote = null;
    }
  };
})();
