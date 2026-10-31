// SPDX-License-Identifier: AGPL-3.0-or-later
import { Panel } from '../Panel';

/** A plain statement of what is coming; no simulated answers. */
export function AiPanel({ onClose }: { onClose: () => void }) {
  return (
    <Panel
      eyebrow="RESEARCH / PLANNED"
      title="Intelligence"
      subtitle="Arrives in milestone M5."
      onClose={onClose}
    >
      <div className="coming">
        <p>
          The research assistant is not connected yet. When it arrives it will use the models you
          choose: local ones through Ollama or LM Studio, or your own keys for hosted providers.
        </p>
        <ul>
          <li>A small model gathers news and filings; a larger one writes the analysis.</li>
          <li>Every claim cites its source.</li>
          <li>It challenges your thesis, with a pushback level you set.</li>
          <li>It learns from your journal and paper trades, never from anyone else's.</li>
        </ul>
        <p className="muted">
          Until then this panel stays empty on purpose: nothing here pretends to be AI.
        </p>
      </div>
    </Panel>
  );
}
