'use strict';
const $ = id => document.getElementById(id);
let executionId = null;
const urlInput = $('pr-url');
const storeConfigured = $('store-help').dataset.availability === 'configured';
if (storeConfigured) {
  $('record-consent').disabled = false;
  $('load-measurements').disabled = false;
  $('store-help').textContent = 'Optional. Recording saves status, duration and citation counts in your private local store.';
} else {
  $('measurements').textContent = 'No measurement store is configured.';
}

// Mirror the Workspace URL shape for early feedback. Workspace still validates every request.
function isCanonicalPRUrl(value) {
  const match = /^https:\/\/github\.com\/([\w.-]+)\/([\w.-]+)\/pull\/[1-9][0-9]*$/.exec(value);
  return value.length <= 300 && match?.[0] === value &&
    !match.slice(1).some(part => part === '.' || part === '..');
}

urlInput.addEventListener('input', () => {
  urlInput.removeAttribute('aria-invalid');
  $('url-error').textContent = '';
});

function elapsed(milliseconds) {
  return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(2)} s` : `${milliseconds.toFixed(1)} ms`;
}
function element(tag, text, parent) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (parent) parent.append(node);
  return node;
}
function list(title, values, parent) {
  if (!values?.length) return;
  element('h3', title, parent);
  const ul = element('ul', undefined, parent);
  values.forEach(value => element('li', typeof value === 'string' ? value : JSON.stringify(value), ul));
}
async function api(route, payload) {
  const response = await fetch(route, {method:'POST', headers:{'Content-Type':'application/json',
    'X-SCOP-Token':document.querySelector('meta[name="scop-token"]').content}, body:JSON.stringify(payload)});
  const body = await response.json();
  if (body.error) throw new Error(body.error.message);
  if (!response.ok) throw new Error('The local service could not complete the request.');
  return body.result;
}
function citation(source, parent) {
  const box = element('div', undefined, parent);
  const label = {metadata: 'PR metadata', description: 'Author description', diff: 'Changed file'}[source.kind] ?? 'GitHub source';
  try {
    const url = new URL(source.url);
    if (url.protocol === 'https:' && ['github.com','api.github.com'].includes(url.hostname) && !url.username && !url.password) {
      const link = element('a', `${label}: ${source.locator} (opens GitHub in a new tab)`, box);
      link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    } else element('span', 'Unsupported citation URL', box);
  } catch { element('span', 'Invalid citation URL', box); }
  element('p', 'Exact source excerpt', box).className = 'hint excerpt-label';
  element('pre', source.excerpt, box);
}
function render(result) {
  const workspace = result.workspace;
  if (!workspace || workspace.request_error) throw new Error(workspace?.request_error?.message || result.workspace_error?.message || 'No workflow result was returned.');
  const run = workspace.execution;
  if (!run) throw new Error('No execution record was returned.');
  const panel = $('result'); panel.replaceChildren(); panel.hidden = false;
  $('status').textContent = `Workflow ${run.status} · ${elapsed(run.duration_ms)}`;
  element('h2', `Workflow ${run.status}`, panel);
  element('p', `Execution ${run.execution_id}`, panel);
  element('p', `Selected skill: ${run.skill ?? 'Not selected'}`, panel);
  element('p', `Evidence: ${run.references_verified} / ${run.references_checked} references matched`, panel);
  const details = element('details', undefined, panel);
  element('summary', 'Workflow steps and timing', details);
  const steps = element('ol', undefined, details);
  Object.values(run.steps).forEach(step => element('li', `${step.name.replaceAll('_',' ')} — ${step.status} · ${step.duration_ms === null ? 'Not started' : elapsed(step.duration_ms)}`, steps));
  if (run.error_code) element('p', `${run.error_code}: ${run.error_message}`, panel);
  if (run.status === 'completed' && run.summary) {
    element('h2', 'Pull request summary', panel);
    element('p', 'SCOP matched the excerpts to GitHub. Review whether each excerpt supports the claim in context.', panel);
    for (const fact of run.summary.verified_facts) {
      const article = element('article', undefined, panel);
      article.className = 'claim';
      element('p', fact.claim, article).className = 'claim-text';
      const sources = element('details', undefined, article);
      element('summary', `Sources and excerpts (${fact.sources.length})`, sources);
      fact.sources.forEach(source => citation(source, sources));
    }
    list('Assumptions', run.summary.assumptions, panel);
  }
  list('Limitations', [...new Set([...run.limitations, ...(run.summary?.limitations ?? [])])], panel);
  executionId = result.measurement && run.status === 'completed' ? run.execution_id : null;
  $('feedback-panel').hidden = !executionId;
  if (!result.measurement) element('p', 'This execution was not recorded. Feedback storage is unavailable for this run.', panel);
}
$('run-form').addEventListener('submit', async event => {
  event.preventDefault();
  const prUrl = urlInput.value.trim();
  if (!isCanonicalPRUrl(prUrl)) {
    urlInput.setAttribute('aria-invalid', 'true');
    $('url-error').textContent = 'Enter a GitHub pull request URL like https://github.com/pallets/flask/pull/5808. Remove any extra path, query, or fragment.';
    urlInput.focus();
    return;
  }
  const record = storeConfigured && $('record-consent').checked;
  $('run-button').disabled = true; $('result').hidden = true; $('feedback-panel').hidden = true;
  executionId = null; $('feedback-form').querySelector('button').disabled = false; $('feedback-form').reset(); $('feedback-status').textContent = '';
  $('status').textContent = 'Running the workflow… Waiting for the final execution record. Closing this page does not cancel execution.';
  try {
    render(await api('/api/run', {request:{pr_url:prUrl,
      permissions:$('github-consent').checked ? ['github:read-pr-evidence'] : []},
      record_measurement:record,
      permissions:record ? ['local:write-measurements'] : []}));
  } catch (error) { $('status').textContent = `Request error: ${error.message} No successful outcome is assumed.`; }
  finally { $('run-button').disabled = false; }
});
$('feedback-form').addEventListener('submit', async event => {
  event.preventDefault(); if (!executionId) return;
  const button = $('feedback-form').querySelector('button');
  button.disabled = true; $('run-button').disabled = true;
  const evaluation = {decision:$('decision').value};
  for (const field of ['review','rework']) {
    const value = $(field + '-time').value;
    if (value !== '') evaluation[field] = {milliseconds:Math.round(Number(value)*1000), provenance:$('provenance').value};
  }
  try {
    const result = await api('/api/measurement', {operation:'feedback',execution_id:executionId,evaluation,
      permissions:$('feedback-consent').checked ? ['local:write-measurements'] : []});
    $('feedback-status').textContent = `Saved: ${result.feedback.evaluation.decision}. Technical status remains ${result.execution.status}.`;
    executionId = null;
  } catch (error) { $('feedback-status').textContent = error.message; }
  finally { button.disabled = !executionId; $('run-button').disabled = false; }
});
$('load-measurements').addEventListener('click', async () => {
  try {
    const result = await api('/api/measurement', {operation:'export'});
    const panel = $('measurements'); panel.replaceChildren();
    const a = result.aggregate;
    element('p', `${a.recorded_attempts} recorded attempts · ${a.eligible_evaluations} human evaluations`, panel);
    const dl = element('dl', undefined, panel);
    for (const [title, key] of [['Acceptance rate','acceptance_rate'],['Rework rate','rework_rate'],['Citation coverage','citation_verification_coverage'],['Completion rate','workflow_completion_rate']]) {
      const metric = a[key]; element('dt', title, dl);
      element('dd', metric.value === null ? 'Unknown' : `${metric.numerator} / ${metric.denominator}`, dl);
    }
    result.observations.forEach((row, i) => {
      const m = row.measurement;
      element('h3', `Observation ${i+1}: ${row.technical_status} · ${row.decision ?? 'Unreviewed'}`, panel);
      element('p', `Execution: ${m.execution_duration.milliseconds} ms (system-observed)`, panel);
      for (const [label, value] of [['Review',m.human_review_duration],['Rework',m.human_rework_duration]])
        element('p', `${label}: ${value ? value.milliseconds + ' ms (' + value.provenance + ')' : 'Unknown'}`, panel);
      element('p', `Observed total: ${m.total_observed_task_time.milliseconds} ms · ${m.total_observed_task_time.complete ? 'All components supplied' : 'Partial; human timing missing'}`, panel);
    });
  } catch (error) { $('measurements').textContent = error.message; }
});
