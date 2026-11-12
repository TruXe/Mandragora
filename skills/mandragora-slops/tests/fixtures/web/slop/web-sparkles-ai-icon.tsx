import { Sparkles } from "lucide-react";

export function Toolbar() {
  return (
    <div className="flex gap-2">
      <button className="inline-flex items-center gap-2 px-3 py-1.5">
        <Sparkles className="h-4 w-4" />
        Generate with AI
      </button>
    </div>
  );
}
