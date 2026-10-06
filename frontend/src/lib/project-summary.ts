export interface SummarySection {
  heading: string;
  items: string[];
}

export function parseProjectSummary(content: string): SummarySection[] {
  const sections: SummarySection[] = [];
  let current: SummarySection = { heading: "Overview", items: [] };

  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    if (line.startsWith("## ")) {
      if (current.items.length) sections.push(current);
      current = { heading: line.slice(3).trim(), items: [] };
    } else if (line.startsWith("- ")) {
      current.items.push(line.slice(2).trim());
    } else if (current.items.length) {
      current.items[current.items.length - 1] += ` ${line}`;
    } else {
      current.items.push(line);
    }
  }
  if (current.items.length) sections.push(current);
  return sections;
}
