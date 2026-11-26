import { useEffect, useRef, type FormEvent } from 'react';
import { ArrowRight, ArrowUpRight, KeyRound, LockKeyhole } from 'lucide-react';

export default function DreamKeyCard({
  dashboardUrl, hosted, value, onChange, onSubmit, busy, error,
}: {
  dashboardUrl: string;
  hosted: boolean;
  value: string;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  busy: boolean;
  error: string;
}) {
  const title = useRef<HTMLHeadingElement>(null);

  useEffect(() => { title.current?.focus({ preventScroll: true }); }, []);

  return <section className="dream-key-card" aria-labelledby="dream-key-title">
    <header className="dream-key-header">
      <span className="dream-key-icon"><KeyRound size={23} aria-hidden="true" /></span>
      <div>
        <h2 id="dream-key-title" ref={title} tabIndex={-1}>Connect your Dream Labs account</h2>
        <p>Use your Dream account to run models and access your fine-tuned checkpoints.</p>
      </div>
    </header>
    <div className="dream-key-steps">
      <div className="dream-key-create">
        <h3><span aria-hidden="true">1</span> Create an API key</h3>
        <p>Open Dream Labs, sign in, and copy your new key.</p>
        <a href={dashboardUrl} target="_blank" rel="noreferrer">
          Open Dream Labs API Keys <ArrowUpRight size={16} aria-hidden="true" />
        </a>
      </div>
      <form className="dream-key-form" onSubmit={onSubmit} aria-busy={busy}>
        <label htmlFor="dream-key-input"><span aria-hidden="true">2</span> Enter your API key</label>
        <input id="dream-key-input" type="password" autoComplete="off" spellCheck={false} maxLength={300}
          aria-describedby="dream-key-privacy" value={value} onChange={(event) => onChange(event.target.value)}
          placeholder="Paste your Dream Labs API key" readOnly={busy} />
        <button type="submit" disabled={busy || !value.trim()}>
          {busy ? 'Checking access…' : 'Connect Dream Labs'} <ArrowRight size={16} aria-hidden="true" />
        </button>
      </form>
    </div>
    <p className="dream-key-privacy" id="dream-key-privacy">
      <LockKeyhole size={15} aria-hidden="true" />
      <span>{hosted ? 'Your key stays in your private workspace, separate from chat.' : 'Your key is stored locally, separate from chat.'}</span>
    </p>
    {error && <p className="alert" role="alert">{error}</p>}
  </section>;
}
