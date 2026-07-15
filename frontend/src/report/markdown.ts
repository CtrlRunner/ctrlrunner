// Markdown rendering of a single test result -- powers both the "MD"
// copy button (raw markdown to clipboard) and "Copy prompt" (same body
// wrapped in an AI fix-it instruction).
import type { LogEntry, Step, TestData } from '../shared/types';
import { OUTCOME_LABELS } from '../shared/types';

function fence(content: string, lang = ''): string {
  // Grow the fence if the content itself contains backtick runs.
  let marker = '```';
  while (content.includes(marker)) marker += '`';
  return `${marker}${lang}\n${content.replace(/\n$/, '')}\n${marker}`;
}

function stepsToMarkdown(steps: Step[], depth: number, out: string[]): void {
  for (const s of steps) {
    const mark = s.outcome === 'passed' ? 'x' : ' ';
    out.push(`${'  '.repeat(depth)}- [${mark}] ${s.name} (${s.duration}s)`);
    if (s.error) out.push(`${'  '.repeat(depth + 1)}- error: ${s.error.split('\n')[0]}`);
    if (s.children?.length) stepsToMarkdown(s.children, depth + 1, out);
  }
}

function logsToMarkdown(logs: LogEntry[], out: string[]): void {
  for (const entry of logs) {
    out.push(`### Logs — attempt ${entry.attempt}${entry.truncated ? ' (truncated)' : ''}`);
    if (entry.stdout) {
      out.push('stdout:');
      out.push(fence(entry.stdout));
    }
    if (entry.stderr) {
      out.push('stderr:');
      out.push(fence(entry.stderr));
    }
    if (entry.records.length) {
      out.push('log records:');
      out.push(fence(entry.records.map((r) => `[${r.level}] ${r.name}: ${r.message}`).join('\n')));
    }
    out.push('');
  }
}

export function testToMarkdown(test: TestData): string {
  const out: string[] = [];
  out.push(`# ${test.id}`);
  out.push('');
  const facts: string[] = [];
  facts.push(`- Outcome: ${OUTCOME_LABELS[test.outcome] || test.outcome}`);
  if (test.caseId) facts.push(`- Case ID: ${test.caseId}`);
  facts.push(`- Duration: ${test.duration}s`);
  if (test.attempts > 1) facts.push(`- Attempts: ${test.attempts}`);
  if (test.tags.length) facts.push(`- Tags: ${test.tags.map((t) => `\`${t}\``).join(', ')}`);
  for (const [dim, value] of Object.entries(test.groups || {})) facts.push(`- ${dim}: ${value}`);
  if (test.quarantined) facts.push(`- Quarantined: ${test.quarantineReason || 'no reason given'}`);
  if (test.nearTimeout)
    facts.push('- Near timeout: finished at or above 80% of its configured timeout');
  out.push(...facts);
  out.push('');

  if (test.error) {
    out.push('## Error');
    out.push(fence(test.error));
    out.push('');
  }

  const d = test.assertDetails;
  if (d) {
    out.push('## Assert details');
    out.push(`- expr: \`assert ${d.expr}\``);
    if (d.op) out.push(`- op: \`${d.op}\``);
    if (d.left) out.push(`- left: \`${d.left.repr}\` (${d.left.type})`);
    if (d.right) out.push(`- right: \`${d.right.repr}\` (${d.right.type})`);
    if (typeof d.diff === 'string') out.push(fence(d.diff, 'diff'));
    else if (d.diff) {
      if (d.diff.missing?.length) out.push(`- missing: ${d.diff.missing.join(', ')}`);
      if (d.diff.extra?.length) out.push(`- extra: ${d.diff.extra.join(', ')}`);
    }
    if (d.names) {
      out.push('- values:');
      for (const [k, v] of Object.entries(d.names)) out.push(`  - \`${k} = ${v}\``);
    }
    if (d.truncated) out.push('- (truncated)');
    out.push('');
  }

  if (test.steps?.length) {
    out.push('## Steps');
    stepsToMarkdown(test.steps, 0, out);
    out.push('');
  }

  if (test.logs?.length) logsToMarkdown(test.logs, out);

  if (test.artifacts?.length) {
    out.push('## Artifacts');
    for (const a of test.artifacts)
      out.push(`- ${a.label}${a.embedded ? ' (embedded)' : ` — ${a.href}`}`);
    out.push('');
  }

  const props = Object.entries(test.properties || {});
  if (props.length) {
    out.push('## Properties');
    for (const [k, v] of props) out.push(`- ${k}: ${String(v)}`);
    out.push('');
  }

  return `${out
    .join('\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim()}\n`;
}

export function testToPrompt(test: TestData): string {
  return [
    'The following automated test failed. Analyze the failure and suggest a fix.',
    'Focus on the error trace, assert details and captured logs below.',
    '',
    testToMarkdown(test),
  ].join('\n');
}
