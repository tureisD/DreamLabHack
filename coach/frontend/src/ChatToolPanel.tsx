import EvaluationPage from './Evaluation';
import Preflight from './Preflight';
import Repair from './Repair';
import Runs from './Runs';
import StatisticalAudit from './StatisticalAudit';
import Tasks from './Tasks';

export type ChatTool =
  | { kind: 'preflight' | 'statistical' }
  | { kind: 'baseline'; taskId?: string }
  | { kind: 'repair'; taskId: string }
  | { kind: 'runs'; taskId: string; prompt: string }
  | { kind: 'evaluation'; taskId?: string; evaluationId?: string };

const titles: Record<ChatTool['kind'], string> = {
  preflight: 'Check arms and cameras',
  baseline: 'Supervised baseline trials',
  repair: 'Repair first',
  runs: 'Run review',
  statistical: 'Statistical audit',
  evaluation: 'Evaluate the fine-tune',
};

export default function ChatToolPanel({ tool, onClose, onOpen, onTaskSelected, onWork }: {
  tool: ChatTool;
  onClose: () => void;
  onOpen: (tool: ChatTool) => void;
  onTaskSelected: (taskId: string) => void;
  onWork: (kind: 'demos' | 'training', taskId: string) => void;
}) {
  let content;
  switch (tool.kind) {
    case 'preflight':
      content = <Preflight embedded />;
      break;
    case 'statistical':
      content = <StatisticalAudit embedded />;
      break;
    case 'baseline':
      content = <Tasks initialTaskId={tool.taskId} embedded onTaskSelected={onTaskSelected}
        onReview={(taskId, prompt) => onOpen({ kind: 'runs', taskId, prompt })} />;
      break;
    case 'repair':
      content = <Repair initialTaskId={tool.taskId} embedded
        onDemos={(taskId) => onWork('demos', taskId)}
        onTraining={(taskId) => onWork('training', taskId)} />;
      break;
    case 'runs':
      content = <Runs initialPrompt={tool.prompt} embedded />;
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
      {tool.kind === 'runs' && <button type="button" className="secondary"
        onClick={() => onOpen({ kind: 'baseline', taskId: tool.taskId })}>Back to trials</button>}
      <button type="button" className="secondary" onClick={onClose}>Back to chat</button>
    </header>
    <div className="chat-tool-body">{content}</div>
  </section>;
}
