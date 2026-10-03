export type Storage = {
  used_bytes: number;
  limit_bytes: number;
  breakdown?: Record<string, number>;
  files_in_github?: boolean;
};

const mb = (n: number) =>
  n < 1024 * 1024
    ? `${Math.max(1, Math.round(n / 1024))} KB`
    : `${(n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;

export default function StorageMeter({
  storage,
  filesInGitHub,
}: {
  storage: Storage;
  filesInGitHub: boolean;
}) {
  const { used_bytes: used, limit_bytes: limit, breakdown } = storage;
  const pct = Math.min(100, Math.round((used / limit) * 100));
  const tone = pct >= 90 ? "bg-rose" : pct >= 75 ? "bg-amber" : "bg-cyan";
  const parts = Object.entries(breakdown ?? {}).filter(([, n]) => n > 0);

  return (
    <section className="rounded-2xl border border-line bg-card/70 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-sm font-semibold text-text">Database storage</h2>
        <p className="text-sm text-muted">
          {mb(used)} of {mb(limit)} · {pct}%
        </p>
      </div>
      <div
        className="mt-3 h-2 overflow-hidden rounded-full bg-ink/60"
        role="progressbar"
        aria-label="Database storage used"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div className={`h-full ${tone}`} style={{ width: `${Math.max(pct, 1)}%` }} />
      </div>

      {parts.length > 0 && (
        <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12px]">
          {parts.map(([name, n]) => (
            <div key={name} className="flex gap-1.5">
              <dt className="text-faint capitalize">{name}</dt>
              <dd className="text-muted">{mb(n)}</dd>
            </div>
          ))}
        </dl>
      )}

      <p className="mt-3 text-[12px] text-faint">
        The whole database — accounts, documents, and the audit log.{" "}
        {filesInGitHub
          ? "Original files are kept in GitHub, so only their searchable text counts here."
          : "Includes the original files and their searchable text."}{" "}
        {pct >= 90
          ? "Nearly full — delete retired versions you no longer need, or move to a paid plan."
          : pct >= 75
            ? "Getting full — consider deleting retired versions you no longer need."
            : "Plenty of room."}
      </p>
    </section>
  );
}
