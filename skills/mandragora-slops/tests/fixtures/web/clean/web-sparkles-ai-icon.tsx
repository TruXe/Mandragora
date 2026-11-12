import { Reply, ListChecks } from "lucide-react";

export function Toolbar() {
  return (
    <div className="flex gap-2">
      <button className="inline-flex items-center gap-2 px-3 py-1.5">
        <Reply className="h-4 w-4" />
        Draft reply
      </button>
      <button className="inline-flex items-center gap-2 px-3 py-1.5">
        <ListChecks className="h-4 w-4" />
        Summarize thread (12 messages)
      </button>
    </div>
  );
}
