/** Traceability footnote — which detection/scoring/prompt logic (and,
 * when an LLM ran, which models) produced this specific scorecard. See
 * service/app/version.py. Deliberately placed at the bottom of the
 * results, styled like a citation rather than a headline stat: this
 * answers "why did this score change after an evaluation-logic
 * update?" for someone who goes looking, not something every viewer
 * needs to see first. Renders nothing when `versions` is absent
 * (an older cached response, or none configured) rather than showing
 * an empty or placeholder line. */
export function VersionFootnote({ versions }: { versions?: Record<string, string> }) {
  if (!versions || Object.keys(versions).length === 0) return null;

  const order = [
    "detection_version",
    "scoring_version",
    "confidence_derivation_version",
    "semantic_prompt_version",
    "cross_table_prompt_version",
    "generator_model",
    "verifier_model",
  ];
  const labels: Record<string, string> = {
    detection_version: "Detection",
    scoring_version: "Scoring",
    confidence_derivation_version: "Confidence derivation",
    semantic_prompt_version: "Semantic prompt",
    cross_table_prompt_version: "Cross-table prompt",
    generator_model: "Generator",
    verifier_model: "Verifier",
  };

  const parts = order
    .filter((key) => versions[key])
    .map((key) => `${labels[key]} ${versions[key]}`);

  if (parts.length === 0) return null;

  return (
    <p
      className="tabular"
      style={{ fontSize: "0.75rem", color: "var(--text-muted)", margin: "0.25rem 0 0" }}
    >
      {parts.join(" · ")}
    </p>
  );
}
