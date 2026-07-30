"use client";

export type Escalation = {
  headline?: string;
  guidance?: string;
  reason?: string;
  org_name?: string;
  phone?: string;
  email?: string;
  contact_name?: string;
};

const REASON_HINT: Record<string, string> = {
  no_documents: "No documents have been uploaded to the library yet.",
  no_match: "Nothing in the library matched this question.",
  low_confidence: "The closest matches were only loosely related.",
  model_declined: "The matching passages didn't actually state an answer.",
  no_citations: "No answer could be tied back to a specific passage.",
  safety_refusal: "This question falls outside what the assistant handles.",
  meta_query: "This asked about the assistant itself rather than a policy.",
  error: "A technical problem interrupted the lookup.",
};

export default function EscalationCard({ data }: { data: Escalation }) {
  const { phone, email, org_name, contact_name, reason } = data;
  const hasContact = Boolean(phone || email);

  return (
    <div className="animate-fade-up rounded-2xl border border-amber/35 bg-amber/[0.06] p-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-amber/20 text-sm text-amber">
          !
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium text-text">
            {data.headline || "I don't have a documented answer for this."}
          </p>
          <p className="mt-1.5 text-sm leading-relaxed text-muted">
            I&apos;d rather send you to a person than give you something that might be wrong.
          </p>

          {hasContact ? (
            <div className="mt-4 flex flex-wrap gap-2.5">
              {phone && (
                <a
                  href={`tel:${phone.replace(/[^\d+]/g, "")}`}
                  className="inline-flex items-center gap-2 rounded-xl bg-amber px-4 py-2 text-sm font-semibold text-ink transition hover:brightness-110"
                >
                  Call {phone}
                </a>
              )}
              {email && (
                <a
                  href={`mailto:${email}`}
                  className="inline-flex items-center gap-2 rounded-xl border border-amber/45 px-4 py-2 text-sm font-medium text-amber transition hover:bg-amber/10"
                >
                  Email {email}
                </a>
              )}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-line bg-ink/50 p-3.5 text-sm text-muted">
              Please ask {contact_name || "a supervisor"} at {org_name || "the office"} directly.
              <span className="mt-1.5 block text-xs text-faint">
                An administrator still needs to add the office phone number and email in the
                backend settings, so this assistant can show them here.
              </span>
            </div>
          )}

          <p className="mt-3.5 text-xs text-faint">
            Ask for {contact_name || "assistance"} at {org_name || "the organization"}.
            {reason && REASON_HINT[reason] ? ` (${REASON_HINT[reason]})` : ""}
          </p>
        </div>
      </div>
    </div>
  );
}
