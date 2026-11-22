import EvaluationPage from './Evaluation';
import Preflight from './Preflight';
import StatisticalAudit from './StatisticalAudit';

export type ChatTool =
  | { kind: 'preflight' | 'statistical' }
  | { kind: 'evaluation'; taskId?: string; evaluationId?: string };

const titles: Record<ChatTool['kind'], string> = {
  preflight: 'Check arms and cameras',
  statistical: 'Statistical audit',
  evaluation: 'Evaluate the fine-tune',
};

export default function ChatToolPanel({ tool, onClose }: { tool: ChatTool; onClose: () => void }) {
  let content;
  switch (tool.kind) {
    case 'preflight':
      content = <Preflight embedded />;
      break;
    case 'statistical':
      content = <StatisticalAudit embedded />;
      break;
    case 'evaluation':
      content = tool.taskId
        ? <EvaluationPage key={`${tool.taskId}:${tool.evaluationId ?? ''}`}
          initialTaskId={tool.taskId} initialEvaluationId={tool.evaluationId} embedded />
        : <p>Set up a task in chat to plan its evaluation.</p>;
      break;
  }

  return <section className="chat-inline-workspace chat-tool-panel" aria-label={titles[tool.kind]}>
    <header className="chat-workspace-header">
      <h2>{titles[tool.kind]}</h2>
      <button type="button" className="secondary" onClick={onClose}>Back to chat</button>
    </header>
    <div className="chat-tool-body">{content}</div>
  </section>;
}
