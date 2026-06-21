import { useEffect, useState } from "react";
import { Zap } from "lucide-react";

/** Branded ~1.4s entrance shown when arriving in the panel. */
export function EntryOverlay({ onDone }: { onDone: () => void }) {
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const t1 = setTimeout(() => setLeaving(true), 1050);
    const t2 = setTimeout(onDone, 1500);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [onDone]);

  return (
    <div className={`entry ${leaving ? "leaving" : ""}`}>
      <div className="flex flex-col items-center text-center">
        <div className="entry-mark">
          <span className="entry-ring" />
          <Zap className="h-9 w-9" strokeWidth={2.4} />
        </div>
        <div className="entry-title mt-5 text-[11px] font-semibold uppercase tracking-[5px] text-fg-subtle">
          ELMA
        </div>
        <h1 className="entry-title mt-1 text-2xl font-bold tracking-tight">С возвращением</h1>
        <p className="entry-sub mt-1 text-sm text-fg-muted">Консоль управления</p>
      </div>
    </div>
  );
}
